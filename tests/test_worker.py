"""설명 실행기 — 작업을 집고, 결과를 기록하고, 실패를 상태로 남긴다.

워커가 없던 동안 `explanation_run`은 `PENDING`으로만 쌓였다. 그래서 모델·프롬프트
버전이 비었고 `eval_result`에는 행이 생기지 않았으며 심사 상태가 `SCREENED`에서
멈춰 네 상태 중 셋이 도달 불가능했다. 아래 테스트는 그 경로가 실제로 이어지는지를
확인한다 — 컬럼이 있다는 것과 채워진다는 것은 다른 사실이다.

LLM은 부르지 않는다. 파이프라인 호출을 대역으로 바꿔 워커의 판단만 검증한다.
실제 호출까지 함께 재면 제공자 상태에 따라 결과가 흔들려 회귀 판정에 쓸 수 없다.
"""
import concurrent.futures
import datetime
import uuid

import pytest
from types import SimpleNamespace

from sqlalchemy.orm import Session

from loan_agent.db import models



class _StubSession:
    """execute_claimed_run이 여는 읽기 세션 대역. 행 조회만 하면 되므로 얇게 둔다."""

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get(self, _model, _pk):
        return SimpleNamespace(id=uuid.uuid4(), assessment_id=uuid.uuid4())

    def expunge(self, _obj):
        pass


def _session(engine) -> Session:
    return Session(bind=engine)


def _pending_case(session, verdict="ELIGIBLE"):
    """심사 하나와 그에 딸린 대기 중 설명 작업을 만든다."""
    case = models.AssessmentCase(
        idempotency_key=str(uuid.uuid4()), request_hash="h", status="SCREENED",
        monthly_income=7_000_000, existing_debt=0, credit_grade=1,
        requested_amount=30_000_000, employment_type="정규직", collateral_owned=False,
    )
    session.add(case)
    session.flush()
    session.add(models.DecisionResult(
        assessment_id=case.id, verdict=verdict, repayment_band="여유", dsr=0.083,
        monthly_payment={}, rule_version="r", product_dataset_version="p",
    ))
    run = models.ExplanationRun(assessment_id=case.id, status="PENDING")
    session.add(run)
    session.flush()
    return case, run


def test_generate_explanation_uses_one_guidance_call_with_persisted_context(monkeypatch):
    """안내문은 저장된 판정·DSR·상품 상세만 주입한 한 번의 LLM 호출이어야 한다."""
    from loan_agent import core, llm, worker

    context = {
        "verdict": "ELIGIBLE",
        "dsr": 0.083,
        "recommendations": [{"상품코드": "A-02", "상품명": "프리미엄대출", "은행": "A은행", "금리범위": "3.0%~5.5%", "최대한도": 100_000_000}],
    }
    captured = {}

    async def guidance(payload, *, api_key=None):
        captured.update(payload=payload, api_key=api_key)
        return {
            "text": "검토 결과 승인 가능한 것으로 판단됩니다(데모 기준). " + core.DISCLAIMER,
            "model_name": "test-model",
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }

    monkeypatch.setattr(worker, "_guidance_context", lambda _id: context)
    monkeypatch.setattr(llm, "generate_guidance", guidance)

    explanation = worker.generate_explanation(SimpleNamespace(id=uuid.uuid4()), api_key="test")

    assert captured == {"payload": context, "api_key": "test"}
    assert explanation.text.endswith(core.DISCLAIMER)
    assert explanation.model_name == "test-model"


def test_claim_takes_one_pending_run(api_db):
    from loan_agent import worker

    with _session(api_db) as session:
        _, run = _pending_case(session)
        session.commit()
        run_id = run.id

    claimed = worker.claim_one()

    assert claimed == run_id
    with _session(api_db) as session:
        assert session.get(models.ExplanationRun, run_id).status == "RUNNING"


def test_claim_returns_none_when_nothing_pending(api_db):
    from loan_agent import worker

    assert worker.claim_one() is None


