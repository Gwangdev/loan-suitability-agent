"""POST /api/v1/assessments — 구조화 입력을 받아 결정적 판정을 한 트랜잭션에 저장한다.

이 엔드포인트가 관통 논리의 실물이 나오는 자리다. 판정은 결정적 계층이 산출하고
(`decision.decide` → `core.screen_loan`), LLM은 여기서 부르지 않는다. 대신 설명 작업을
`explanation_run(PENDING)` 행으로 심사와 같은 트랜잭션에 넣어, 커밋과 작업 발행이
원자적이 되게 한다. 별도 아웃박스 테이블 없이 아웃박스 패턴의 성질을 얻는다(ADR-003).

멱등성은 세 겹이다. 클라이언트의 `Idempotency-Key`, 요청 본문의 해시, 그리고
`assessment_case`의 UNIQUE 제약. 선조회로 대부분의 재요청을 싸게 걸러내지만, READ
COMMITTED에서 조회와 삽입 사이에 경쟁이 있으므로 최종 판단은 UNIQUE 위반을 잡아
현재 상태를 다시 읽는 쪽이 내린다(ADR-004). 같은 키·같은 요청이면 기존 심사를 200으로,
같은 키·다른 요청이면 409로 답한다.
"""
import hashlib
import json
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from loan_agent import decision
from loan_agent import core
from loan_agent.db import engine as db_engine
from loan_agent.db.models import (
    AssessmentCase,
    AuditEvent,
    DecisionResult,
    ExplanationRun,
    IN_FLIGHT_RUN_STATUSES,
    Recommendation,
)

router = APIRouter(tags=["assessments"])

# 화면은 한글 라벨을 쓰지만 직장유형은 판정 입력이자 도메인 데이터이므로(CSV 컬럼과
# 같은 취급) 한글 값을 그대로 계약에 노출한다. 임의 문자열을 막아 오탐을 줄인다.
EMPLOYMENT_TYPES = ("정규직", "계약직", "제한없음")


class AssessmentRequest(BaseModel):
    # 명세에 없는 필드가 조용히 무시되면 클라이언트의 오타를 잡지 못한다.
    model_config = ConfigDict(extra="forbid")

    # 월소득이 0이면 DSR이 정의되지 않는다. 상환능력을 판정할 수 없는 입력은
    # 심사 대상이 아니므로 여기서 막는다.
    monthly_income: int = Field(gt=0)
    existing_debt: int = Field(ge=0)
    credit_grade: int = Field(ge=1, le=10)
    requested_amount: int = Field(gt=0)
    employment_type: str = Field(pattern="^(" + "|".join(EMPLOYMENT_TYPES) + ")$")
    collateral_owned: bool = False


class ParsingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)


def _request_hash(payload: AssessmentRequest) -> str:
    """검증을 통과한 값의 정규화 표현을 해시한다. 같은 뜻의 요청이 같은 해시를 낸다."""
    canonical = json.dumps(
        payload.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _persist(session, payload: AssessmentRequest, idempotency_key: str, request_hash: str) -> uuid.UUID:
    """심사·판정·추천·설명작업·감사이벤트를 한 트랜잭션에 쓴다. 커밋은 호출자가 한다."""
    decided = decision.decide(
        monthly_income=payload.monthly_income,
        existing_debt=payload.existing_debt,
        credit_grade=payload.credit_grade,
        requested_amount=payload.requested_amount,
        employment_type=payload.employment_type,
        collateral_owned=payload.collateral_owned,
    )

    case = AssessmentCase(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="SCREENED",
        monthly_income=payload.monthly_income,
        existing_debt=payload.existing_debt,
        credit_grade=payload.credit_grade,
        requested_amount=payload.requested_amount,
        employment_type=payload.employment_type,
        collateral_owned=payload.collateral_owned,
    )
    session.add(case)
    session.flush()

    session.add(
        DecisionResult(
            assessment_id=case.id,
            verdict=decided["verdict"],
            repayment_band=decided["repayment_band"],
            dsr=decided["dsr"],
            monthly_payment=decided["monthly_payment"],
            rule_version=decided["rule_version"],
            product_dataset_version=decided["product_dataset_version"],
        )
    )
    for rec in decided["recommendations"]:
        session.add(
            Recommendation(
                assessment_id=case.id,
                product_code=rec["product_code"],
                rank=rec["rank"],
                eligible=rec["eligible"],
                reason_codes=rec["reason_codes"],
            )
        )

    session.add(ExplanationRun(assessment_id=case.id, status="PENDING"))
    session.add(
        AuditEvent(
            correlation_id=uuid.uuid4(),
            actor_type="consultant",
            action="assessment.created",
            target_type="assessment_case",
            target_id=case.id,
            metadata_={"verdict": decided["verdict"]},
        )
    )
    session.flush()
    return case.id


def _serialize(session, assessment_id: uuid.UUID) -> dict:
    """저장된 심사를 응답 본문으로 옮긴다. 생성 직후에도 재요청 응답에도 같은 모양이다."""
    case = session.get(AssessmentCase, assessment_id)
    result = session.get(DecisionResult, assessment_id)
    recommendations = (
        session.execute(
            select(Recommendation)
            .where(Recommendation.assessment_id == assessment_id)
            .order_by(Recommendation.rank)
        )
        .scalars()
        .all()
    )
    run = (
        session.execute(
            select(ExplanationRun)
            .where(ExplanationRun.assessment_id == assessment_id)
            .where(ExplanationRun.status.in_(IN_FLIGHT_RUN_STATUSES))
            .order_by(ExplanationRun.id)
        )
        .scalars()
        .first()
    )

    return {
        "assessment_id": str(case.id),
        "status": case.status,
        "verdict": result.verdict,
        "repayment_band": result.repayment_band,
        "dsr": float(result.dsr),
        "monthly_payment": result.monthly_payment,
        "recommendations": [
            {"product_code": r.product_code, "rank": r.rank} for r in recommendations
        ],
        "rule_version": result.rule_version,
        "product_dataset_version": result.product_dataset_version,
        "explanation_run": {"id": str(run.id), "status": run.status} if run else None,
    }


def _replay(session, existing: AssessmentCase, request_hash: str, response: Response) -> dict:
    """이미 존재하는 심사 — 같은 요청이면 200으로 그대로, 다른 요청이면 409."""
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="같은 Idempotency-Key로 다른 내용의 요청이 왔습니다.",
        )
    response.status_code = status.HTTP_200_OK
    return _serialize(session, existing.id)


