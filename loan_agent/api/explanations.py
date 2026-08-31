"""설명 실행 — 재생성 요청과 시도 이력.

설명 생성은 심사와 분리돼 있다. 심사 생성 트랜잭션은 `PENDING` 행만 남기고 LLM은
부르지 않으며, 실제 호출은 별도 실행기의 몫이다. 그래야 제공자 지연이 요청 수명을
지배하지 않고, 설명이 실패해도 판정이 그대로 남는다(ADR-003·ADR-007).

재생성에는 동시성 통제가 붙는다. 진행 중인 시도가 둘 이상 생기면 어느 것이 유효한
설명인지 정해지지 않고, 감사 대상 시스템에서 「그때 무엇이 유효했는지 모른다」는
허용되지 않는다. 애플리케이션이 먼저 걸러내되 최종 판단은 부분 UNIQUE 제약이
내린다 — 앱 검사는 이 API를 거치는 요청만 막기 때문이다(ADR-019).
"""
import uuid

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from loan_agent.api.contract import API_KEY_HEADER
from loan_agent.db import engine as db_engine
from loan_agent import worker
from loan_agent.db.models import (
    AssessmentCase,
    EvalResult,
    ExplanationRun,
    IN_FLIGHT_RUN_STATUSES,
)

router = APIRouter(tags=["explanations"])


def run_payload(run: ExplanationRun, eval_result=None) -> dict:
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
        "explanation_text": run.explanation_text,
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


def runs_with_eval(session, assessment_id: uuid.UUID) -> list:
    """한 심사의 설명 시도를 최신순으로, 각각의 채점 결과와 함께 읽는다."""
    return session.execute(
        select(ExplanationRun, EvalResult)
        .outerjoin(EvalResult, EvalResult.explanation_run_id == ExplanationRun.id)
        .where(ExplanationRun.assessment_id == assessment_id)
        .order_by(ExplanationRun.started_at.desc().nulls_last(), ExplanationRun.id.desc())
    ).all()


@router.post("/api/v1/assessments/{assessment_id}/explanation-runs", status_code=201)
def regenerate_explanation(
    assessment_id: uuid.UUID,
    response: Response,
    api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
):
    if api_key:
        try:
            run_id = worker.run_for_visitor(assessment_id, api_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="심사를 찾을 수 없습니다.") from exc
        except worker.ExplanationRunConflict as exc:
            raise HTTPException(status_code=409, detail="진행 중인 설명 실행이 있습니다.") from exc
        except worker.ExplanationTimedOut as exc:
            raise HTTPException(status_code=503, detail="안내문 제공자가 응답하지 않았습니다.") from exc
        with db_engine.get_sessionmaker()() as session:
            run = session.get(ExplanationRun, run_id)
            payload = run_payload(run)
        response.status_code = status.HTTP_200_OK
        return payload

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
            # 키가 있든 없든 같은 표현을 돌려준다. 형상이 갈리면 클라이언트가 자기
            # 요청에 키를 넣었는지로 파싱을 분기해야 하고, 그것은 ADR-026이 심사
            # 응답에서 결함으로 판정한 형제 비대칭과 같은 형태다. 아직 실행 전이라
            # 대부분의 필드는 비어 있는데, 그 비어 있음 자체가 상태를 말해 준다.
            return run_payload(run)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="진행 중인 설명 실행이 있습니다.") from exc


@router.get("/api/v1/assessments/{assessment_id}/explanation-runs")
def list_explanation_runs(assessment_id: uuid.UUID):
    with db_engine.get_sessionmaker()() as session:
        if session.get(AssessmentCase, assessment_id) is None:
            raise HTTPException(status_code=404, detail="심사를 찾을 수 없습니다.")
        rows = runs_with_eval(session, assessment_id)
        return {"items": [run_payload(run, evaluated) for run, evaluated in rows]}
