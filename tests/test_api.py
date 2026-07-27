"""FastAPI 서비스 계층 테스트 (API 키 불필요).

키가 필요한 /advise 는 실제 LLM을 호출하지 않고,
(1) 필수필드 누락 → 422, (2) 키 부재 → 503 두 방어 경로만 검증한다(비용 0).
"""
import pytest
from fastapi.testclient import TestClient

from loan_agent.api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_products():
    r = client.get("/products")
    assert r.status_code == 200
    assert r.json()["count"] == 22


def test_parse():
    r = client.post("/parse", json={
        "text": "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요."})
    assert r.status_code == 200
    body = r.json()
    assert body["parsed"]["월소득"] == 7000000
    assert body["missing_required"] == []


def test_screen_approves_good_customer():
    r = client.post("/screen", json={
        "월소득": 7000000, "부채": 0, "신용등급": 1,
        "희망금액": 30000000, "직장유형": "정규직", "담보보유": False})
    assert r.status_code == 200
    body = r.json()
    assert body["판정"] == "승인가능"
    assert body["추천상품"] is not None
    assert 1 <= len(body["추천후보"]) <= 3


def test_screen_hard_case_has_no_recommendation():
    r = client.post("/screen", json={
        "월소득": 1800000, "부채": 30000000, "신용등급": 6,
        "희망금액": 10000000, "직장유형": "제한없음"})
    assert r.status_code == 200
    body = r.json()
    assert body["판정"] == "어려움"
    assert body["추천상품"] is None


def test_screen_validation_rejects_bad_grade():
    # 신용등급 범위(1~10) 밖 → Pydantic 422
    r = client.post("/screen", json={
        "월소득": 3000000, "신용등급": 99, "희망금액": 10000000})
    assert r.status_code == 422


def test_advise_missing_fields_returns_422():
    # 필수 정보 없는 입력 → LLM 호출 전에 422로 차단(비용 0)
    r = client.post("/advise", json={"text": "안녕하세요 대출 문의합니다"})
    assert r.status_code == 422
    assert "missing_required" in r.json()["detail"]


def test_advise_without_key_returns_503(monkeypatch):
    # 키를 비워 LLM 파이프라인 진입 직전 503으로 안내되는지(네트워크 호출 없음)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    r = client.post("/advise", json={
        "text": "월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요."})
    assert r.status_code == 503
