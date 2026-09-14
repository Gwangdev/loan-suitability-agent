"""방문자 키 처리 테스트 (crewai·네트워크 불필요).

핵심 요구사항: 키가 없으면 명확한 ValueError로 막고, 방문자 키는 인자로만 전달되어
os.environ을 오염시키지 않아야 한다(공유 프로세스 키 누출 방지).
"""
import os
import pathlib
import subprocess
import sys

import pytest

from loan_agent import core, llm, settings


def test_get_llm_without_key_raises(monkeypatch, tmp_path):
    # 설정은 환경변수가 없으면 .env를 읽는다. 개발 머신의 .env에 키가 있으면 「키 없음」을
    # 만들 수 없으므로 존재하지 않는 파일을 가리키게 한다.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "DOTENV_PATH", tmp_path / "absent.env")
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


def test_loading_crewai_through_the_service_does_not_copy_a_dotenv_into_the_environment(tmp_path):
    """서비스가 crewai를 불러와도 작업 폴더의 `.env`가 프로세스 환경변수로 올라가지 않아야 한다.

    crewai는 import될 때 모듈 수준에서 `load_dotenv()`를 부르고, python-dotenv는 `python -c`·REPL·
    디버거로 띄운 프로세스에서 현재 작업 폴더의 `.env`를 찾는다. 저장소 `.env`에 서버 키가 있으면 그
    키가 전역 환경에 남는다. 위 테스트는 이 조건에서만 실패해 드러났으므로, 조건을 직접 만든다 —
    임시 폴더에 `.env`를 두고 그 폴더에서 `python -c`로 하위 프로세스를 띄운다. 저장소 `.env`에
    기대지 않으므로 `.env`가 없는 CI에서도 같은 조건이 된다.

    대조 실행은 서비스 코드를 거치지 않고 crewai만 불러와 이 조건이 실제로 `.env`를 올리는지 확인한다.
    crewai가 더는 그러지 않으면 막을 대상이 없으므로 건너뛴다.
    """
    (tmp_path / ".env").write_text("LOAN_AGENT_DOTENV_PROBE=loaded\n", encoding="utf-8")
    root = pathlib.Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items()
           if k not in {"LOAN_AGENT_DOTENV_PROBE", "PYTHON_DOTENV_DISABLED"}}
    env["PYTHONPATH"] = str(root)
    probe = "import os\nprint('PROBE=' + str('LOAN_AGENT_DOTENV_PROBE' in os.environ))\n"

    def run(code: str) -> str:
        done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=180)
        assert done.returncode == 0, done.stderr[-2000:]
        [marker] = [line for line in done.stdout.splitlines() if line.startswith("PROBE=")]
        return marker

    if run("from crewai import LLM\n" + probe) != "PROBE=True":
        pytest.skip("crewai가 import 시 .env를 더는 올리지 않아 이 테스트가 막을 대상이 없다")

    via_service = run(
        "from loan_agent import llm\n"
        "try:\n"
        "    llm.get_llm(api_key='sk-visitor-fake')\n"
        "except Exception:\n"
        "    pass\n" + probe
    )
    assert via_service == "PROBE=False"


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
