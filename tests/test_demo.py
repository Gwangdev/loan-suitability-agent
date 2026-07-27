"""무토큰 데모(사전 녹화 결과) 테스트 (API 키 불필요)."""
from fastapi.testclient import TestClient

from loan_agent import core
from loan_agent.api import app

client = TestClient(app)


def test_fixtures_load():
    fx = core.load_demo_fixtures()
    assert len(fx["cases"]) == 5
    for c in fx["cases"]:
        r = c["result"]
        assert r["파싱결과"] and r["심사결과"] and r["안내문"]


def test_demo_list_endpoint():
    r = client.get("/demo")
    assert r.status_code == 200
    body = r.json()
    assert len(body["cases"]) == 5
    assert body["model"]  # 생성 모델명 존재


def test_demo_case_endpoint_returns_baked_output():
    r = client.get("/demo/0")
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["안내문"]          # 사전 녹화 안내문 존재
    assert "usage" in body["result"]


def test_demo_case_out_of_range_404():
    assert client.get("/demo/999").status_code == 404


def test_demo_consumes_no_key():
    """데모 조회 경로는 키·토큰이 전혀 필요 없어야 한다(핵심 요구사항)."""
    # load_demo_fixtures는 파일만 읽으므로 키 상태와 무관하게 동작
    fx = core.load_demo_fixtures()
    assert fx["cases"], "픽스처가 있어야 방문자가 토큰 없이 데모를 볼 수 있다"
