"""설명 실행 경로의 채점 — 채점하지 않은 지표를 통과로 적지 않는다.

안내문은 저장된 구조화 값을 넣어 LLM을 한 번 부를 뿐 파싱을 하지 않으므로, 이 경로에는 파싱정확도가
대조할 파서 출력이 없다. 예전에는 이 지표를 통과로 덮어 기록했고, 공용 채점기가 같은 입력에서 만든
「파싱 실패」 근거는 그대로 남아 한 행 안에서 컬럼과 근거가 서로 반대를 말했다. 채점 대상이 아닌 지표는
값을 비워 두고, 공개 여부는 이 경로가 채점 대상으로 정한 지표만으로 판단한다.

공개 여부를 「값이 비어 있지 않은 지표」로 계산하면 채점 대상 지표가 실수로 비어 돌아올 때 조용히
판단에서 빠진다. 마지막 테스트가 그 방향을 막는다.
"""
import uuid
from types import SimpleNamespace

from loan_agent import core, worker
from tests.test_eval import GOOD_ADVICE


def _case():
    return SimpleNamespace(
        id=uuid.uuid4(), monthly_income=7_000_000, existing_debt=0, credit_grade=1,
        requested_amount=30_000_000, employment_type="정규직", collateral_owned=False,
    )


def _explanation(text):
    return worker.Explanation(
        text=text, model_name="test-model", prompt_version="test-prompt",
        input_tokens=None, output_tokens=None,
    )


def test_parse_accuracy_is_left_unscored_on_the_explanation_path():
    score = worker.score_explanation(_case(), _explanation(GOOD_ADVICE))

    assert score.checks["파싱정확도"] is None
    assert "파싱정확도" not in score.detail
    assert score.passed is True


def test_a_failing_scored_metric_still_withholds_the_explanation():
    score = worker.score_explanation(_case(), _explanation(GOOD_ADVICE.replace(core.DISCLAIMER, "")))

    assert score.checks["디스클레이머"] is False
    assert score.passed is False


def test_a_scored_metric_that_comes_back_empty_does_not_pass(monkeypatch):
    real = worker.evaluator.score_case

    def empty_numeric_grounding(case):
        scored = real(case)
        scored["checks"] = {**scored["checks"], "수치근거": None}
        return scored

    monkeypatch.setattr(worker.evaluator, "score_case", empty_numeric_grounding)

    assert worker.score_explanation(_case(), _explanation(GOOD_ADVICE)).passed is False
