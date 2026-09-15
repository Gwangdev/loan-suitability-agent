"""설명 실행기 — 대기 중인 설명 작업을 집어 실행하고 결과를 기록한다.

심사 생성은 `explanation_run(PENDING)` 행만 남기고 LLM을 부르지 않는다(ADR-003).
그 행을 집어 실제로 실행하는 것이 이 모듈이고, 없으면 작업이 쌓이기만 해서 모델·
프롬프트 버전이 영원히 비고 심사가 `SCREENED`에서 멈춘다(ADR-023).

큐 인프라를 쓰지 않는다. 큐가 하는 일은 「작업을 안전하게 하나씩 꺼내주기」인데
PostgreSQL의 `FOR UPDATE SKIP LOCKED`가 같은 보장을 주고 DB는 어차피 쓰고 있다.
저장소를 하나 더 들이면 같은 일을 하는 곳이 둘이 된다.

**작업을 집는 것과 실행하는 것을 분리한다.** 행을 `RUNNING`으로 바꾸고 곧바로 커밋해
잠금을 놓은 뒤에 LLM을 부른다. 잠금을 쥔 채 호출하면 10~30초 동안 행과 커넥션이 함께
묶여, ADR-003이 트랜잭션 밖으로 밀어낸 문제가 이 안에서 되살아난다.

실행: python -m loan_agent.worker
"""
import dataclasses
import datetime
import logging
import os
import time
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from loan_agent import core, llm, decision, logs, eval as evaluator
from loan_agent.db import engine as db_engine
from loan_agent.db import models

logger = logging.getLogger(__name__)

EVAL_METRICS = evaluator.METRICS

# 파싱정확도는 LLM 파서의 JSON을 규칙 파서 정답과 대조하는 지표다. 이 경로는 저장된 구조화 값으로 안내문을
# 한 번 생성할 뿐 파싱을 하지 않아 대조할 출력이 없다. 통과로 채우면 채점의 부재가 통과라는 주장이 되므로
# 값을 비워 두고, 공개 여부는 이 경로가 실제로 채점하는 지표만으로 정한다.
UNSCORED_METRICS = ("파싱정확도",)
SCORED_METRICS = tuple(m for m in EVAL_METRICS if m not in UNSCORED_METRICS)

# ADR-022가 정한 설명 작업 상한을 그대로 쓴다. 같은 뜻의 숫자를 여기서 새로 정하면
# 두 값이 갈라지고, 어느 쪽이 맞는지 나중에 알 수 없다.
RUN_TIMEOUT_SECONDS = core.EXPLANATION_RUN_TIMEOUT_SECONDS

# 프롬프트를 고치면 이 값을 올린다. 모델명과 나누어 두는 이유는 둘이 독립적으로
# 바뀌기 때문이다 — 합치면 품질 변화가 모델 탓인지 프롬프트 탓인지 가릴 수 없다(ADR-005).
PROMPT_VERSION = "guidance-2026.08"

POLL_INTERVAL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "2"))


@dataclasses.dataclass(frozen=True)
class Explanation:
    text: str
    model_name: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None


@dataclasses.dataclass(frozen=True)
class Score:
    checks: dict
    passed: bool
    detail: dict


class ExplanationRunConflict(Exception):
    """이미 다른 실행자가 아직 유효한 RUNNING 행을 보유한 경우."""


class ExplanationTimedOut(Exception):
    """ADR-022의 설명 실행 상한을 넘긴 경우."""


def claim_one() -> uuid.UUID | None:
    """대기 중인 작업 하나를 집어 RUNNING으로 바꾸고 곧바로 커밋한다.

    `SKIP LOCKED`가 다른 워커에게 이미 잡힌 행을 건너뛴다. 그래서 워커를 여럿 띄워도
    같은 대기 행을 두 워커가 동시에 집지 않고, 그 보장을 애플리케이션 조건문이 아니라 DB가 준다.
    다만 상한을 넘긴 RUNNING은 `reclaim_stale`이 대기로 되돌리므로, 느린 실행이 아직 살아 있을 때
    회수되면 같은 작업이 한 번 더 실행될 수 있다. 외부 호출의 정확히 한 번 실행은 보장하지 않는다.
    """
    with Session(bind=db_engine.get_engine()) as session, session.begin():
        run_id = session.execute(
            text(
                "SELECT id FROM explanation_run "
                " WHERE status = 'PENDING' ORDER BY id "
                "   FOR UPDATE SKIP LOCKED LIMIT 1"
            )
        ).scalar()
        if run_id is None:
            return None
        run = session.get(models.ExplanationRun, run_id)
        run.status = "RUNNING"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        return run.id


