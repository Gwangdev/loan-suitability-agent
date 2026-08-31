"""방문자 키 처리 테스트 (crewai·네트워크 불필요).

핵심 요구사항: 키가 없으면 명확한 ValueError로 막고, 방문자 키는 인자로만 전달되어
os.environ을 오염시키지 않아야 한다(공유 프로세스 키 누출 방지).
"""
import pytest

from loan_agent import core, llm


def test_get_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        llm.get_llm()  # crewai import 전에 키 검증 → 무거운 의존성 없이도 ValueError


def test_visitor_key_not_written_to_environ(monkeypatch):
    """방문자 키를 인자로 넘겨도 os.environ에는 남지 않아야 한다(누출 방지).
    (키가 유효하지 않아 이후 단계에서 실패하더라도, 환경변수 오염이 없어야 함.)"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        llm.get_llm(api_key="sk-visitor-fake")
    except Exception:
        pass  # crewai 유무·키 유효성과 무관 — 관심사는 environ 오염 여부뿐
    assert "OPENAI_API_KEY" not in __import__("os").environ


def test_has_api_key_reflects_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert llm.has_api_key() is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm.has_api_key() is False


def test_every_module_resolves_its_own_names():
    """모듈이 쓰는 이름이 전부 그 모듈에서 해결되는지 확인한다.

    llm.py를 core.py에서 떼어낼 때 re·json 임포트가 따라오지 않아 parse_with_llm이
    NameError로 죽었다. 테스트가 그 함수를 대역으로 바꾸고 있어 아무도 눈치채지
    못했고, 실제 키로 처음 돌렸을 때 드러났다. 대역은 함수를 안 부르므로 함수 안의
    임포트 누락을 영원히 못 잡는다 — 그래서 호출이 아니라 이름 해석을 검사한다.
    """
    import ast
    import builtins
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "loan_agent"
    problems = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bound = {"__file__", "__name__", "__doc__"} | set(dir(builtins))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                bound |= {a.asname or a.name for a in node.names}
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Assign):
                bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                bound.add(node.target.id)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, (ast.comprehension,)) and isinstance(node.target, ast.Name):
                bound.add(node.target.id)
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                bound.add(node.target.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
                bound.add(node.optional_vars.id)
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        unresolved = sorted(used - bound)
        if unresolved:
            problems[path.name] = unresolved

    assert not problems, f"모듈에서 해결되지 않는 이름: {problems}"