def _run_payload(run: ExplanationRun, eval_result=None) -> dict:
    """설명 시도 메타데이터만 노출한다. 원문 프롬프트는 저장하지도 응답하지도 않는다."""
    return {
        "id": str(run.id),
        "status": run.status,
        "model_name": run.model_name,
        "prompt_version": run.prompt_version,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "latency_ms": run.latency_ms,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "error_code": run.error_code,
        "eval_result": (
            {
                "parse_accuracy": eval_result.parse_accuracy,
                "verdict_consistency": eval_result.verdict_consistency,
                "disclaimer_present": eval_result.disclaimer_present,
                "recommendation_consistency": eval_result.recommendation_consistency,
                "numeric_grounding": eval_result.numeric_grounding,
                "conditional_language": eval_result.conditional_language,
                "passed": eval_result.passed,
                "detail": eval_result.detail,
            }
            if eval_result else None
        ),
    }


def _assessment_detail(session, assessment_id: uuid.UUID) -> dict:
    case = session.get(AssessmentCase, assessment_id)
    if case is None:
        raise HTTPException(status_code=404, detail="심사를 찾을 수 없습니다.")
    result = session.get(DecisionResult, assessment_id)
    recommendations = session.execute(
        select(Recommendation)
        .where(Recommendation.assessment_id == assessment_id)
        .order_by(Recommendation.rank)
    ).scalars().all()
    from loan_agent.db.models import EvalResult

    rows = session.execute(
        select(ExplanationRun, EvalResult)
        .outerjoin(EvalResult, EvalResult.explanation_run_id == ExplanationRun.id)
        .where(ExplanationRun.assessment_id == assessment_id)
        .order_by(ExplanationRun.started_at.desc().nulls_last(), ExplanationRun.id.desc())
    ).all()
    return {
        "assessment_id": str(case.id),
        "status": case.status,
        "created_at": case.created_at.isoformat(),
        "decision": {
            "verdict": result.verdict,
            "repayment_band": result.repayment_band,
            "dsr": float(result.dsr),
            "monthly_payment": result.monthly_payment,
            "rule_version": result.rule_version,
            "product_dataset_version": result.product_dataset_version,
        },
        "recommendations": [
            {"product_code": row.product_code, "rank": row.rank, "eligible": row.eligible}
            for row in recommendations
        ],
        "explanation_runs": [_run_payload(run, evaluated) for run, evaluated in rows],
    }