def reclaim_stale() -> int:
    """상한을 넘긴 RUNNING을 PENDING으로 되돌린다.

    작업을 집은 워커가 죽으면 행이 RUNNING인 채 남아 아무도 다시 집지 못한다.
    상한 안이면 다른 워커가 일하는 중이므로 건드리지 않는다.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=RUN_TIMEOUT_SECONDS
    )
    with Session(bind=db_engine.get_engine()) as session, session.begin():
        stale = session.execute(
            select(models.ExplanationRun)
            .where(models.ExplanationRun.status == "RUNNING")
            .where(models.ExplanationRun.started_at < cutoff)
        ).scalars().all()
        for run in stale:
            run.status = "PENDING"
            run.started_at = None
        return len(stale)


def claim_for_visitor(assessment_id: uuid.UUID) -> uuid.UUID:
    """방문자 키 요청이 기존 PENDING 또는 스테일 RUNNING 행을 집는다.

    행을 RUNNING으로 바꾸는 트랜잭션은 여기서 끝낸다. LLM 호출을 같은 트랜잭션에
    넣으면 커넥션을 장시간 점유해 ADR-003의 분리 규칙을 깨기 때문이다.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=RUN_TIMEOUT_SECONDS
    )
    with Session(bind=db_engine.get_engine()) as session, session.begin():
        case = session.get(models.AssessmentCase, assessment_id)
        if case is None:
            raise KeyError(assessment_id)
        run = session.execute(
            select(models.ExplanationRun)
            .where(models.ExplanationRun.assessment_id == assessment_id)
            .where(models.ExplanationRun.status.in_(("PENDING", "RUNNING")))
            # id는 uuid4라 정렬해도 시간순이 아니다. 지금은 in-flight 행이 최대
            # 하나라 어느 쪽을 집어도 같지만, 코드가 「최신 행」을 고른다고 읽히면서
            # 실제로는 임의 선택인 상태를 남겨 두지 않는다.
            .order_by(models.ExplanationRun.started_at.desc().nullslast())
            .with_for_update()
        ).scalars().first()
        if (
            run is not None
            and run.status == "RUNNING"
            and run.started_at is not None
            and run.started_at >= cutoff
        ):
            raise ExplanationRunConflict(assessment_id)
        if run is None:
            run = models.ExplanationRun(assessment_id=assessment_id, status="PENDING")
            session.add(run)
            session.flush()
        run.status = "RUNNING"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        return run.id


def _guidance_context(assessment_id: uuid.UUID) -> dict:
    """DB에 확정 저장된 판정과 추천 상세만 안내문 입력으로 만든다."""
    with Session(bind=db_engine.get_engine()) as session:
        decision_row = session.get(models.DecisionResult, assessment_id)
        recommendations = session.execute(
            select(models.Recommendation)
            .where(models.Recommendation.assessment_id == assessment_id)
            .where(models.Recommendation.eligible.is_(True))
            .order_by(models.Recommendation.rank)
        ).scalars().all()
    return {
        # 저장은 영문 enum이지만 이 값은 고객이 읽을 문장으로 들어간다. 한글 어휘로
        # 되돌리지 않으면 모델이 그대로 직역한다(ADR-012).
        "verdict": decision.VERDICT_LABEL.get(decision_row.verdict, decision_row.verdict),
        "repayment_band": decision.BAND_LABEL.get(decision_row.repayment_band, decision_row.repayment_band),
        "dsr": float(decision_row.dsr),
        "recommendations": [row.reason_codes for row in recommendations],
    }


def _usage_tokens(usage) -> tuple[int | None, int | None]:
    """토큰 사용량을 객체와 dict 양쪽에서 꺼낸다.

    crewai는 `crew.usage_metrics`로 UsageMetrics 객체를 주고 녹화 픽스처는 dict를 준다.
    예전 추출식은 삼항 조건이 전체 식을 dict인 경우로 묶어, 객체를 처리하려고 넣은
    getattr 분기가 도달할 수 없었다 — 그래서 실제 실행에서는 두 값이 항상 None이었다.
    """
    if usage is None:
        return None, None
    if isinstance(usage, dict):
        return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


