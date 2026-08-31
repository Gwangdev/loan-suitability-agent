"""무토큰 데모(사전 녹화 결과) — 픽스처 계층 테스트 (API 키 불필요).

HTTP 표면(`GET /api/v1/demo-cases`)에 대한 테스트는 그 항목을 구현할 때 함께 쓴다.
여기 남은 것은 표면과 무관하게 성립해야 하는 사실 — 픽스처가 읽히는가, 그리고 그
경로가 키를 요구하지 않는가 — 이며, 표면이 바뀌어도 깨지지 않아야 한다.
"""
from loan_agent import core


def test_fixtures_load():
    fx = core.load_demo_fixtures()
    assert len(fx["cases"]) == 5
    for c in fx["cases"]:
        r = c["result"]
        assert r["파싱결과"] and r["심사결과"] and r["안내문"]


def test_demo_consumes_no_key():
    """데모 조회 경로는 키·토큰이 전혀 필요 없어야 한다(핵심 요구사항)."""
    # load_demo_fixtures는 파일만 읽으므로 키 상태와 무관하게 동작
    fx = core.load_demo_fixtures()
    assert fx["cases"], "픽스처가 있어야 방문자가 토큰 없이 데모를 볼 수 있다"