def test_parallel_claims_never_take_the_same_run(api_db):
    """워커를 여러 개 띄워도 한 작업은 한 번만 실행된다.

    `SKIP LOCKED`가 이미 잡힌 행을 건너뛰는지 보는 테스트다. 이것이 깨지면 같은
    심사에 설명이 두 번 만들어지고 토큰도 두 배로 든다.
    """
    from loan_agent import worker

    with _session(api_db) as session:
        for _ in range(3):
            _pending_case(session)
        session.commit()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        claimed = [f.result() for f in [pool.submit(worker.claim_one) for _ in range(6)]]

    taken = [c for c in claimed if c is not None]
    assert len(taken) == 3
    assert len(set(taken)) == 3


def test_completed_run_records_versions_and_eval(api_db, monkeypatch):
    """통과한 실행은 버전·토큰·설명문과 채점 결과를 남기고 심사를 COMPLETED로 옮긴다."""
    from loan_agent import worker

    with _session(api_db) as session:
        case, run = _pending_case(session)
        session.commit()
        case_id, run_id = case.id, run.id

    monkeypatch.setattr(worker, "generate_explanation", lambda _c: worker.Explanation(
        text="검토 결과 승인 가능한 것으로 판단됩니다(데모 기준).",
        model_name="openai/gpt-4o-mini", prompt_version="v1",
        input_tokens=100, output_tokens=50,
    ))
    monkeypatch.setattr(worker, "score_explanation", lambda *_: worker.Score(
        checks={m: True for m in worker.EVAL_METRICS}, passed=True, detail={},
    ))

    worker.run_once()

    with _session(api_db) as session:
        done = session.get(models.ExplanationRun, run_id)
        assert done.status == "COMPLETED"
        assert done.model_name == "openai/gpt-4o-mini"
        assert done.prompt_version == "v1"
        assert done.input_tokens == 100 and done.output_tokens == 50
        assert done.latency_ms is not None
        assert done.explanation_text
        assert session.get(models.EvalResult, run_id) is not None

        case = session.get(models.AssessmentCase, case_id)
        assert case.status == "COMPLETED"
        assert case.current_explanation_run_id == run_id


def test_provider_failure_becomes_explanation_failed(api_db, monkeypatch):
    """호출이 실패하면 판정을 건드리지 않고 실행만 실패로 남긴다."""
    from loan_agent import worker

    with _session(api_db) as session:
        case, run = _pending_case(session)
        session.commit()
        case_id, run_id = case.id, run.id

    def _boom(_c):
        raise RuntimeError("provider down: token sk-should-not-be-stored")

    monkeypatch.setattr(worker, "generate_explanation", _boom)
    worker.run_once()

    with _session(api_db) as session:
        failed = session.get(models.ExplanationRun, run_id)
        # 실행은 FAILED, 그 심사가 EXPLANATION_FAILED다. 어휘를 겹치지 않게 나눠 뒀다.
        assert failed.status == "FAILED"
        assert failed.explanation_text is None
        # 정규화된 코드만 남는다. 예외 원문에는 자격증명이 섞일 수 있다.
        assert "sk-should-not-be-stored" not in (failed.error_code or "")
        assert session.get(models.AssessmentCase, case_id).status == "EXPLANATION_FAILED"


def test_eval_failure_withholds_the_explanation(api_db, monkeypatch):
    """채점에 실패한 설명은 공개하지 않는다(ADR-007)."""
    from loan_agent import worker

    with _session(api_db) as session:
        case, run = _pending_case(session)
        session.commit()
        case_id, run_id = case.id, run.id

    monkeypatch.setattr(worker, "generate_explanation", lambda _c: worker.Explanation(
        text="승인합니다.", model_name="m", prompt_version="v1",
        input_tokens=10, output_tokens=5,
    ))
    monkeypatch.setattr(worker, "score_explanation", lambda *_: worker.Score(
        checks={m: m != "조건부표현" for m in worker.EVAL_METRICS},
        passed=False, detail={"조건부표현": "확정 표현 사용"},
    ))

    worker.run_once()

    with _session(api_db) as session:
        reviewed = session.get(models.ExplanationRun, run_id)
        assert reviewed.status == "REVIEW_REQUIRED"
        assert reviewed.explanation_text is None
        assert session.get(models.EvalResult, run_id).passed is False
        case = session.get(models.AssessmentCase, case_id)
        assert case.status == "REVIEW_REQUIRED"
        # 통과하지 못한 설명을 유효본으로 가리키지 않는다.
        assert case.current_explanation_run_id is None


