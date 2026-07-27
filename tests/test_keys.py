"""방문자 키 처리 테스트 (crewai·네트워크 불필요).

핵심 요구사항: 키가 없으면 명확한 ValueError로 막고, 방문자 키는 인자로만 전달되어
os.environ을 오염시키지 않아야 한다(공유 프로세스 키 누출 방지).
"""
import pytest

from loan_agent import core


def test_get_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        core.get_llm()  # crewai import 전에 키 검증 → 무거운 의존성 없이도 ValueError


def test_visitor_key_not_written_to_environ(monkeypatch):
    """방문자 키를 인자로 넘겨도 os.environ에는 남지 않아야 한다(누출 방지).
    (키가 유효하지 않아 이후 단계에서 실패하더라도, 환경변수 오염이 없어야 함.)"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        core.get_llm(api_key="sk-visitor-fake")
    except Exception:
        pass  # crewai 유무·키 유효성과 무관 — 관심사는 environ 오염 여부뿐
    assert "OPENAI_API_KEY" not in __import__("os").environ


def test_has_api_key_reflects_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert core.has_api_key() is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert core.has_api_key() is False