def generate_explanation(case: models.AssessmentCase, api_key: str | None = None) -> Explanation:
    """저장된 결정 데이터를 주입해 안내문을 한 번 생성한다."""
    import asyncio

    result = asyncio.run(
        asyncio.wait_for(
            llm.generate_guidance(_guidance_context(case.id), api_key=api_key),
            timeout=RUN_TIMEOUT_SECONDS,
        )
    )
    usage = result.get("usage")
    input_tokens, output_tokens = _usage_tokens(usage)
    guidance = result.get("text") or ""
    if core.DISCLAIMER not in guidance:
        guidance = f"{guidance}\n\n{core.DISCLAIMER}"
    return Explanation(
        text=guidance,
        model_name=result.get("model_name") or llm.get_model_name(),
        prompt_version=PROMPT_VERSION,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def score_explanation(case: models.AssessmentCase, explanation: Explanation) -> Score:
    """생성된 안내문을 기존 Eval 지표로 채점한다.

    채점기를 새로 만들지 않고 회귀 검증에 쓰는 것과 같은 것을 쓴다. 둘이 갈라지면
    「평가를 통과했다」가 어느 기준의 통과인지 알 수 없어진다.
    """
    parsed = {
        "월소득": case.monthly_income, "부채": case.existing_debt,
        "신용등급": case.credit_grade, "희망금액": case.requested_amount,
        "직장유형": case.employment_type, "담보보유": case.collateral_owned,
    }
    scored = evaluator.score_case({
        "name": str(case.id),
        "input": "",
        "expected_parse": parsed,
        "result": {"파싱결과": None, "심사결과": None, "안내문": explanation.text},
    })
    checks = dict(scored["checks"])
    detail = dict(scored["detail"])
    # 공용 채점기는 파서 출력이 없으면 파싱 실패로 채점하고 근거까지 남긴다. 이 경로에서는 그 판정도 근거도
    # 측정 결과가 아니므로 함께 지운다. 공개 여부를 「값이 있는 지표」로 계산하지 않는 이유는, 채점 대상
    # 지표가 실수로 비어 돌아오면 판단에서 조용히 빠져 통과하지 못한 안내문이 공개될 수 있기 때문이다.
    for metric in UNSCORED_METRICS:
        checks[metric] = None
        detail.pop(metric, None)
    passed = all(checks.get(m) for m in SCORED_METRICS)
    return Score(checks=checks, passed=passed, detail=detail)


def _finish(run_id: uuid.UUID, explanation: Explanation | None, score: Score | None,
            error_code: str | None, elapsed_ms: int, *, claimed_at: datetime.datetime | None) -> bool:
    """실행 결과를 한 트랜잭션에 기록하고 심사 상태를 함께 옮긴다. 기록했으면 True, 버렸으면 False.

    기록은 이 실행자가 집은 행이 아직 그대로일 때만 한다. `reclaim_stale`은 죽은 워커의 작업을 살리려고
    상한을 넘긴 RUNNING을 되돌리는데, 실행자가 죽은 것이 아니라 느렸을 뿐이면 다른 실행자가 같은 행을
    다시 집어 끝낼 수 있다. 그 뒤 늦게 도착한 결과를 그대로 쓰면 완료된 실행과 심사가 덮였다. 그래서
    집을 때 적힌 `started_at`을 표식으로 삼아, 행을 잠근 뒤 상태가 RUNNING이고 표식이 같을 때만 쓴다.
    되돌리면 `started_at`이 비고 다시 집으면 새 시각이 적히므로 표식이 반드시 달라진다. 기존 컬럼으로
    판정하므로 데이터 모델은 바뀌지 않는다.
    """
    with Session(bind=db_engine.get_engine()) as session, session.begin():
        run = session.get(models.ExplanationRun, run_id, with_for_update=True)
        if run.status != "RUNNING" or run.started_at != claimed_at:
            logger.warning("explanation run result discarded: run no longer held by this executor",
                           extra={"run_id": str(run_id)})
            return False
        case = session.get(models.AssessmentCase, run.assessment_id)
        run.finished_at = datetime.datetime.now(datetime.timezone.utc)
        run.latency_ms = elapsed_ms

        if error_code is not None:
            # 실행 상태와 심사 상태는 어휘가 다르다. 실행은 FAILED이고 그 심사가
            # EXPLANATION_FAILED가 된다 — 하나의 시도가 실패한 것과 심사 전체가
            # 설명을 얻지 못한 것은 다른 사실이기 때문이다(ADR-012).
            run.status = "FAILED"
            run.error_code = error_code
            case.status = "EXPLANATION_FAILED"
            return True

        run.model_name = explanation.model_name
        run.prompt_version = explanation.prompt_version
        run.input_tokens = explanation.input_tokens
        run.output_tokens = explanation.output_tokens
        session.add(models.EvalResult(
            explanation_run_id=run.id,
            parse_accuracy=score.checks["파싱정확도"],
            verdict_consistency=score.checks["판정정합성"],
            disclaimer_present=score.checks["디스클레이머"],
            recommendation_consistency=score.checks["추천정합성"],
            numeric_grounding=score.checks["수치근거"],
            conditional_language=score.checks["조건부표현"],
            passed=score.passed,
            detail=score.detail,
        ))

        if not score.passed:
            # 통과하지 못한 설명은 저장도 노출도 하지 않고 유효본으로 가리키지도 않는다(ADR-007).
            run.status = "REVIEW_REQUIRED"
            case.status = "REVIEW_REQUIRED"
            return True

        run.status = "COMPLETED"
        run.explanation_text = explanation.text
        case.status = "COMPLETED"
        case.current_explanation_run_id = run.id
        return True


def execute_claimed_run(
    run_id: uuid.UUID,
    *,
    api_key: str | None = None,
    raise_timeout: bool = False,
) -> None:
    """이미 RUNNING으로 커밋된 행을 실행하고 결과를 같은 행에 기록한다.

    `raise_timeout`은 응답을 기다리는 동기 호출자(방문자 경로)를 뜻한다. 워커 경로는 결과를 행에 남기고
    조용히 끝나면 되지만, 동기 호출자는 무엇이 일어났는지 받아야 한다. 그래서 시간 초과뿐 아니라
    이 실행자가 행을 더는 보유하지 않아 결과가 버려진 경우도 예외로 올린다. 버려졌는데 정상 반환하면
    호출자가 남이 실행 중인 행을 결과로 받는다. 형제 경로가 이미 쓰는 `ExplanationRunConflict`로 알린다.
    """
    with Session(bind=db_engine.get_engine()) as session:
        run = session.get(models.ExplanationRun, run_id)
        # 집을 때 적힌 시각이 이 실행자가 행을 보유하고 있다는 표식이다. 결과를 쓸 때 다시 대조한다.
        claimed_at = run.started_at
        case = session.get(models.AssessmentCase, run.assessment_id)
        session.expunge(case)

    started = time.monotonic()
    try:
        explanation = generate_explanation(case, api_key=api_key) if api_key else generate_explanation(case)
        score = score_explanation(case, explanation)
    except TimeoutError as exc:
        held = _finish(run_id, None, None, "PROVIDER_TIMEOUT", int((time.monotonic() - started) * 1000),
                       claimed_at=claimed_at)
        if raise_timeout:
            if not held:
                raise ExplanationRunConflict(case.id) from exc
            raise ExplanationTimedOut(run_id) from exc
        # 동기 경로만 예외를 올린다. 워커 경로는 행에 기록하고 조용히 끝내야 하는데,
        # return이 없으면 아래 _finish로 흘러내려 할당된 적 없는 explanation·score를
        # 읽는다. 그 UnboundLocalError는 run_once를 거쳐 main()의 루프까지 올라가
        # 워커 프로세스를 죽인다.
        return
    except Exception:
        # 제공자 예외 원문에는 자격증명이 섞일 수 있다. 저장뿐 아니라 로그에도 남기지
        # 않고 실행 식별자와 정규화된 코드만 기록한다.
        logger.error("explanation run failed: %s", run_id, extra={"run_id": str(run_id)})
        held = _finish(run_id, None, None, "PROVIDER_ERROR", int((time.monotonic() - started) * 1000),
                       claimed_at=claimed_at)
        if raise_timeout and not held:
            raise ExplanationRunConflict(case.id)
        return

    held = _finish(run_id, explanation, score, None, int((time.monotonic() - started) * 1000),
                   claimed_at=claimed_at)
    if raise_timeout and not held:
        raise ExplanationRunConflict(case.id)


def run_once() -> bool:
    """작업 하나를 처리한다. 집을 것이 없으면 False."""
    run_id = claim_one()
    if run_id is None:
        return False
    execute_claimed_run(run_id)
    return True


def run_for_visitor(assessment_id: uuid.UUID, api_key: str) -> uuid.UUID:
    """방문자 키로 기존 실행 행을 동기 처리한다. 키는 호출 체인 밖에 저장하지 않는다."""
    run_id = claim_for_visitor(assessment_id)
    execute_claimed_run(run_id, api_key=api_key, raise_timeout=True)
    return run_id


def main() -> None:  # pragma: no cover - 실행 진입점
    logs.configure()
    logger.info("explanation worker started")
    while True:
        reclaim_stale()
        if not run_once():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    main()
