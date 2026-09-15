"""Streamlit UI의 결정적 심사가 API 계층을 거치는지 확인한다."""
from loan_agent import app


def test_submit_assessment_posts_structured_form_with_idempotency_key(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"assessment_id": "a", "verdict": "ELIGIBLE"}

    def post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(app.httpx, "post", post)
    result = app._submit_assessment({"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False})

    assert result["verdict"] == "ELIGIBLE"
    assert captured["url"].endswith("/api/v1/assessments")
    assert captured["json"]["monthly_income"] == 7_000_000
    assert captured["headers"]["Idempotency-Key"]
    assert captured["timeout"] == 10.0


def test_submit_assessment_uses_a_new_key_for_each_new_confirmed_submission(monkeypatch):
    keys = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"assessment_id": "a", "verdict": "ELIGIBLE"}

    def post(_url, *, json, headers, timeout):
        keys.append(headers["Idempotency-Key"])
        return Response()

    monkeypatch.setattr(app.httpx, "post", post)
    customer = {"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False}
    app._submit_assessment(customer)
    app._submit_assessment(customer)

    assert keys[0] != keys[1]


def test_visitor_key_explanation_runs_inside_a_progress_indicator(monkeypatch):
    """방문자 키로 안내문을 만드는 동안 화면에 진행 표시가 떠 있어야 한다.

    이 경로는 심사 제출과 안내문 실행을 동기로 기다리므로 수 초가 걸리는데, 화면에는 아무
    표시가 없어 버튼을 눌렀는지조차 알 수 없었다. 두 요청이 모두 진행 표시가 켜진 동안
    나가는지를 고정한다 — 표시가 요청보다 늦게 켜지거나 먼저 꺼지면 이 테스트가 깨진다.
    """
    state = {"spinning": False, "messages": []}
    calls = []

    class Spinner:
        def __init__(self, text):
            state["messages"].append(text)

        def __enter__(self):
            state["spinning"] = True

        def __exit__(self, *exc):
            state["spinning"] = False
            return False

    class Response:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    def post(url, *, json=None, headers, timeout):
        calls.append((url, state["spinning"]))
        if url.endswith("/explanation-runs"):
            return Response({"explanation_text": "안내문", "input_tokens": 1, "output_tokens": 1})
        return Response({"assessment_id": "a", "verdict": "ELIGIBLE"})

    monkeypatch.setattr(app.st, "spinner", Spinner)
    monkeypatch.setattr(app.httpx, "post", post)
    customer = {"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False}

    assessment, payload = app._run_explanation(customer, "sk-visitor")

    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["assessments", "explanation-runs"]
    assert all(spinning for _, spinning in calls), "진행 표시가 꺼진 채로 요청이 나갔다"
    assert state["spinning"] is False, "요청이 끝난 뒤에도 진행 표시가 남았다"
    assert state["messages"] and state["messages"][0]
    assert assessment["assessment_id"] == "a"
    assert payload["explanation_text"] == "안내문"


def test_withheld_message_names_failed_metrics_in_korean_without_the_overall_flag():
    """검사를 통과하지 못한 이유는 한글 지표명으로만 알려 준다.

    거짓인 값을 모두 미달 지표로 세면 전체 통과 여부(`passed`)까지 지표처럼 나오고, API의 영문
    필드명이 그대로 화면에 나간다. API는 영문, 화면은 한글이라는 경계를 화면 쪽에서 지킨다.
    """
    payload = {
        "status": "REVIEW_REQUIRED",
        "eval_result": {
            "parse_accuracy": True,
            "verdict_consistency": True,
            "disclaimer_present": True,
            "recommendation_consistency": False,
            "numeric_grounding": False,
            "conditional_language": True,
            "passed": False,
            "detail": {"추천정합성": "사유"},
        },
    }

    message = app._withheld_message(payload)

    assert "추천정합성" in message and "수치근거" in message
    assert "passed" not in message
    assert "recommendation_consistency" not in message and "numeric_grounding" not in message


def test_withheld_message_does_not_count_an_unscored_metric_as_failed():
    """채점하지 않은 지표(null)는 미달이 아니다. 설명 실행의 파싱정확도가 그렇다."""
    payload = {
        "status": "REVIEW_REQUIRED",
        "eval_result": {
            "parse_accuracy": None,
            "verdict_consistency": True,
            "disclaimer_present": True,
            "recommendation_consistency": True,
            "numeric_grounding": False,
            "conditional_language": True,
            "passed": False,
            "detail": {"수치근거": "사유"},
        },
    }

    message = app._withheld_message(payload)

    assert "수치근거" in message
    assert "파싱정확도" not in message


def _status_error(code, headers=None):
    import httpx

    request = httpx.Request("POST", "http://api.test/api/v1/assessments/x/explanation-runs")
    response = httpx.Response(code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(str(code), request=request, response=response)


def test_explanation_error_message_tells_timeout_conflict_and_rate_limit_apart():
    """실패 사유가 다르면 방문자가 할 일도 다르므로 안내를 나눈다.

    모든 예외를 한 문구로 받으면 제공자 시간 초과, 이미 진행 중인 실행, 요청 상한을 구분할 수
    없고, 서버 상한보다 클라이언트 대기를 길게 잡아 503 안내를 받으려던 설계가 화면에서 쓰이지 않는다.
    """
    timeout = app._explanation_error_message(_status_error(503))
    conflict = app._explanation_error_message(_status_error(409))
    limited = app._explanation_error_message(_status_error(429, {"Retry-After": "120"}))
    generic = app._explanation_error_message(RuntimeError("boom"))

    assert len({timeout, conflict, limited, generic}) == 4
    assert "120" in limited


def test_an_explanation_attempt_counts_toward_the_cap_and_cooldown_even_when_it_fails(monkeypatch):
    """요청을 보낸 시도는 결과와 무관하게 세션 횟수와 쿨다운에 반영한다.

    성공했을 때만 세면, 모델 호출이 실제로 나간 뒤 시간 초과로 끝난 시도는 횟수에도 쿨다운에도
    잡히지 않아 곧바로 다시 실행할 수 있었다. 요청을 보내기 전에 기록한다.
    """
    import httpx

    class Spinner:
        def __init__(self, _text):
            pass

        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    class Response:
        def __init__(self, body, error=None):
            self._body, self._error = body, error

        def raise_for_status(self):
            if self._error:
                raise self._error

        def json(self):
            return self._body

    def post(url, *, json=None, headers, timeout):
        if url.endswith("/explanation-runs"):
            return Response({}, error=_status_error(503))
        return Response({"assessment_id": "a"})

    monkeypatch.setattr(app.st, "spinner", Spinner)
    monkeypatch.setattr(app.httpx, "post", post)
    attempts = {"run_count": 2}
    customer = {"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False}

    try:
        app._run_explanation(customer, "sk-visitor", attempts=attempts, now=123.0)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("503 응답이 예외로 올라오지 않았다")

    assert attempts["run_count"] == 3
    assert attempts["last_run_ts"] == 123.0


def test_a_failed_assessment_submission_spends_no_attempt_and_reads_like_the_deterministic_path(monkeypatch):
    """심사 제출에서 끝난 시도는 모델 호출이 나가지 않았으므로 세션 횟수와 쿨다운을 쓰지 않는다.

    제출 전에 기록하던 때는 심사 서비스에 닿지 못한 실패까지 10회 중 한 번을 쓰고 「AI 안내문 생성 중
    오류」로 안내했다. 같은 실패를 결정적 심사 버튼은 「심사 서비스에 연결할 수 없습니다」로 안내한다.
    """
    import httpx

    class Spinner:
        def __init__(self, _text):
            pass

        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    calls = []

    def post(url, *, json=None, headers, timeout):
        calls.append(url)
        raise httpx.ConnectError("unreachable", request=httpx.Request("POST", url))

    monkeypatch.setattr(app.st, "spinner", Spinner)
    monkeypatch.setattr(app.httpx, "post", post)
    attempts = {"run_count": 2, "last_run_ts": 50.0}
    customer = {"월소득": 7_000_000, "부채": 0, "신용등급": 1, "희망금액": 30_000_000, "직장유형": "정규직", "담보보유": False}

    try:
        app._run_explanation(customer, "sk-visitor", attempts=attempts, now=123.0)
    except Exception as exc:
        message = app._explanation_error_message(exc)
    else:
        raise AssertionError("제출 실패가 예외로 올라오지 않았다")

    assert [url.rsplit("/", 1)[-1] for url in calls] == ["assessments"]
    assert attempts == {"run_count": 2, "last_run_ts": 50.0}
    assert message == app.ASSESSMENT_UNAVAILABLE_MESSAGE


def test_usage_cost_uses_input_and_output_token_rates():
    cost = app._usage_cost_usd({"prompt_tokens": 1_000, "completion_tokens": 500})

    assert cost == app.Decimal("0.00045")


def test_screen_from_assessment_carries_every_field_the_table_renders():
    """API 응답만으로 대안 비교표를 그릴 수 있어야 한다.

    운영에서 KeyError로 화면이 죽었다. 데모 픽스처 경로는 screen_loan을 다시 돌려
    아홉 필드를 전부 갖지만, 실제 심사 경로는 API 응답을 옮기므로 API가 주지 않는
    필드는 없다. 두 경로가 같은 렌더 함수를 쓰는데 구조가 달랐던 것이다.

    표가 읽는 키를 여기에 고정한다. 화면이 새 열을 요구하면 이 테스트가 먼저 깨진다.
    """
    from loan_agent import app

    assessment = {
        "decision": {
            "verdict": "ELIGIBLE", "repayment_band": "COMFORTABLE",
            "dsr": 0.097, "monthly_payment": {"합계": 289992},
        },
        "recommendations": [{
            "product_code": "B-01", "rank": 1, "eligible": True,
            "product_name": "무담보신용대출", "bank": "B은행",
            "interest_rate_range": "6.0%~12.0%", "maximum_limit": 30000000,
            "repayment_method": "원리금균등", "rate_type": "변동",
            "early_repayment_fee": 1.0, "approval_margin": 0,
        }],
    }

    screen = app._screen_from_assessment(assessment)
    후보 = screen["추천후보"][0]

    for key in ("상품코드", "상품명", "은행", "금리범위",
                "상환방식", "금리방식", "중도상환수수료", "승인여유마진"):
        assert key in 후보, f"대안 비교표가 읽는 키가 없다: {key}"
        assert 후보[key] is not None, f"API가 값을 주지 않았다: {key}"