def test_stale_running_is_returned_to_pending(api_db):
    """워커가 작업을 집은 채 죽으면 그 행은 아무도 다시 집지 못한다.

    상한을 넘긴 RUNNING을 PENDING으로 되돌린다. 상한값은 ADR-022의 설명 작업
    상한을 그대로 쓴다 — 같은 뜻의 숫자가 두 곳에 생기면 갈라진다.
    """
    from loan_agent import worker

    stale = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=worker.RUN_TIMEOUT_SECONDS + 60
    )
    with _session(api_db) as session:
        _, run = _pending_case(session)
        run.status = "RUNNING"
        run.started_at = stale
        session.commit()
        run_id = run.id

    assert worker.reclaim_stale() == 1

    with _session(api_db) as session:
        assert session.get(models.ExplanationRun, run_id).status == "PENDING"


def test_fresh_running_is_left_alone(api_db):
    """아직 상한 안이면 다른 워커가 일하는 중이므로 건드리지 않는다."""
    from loan_agent import worker

    with _session(api_db) as session:
        _, run = _pending_case(session)
        run.status = "RUNNING"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        run_id = run.id

    assert worker.reclaim_stale() == 0

    with _session(api_db) as session:
        assert session.get(models.ExplanationRun, run_id).status == "RUNNING"


def test_provider_timeout_on_the_worker_path_does_not_crash_the_loop(monkeypatch):
    """워커 경로의 타임아웃은 행에 기록되고 조용히 끝나야 한다.

    예전에는 타임아웃 분기에 return이 없어 아래로 흘러내렸고, 할당된 적 없는
    explanation을 읽어 UnboundLocalError가 났다. 그 예외는 run_once를 거쳐 main()의
    루프까지 올라가 워커 프로세스를 종료시킨다 — 제공자가 한 번 느려지면 서버 키
    경로가 통째로 멈춘다.
    """
    from loan_agent import worker

    finished = []
    monkeypatch.setattr(worker, "generate_explanation",
                        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("provider")))
    monkeypatch.setattr(worker, "_finish",
                        lambda run_id, exp, score, code, ms: finished.append(code))
    monkeypatch.setattr(worker, "Session", _StubSession)
    monkeypatch.setattr(worker.db_engine, "get_engine", lambda: None)

    worker.execute_claimed_run(uuid.uuid4())

    assert finished == ["PROVIDER_TIMEOUT"]


def test_provider_timeout_on_the_visitor_path_still_raises(monkeypatch):
    """동기 경로는 같은 타임아웃을 예외로 올려 API가 503을 낼 수 있어야 한다."""
    from loan_agent import worker

    monkeypatch.setattr(worker, "generate_explanation",
                        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("provider")))
    monkeypatch.setattr(worker, "_finish", lambda *_a, **_k: None)
    monkeypatch.setattr(worker, "Session", _StubSession)
    monkeypatch.setattr(worker.db_engine, "get_engine", lambda: None)

    with pytest.raises(worker.ExplanationTimedOut):
        worker.execute_claimed_run(uuid.uuid4(), api_key="k", raise_timeout=True)


def test_usage_tokens_reads_objects_and_dicts(monkeypatch):
    """토큰은 crewai 객체에서도 읽혀야 한다.

    예전 추출식은 dict일 때만 동작해 실제 실행(UsageMetrics 객체)에서는 두 값이
    항상 None이었다. 픽스처는 dict라 테스트만으로는 드러나지 않던 자리다.
    """
    from types import SimpleNamespace
    from loan_agent import worker

    assert worker._usage_tokens(None) == (None, None)
    assert worker._usage_tokens({"prompt_tokens": 3, "completion_tokens": 4}) == (3, 4)
    obj = SimpleNamespace(prompt_tokens=11, completion_tokens=22)
    assert worker._usage_tokens(obj) == (11, 22)