def _encode_cursor(created_at: datetime, assessment_id: uuid.UUID) -> str:
    raw = json.dumps({"created_at": created_at.isoformat(), "id": str(assessment_id)})
    return urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(value["created_at"]), uuid.UUID(value["id"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="cursor 형식이 올바르지 않습니다.") from exc


@router.post("/api/v1/assessments", status_code=201)
def create_assessment(
    payload: AssessmentRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    request_hash = _request_hash(payload)
    sessionmaker = db_engine.get_sessionmaker()

    with sessionmaker() as session:
        existing = session.scalar(
            select(AssessmentCase).where(
                AssessmentCase.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return _replay(session, existing, request_hash, response)

    try:
        with sessionmaker.begin() as session:
            assessment_id = _persist(session, payload, idempotency_key, request_hash)
            return _serialize(session, assessment_id)
    except IntegrityError:
        # 선조회 이후 다른 요청이 같은 키로 먼저 커밋했다. UNIQUE가 그것을 잡았으므로
        # 이제 커밋된 심사를 읽어 재요청으로 답한다 — 이 경로가 최종 방어선이다.
        with sessionmaker() as session:
            existing = session.scalar(
                select(AssessmentCase).where(
                    AssessmentCase.idempotency_key == idempotency_key
                )
            )
            if existing is None:
                raise
            return _replay(session, existing, request_hash, response)


@router.get("/api/v1/assessments/{assessment_id}")
def get_assessment(assessment_id: uuid.UUID):
    with db_engine.get_sessionmaker()() as session:
        return _assessment_detail(session, assessment_id)


@router.get("/api/v1/assessments")
def list_assessments(
    status_filter: Literal["SCREENED", "COMPLETED", "EXPLANATION_FAILED", "REVIEW_REQUIRED"] | None = Query(default=None, alias="status"),
    period_from: datetime | None = Query(default=None, alias="from"),
    period_to: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    statement = select(AssessmentCase)
    if status_filter is not None:
        statement = statement.where(AssessmentCase.status == status_filter)
    if period_from is not None:
        statement = statement.where(AssessmentCase.created_at >= period_from)
    if period_to is not None:
        statement = statement.where(AssessmentCase.created_at <= period_to)
    if cursor is not None:
        created_at, assessment_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                AssessmentCase.created_at < created_at,
                and_(AssessmentCase.created_at == created_at, AssessmentCase.id < assessment_id),
            )
        )
    statement = statement.order_by(AssessmentCase.created_at.desc(), AssessmentCase.id.desc()).limit(limit + 1)
    with db_engine.get_sessionmaker()() as session:
        cases = session.execute(statement).scalars().all()
        page, trailing = cases[:limit], cases[limit:]
        return {
            "items": [
                {"assessment_id": str(case.id), "status": case.status, "created_at": case.created_at.isoformat()}
                for case in page
            ],
            "next_cursor": _encode_cursor(page[-1].created_at, page[-1].id) if trailing else None,
        }


@router.post("/api/v1/assessments/{assessment_id}/explanation-runs", status_code=201)
def regenerate_explanation(assessment_id: uuid.UUID):
    sessionmaker = db_engine.get_sessionmaker()
    try:
        with sessionmaker.begin() as session:
            if session.get(AssessmentCase, assessment_id) is None:
                raise HTTPException(status_code=404, detail="심사를 찾을 수 없습니다.")
            active = session.scalar(
                select(ExplanationRun.id)
                .where(ExplanationRun.assessment_id == assessment_id)
                .where(ExplanationRun.status.in_(IN_FLIGHT_RUN_STATUSES))
            )
            if active is not None:
                raise HTTPException(status_code=409, detail="진행 중인 설명 실행이 있습니다.")
            run = ExplanationRun(assessment_id=assessment_id, status="PENDING")
            session.add(run)
            session.flush()
            return {"id": str(run.id), "status": run.status}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="진행 중인 설명 실행이 있습니다.") from exc


@router.get("/api/v1/assessments/{assessment_id}/explanation-runs")
def list_explanation_runs(assessment_id: uuid.UUID):
    with db_engine.get_sessionmaker()() as session:
        if session.get(AssessmentCase, assessment_id) is None:
            raise HTTPException(status_code=404, detail="심사를 찾을 수 없습니다.")
        from loan_agent.db.models import EvalResult

        rows = session.execute(
            select(ExplanationRun, EvalResult)
            .outerjoin(EvalResult, EvalResult.explanation_run_id == ExplanationRun.id)
            .where(ExplanationRun.assessment_id == assessment_id)
            .order_by(ExplanationRun.started_at.desc().nulls_last(), ExplanationRun.id.desc())
        ).all()
        return {"items": [_run_payload(run, evaluated) for run, evaluated in rows]}


@router.post("/api/v1/parsing-preview")
def parsing_preview(payload: ParsingPreviewRequest):
    candidate = core.rule_based_parse(payload.text)
    return {"candidate": candidate, "missing_fields": core.missing_required_fields(candidate)}


@router.get("/api/v1/demo-cases")
def demo_cases():
    return core.load_demo_fixtures()
