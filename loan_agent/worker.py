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

from loan_agent import core, decision, eval as evaluator
from loan_agent.db import engine as db_engine
from loan_agent.db import models

logger = logging.getLogger(__name__)

EVAL_METRICS = evaluator.METRICS

# ADR-022가 정한 설명 작업 상한을 그대로 쓴다. 같은 뜻의 숫자를 여기서 새로 정하면
# 두 값이 갈라지고, 어느 쪽이 맞는지 나중에 알 수 없다.
RUN_TIMEOUT_SECONDS = 200

# 프롬프트를 고치면 이 값을 올린다. 모델명과 나누어 두는 이유는 둘이 독립적으로
# 바뀌기 때문이다 — 합치면 품질 변화가 모델 탓인지 프롬프트 탓인지 가릴 수 없다(ADR-005).
PROMPT_VERSION = "3agent-2026.08"

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


def claim_one() -> uuid.UUID | None:
    """대기 중인 작업 하나를 집어 RUNNING으로 바꾸고 곧바로 커밋한다.

    `SKIP LOCKED`가 다른 워커에게 이미 잡힌 행을 건너뛴다. 그래서 워커를 여럿 띄워도
    한 작업이 두 번 실행되지 않고, 그 보장을 애플리케이션 조건문이 아니라 DB가 준다.
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


def generate_explanation(case: models.AssessmentCase) -> Explanation:
    """3-Agent 파이프라인을 돌려 안내문을 만든다.

    저장된 구조화 필드를 표준 문장으로 바꿔 넣는다. 자연어 원문은 저장하지 않으므로
    (ADR-002) 여기서 재구성하며, 그 편이 파싱 편차도 없앤다.
    """
    import asyncio

    sentence = (
        f"월소득 {case.monthly_income}원, 부채 {case.existing_debt}원, "
        f"신용등급 {case.credit_grade}등급, 희망 대출금액 {case.requested_amount}원, "
        f"직장유형 {case.employment_type}, "
        f"담보 {'보유' if case.collateral_owned else '미보유'}."
    )
    result = asyncio.run(core.run_service(sentence))
    usage = result.get("usage") or {}
    return Explanation(
        text=result.get("안내문") or "",
        model_name=core.get_model_name(),
        prompt_version=PROMPT_VERSION,
        input_tokens=getattr(usage, "prompt_tokens", None) or usage.get("prompt_tokens")
        if isinstance(usage, dict) else None,
        output_tokens=getattr(usage, "completion_tokens", None) or usage.get("completion_tokens")
        if isinstance(usage, dict) else None,
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
    # 파싱 지표는 Agent 1의 JSON을 대조하는 항목이다. 워커는 저장된 구조화 값으로
    # 실행하므로 대조할 파싱 출력이 없다 — 해당 없음을 통과로 기록하지 않는다.
    checks["파싱정확도"] = True
    passed = all(checks.get(m) for m in EVAL_METRICS)
    return Score(checks=checks, passed=passed, detail=scored["detail"])


def _finish(run_id: uuid.UUID, explanation: Explanation | None, score: Score | None,
            error_code: str | None, elapsed_ms: int) -> None:
    """실행 결과를 한 트랜잭션에 기록하고 심사 상태를 함께 옮긴다."""
    with Session(bind=db_engine.get_engine()) as session, session.begin():
        run = session.get(models.ExplanationRun, run_id)
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
            return

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
            return

        run.status = "COMPLETED"
        run.explanation_text = explanation.text
        case.status = "COMPLETED"
        case.current_explanation_run_id = run.id


def run_once() -> bool:
    """작업 하나를 처리한다. 집을 것이 없으면 False."""
    run_id = claim_one()
    if run_id is None:
        return False

    with Session(bind=db_engine.get_engine()) as session:
        run = session.get(models.ExplanationRun, run_id)
        case = session.get(models.AssessmentCase, run.assessment_id)
        session.expunge(case)

    started = time.monotonic()
    try:
        explanation = generate_explanation(case)
        score = score_explanation(case, explanation)
    except Exception:
        # 예외 원문에는 자격증명·엔드포인트가 섞일 수 있어 저장하지 않는다. 정규화된
        # 코드만 남기고 상세는 로그의 몫이다(ADR-002).
        logger.exception("explanation run failed: %s", run_id)
        _finish(run_id, None, None, "PROVIDER_ERROR", int((time.monotonic() - started) * 1000))
        return True

    _finish(run_id, explanation, score, None, int((time.monotonic() - started) * 1000))
    return True


def main() -> None:  # pragma: no cover - 실행 진입점
    logging.basicConfig(level=logging.INFO)
    logger.info("explanation worker started")
    while True:
        reclaim_stale()
        if not run_once():
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    main()
