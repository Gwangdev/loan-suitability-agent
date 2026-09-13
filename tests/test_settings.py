"""설정값을 .env에서 읽되 프로세스 환경변수에 쓰지 않는다는 것을 고정한다.

core 모듈이 import되는 순간 load_dotenv(override=True)로 .env 전체를 os.environ에 덮어쓰고
있었다. .env에 서버 OpenAI 키가 있으면 core를 불러오는 모든 프로세스 — 화면·API·워커 — 의
전역 환경에 키가 들어가, 키는 인자로만 흐른다는 규칙이 import 한 줄에서 무너졌다. 운영 이미지는
.env를 빼고 빌드하므로 실행되지 않았지만, 로컬에서는 그대로 실행되는 경로였다.

서버 키로 안내문을 만드는 로컬 워커 경로는 .env의 키가 필요하므로 읽기 자체를 없앨 수는 없다.
그래서 .env는 값을 돌려주기만 하고 환경에 쓰지 않는 설정 모듈로 읽는다. 실제 환경변수가 있으면
그쪽이 이긴다 — compose가 env_file로 넣은 값이나 셸에서 명시한 값이 파일보다 의도가 분명하다.
"""
import ast
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "loan_agent"


def _calls_named(name):
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called == name:
                found.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    return found


def test_no_service_module_loads_dotenv_into_the_process_environment():
    assert _calls_named("load_dotenv") == []


def test_settings_read_dotenv_values_without_writing_them_to_os_environ(tmp_path, monkeypatch):
    from loan_agent import settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("SETTINGS_PROBE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(settings, "DOTENV_PATH", dotenv)
    monkeypatch.delenv("SETTINGS_PROBE", raising=False)

    assert settings.read("SETTINGS_PROBE") == "from-dotenv"
    assert "SETTINGS_PROBE" not in os.environ


def test_an_explicit_process_environment_value_wins_over_dotenv(tmp_path, monkeypatch):
    from loan_agent import settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("SETTINGS_PROBE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(settings, "DOTENV_PATH", dotenv)
    monkeypatch.setenv("SETTINGS_PROBE", "from-environment")

    assert settings.read("SETTINGS_PROBE") == "from-environment"


def test_an_explicitly_empty_environment_value_wins_over_dotenv(tmp_path, monkeypatch):
    """키를 끄려고 빈 값으로 명시한 환경변수가 .env에 지면, 끈 줄 알았던 키로 실행된다."""
    from loan_agent import settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("SETTINGS_PROBE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(settings, "DOTENV_PATH", dotenv)
    monkeypatch.setenv("SETTINGS_PROBE", "")

    assert settings.read("SETTINGS_PROBE") == ""


def test_an_empty_environment_value_falls_back_to_the_default_not_to_dotenv(tmp_path, monkeypatch):
    """기본값이 있는 설정을 빈 값으로 두면 기본값을 쓴다. 빈 모델명이 LLM 호출까지 가면 안 된다.

    빈 환경변수를 명시값으로 보게 고친 뒤, 기본값이 있는 이름에서도 빈 문자열이 그대로 나가
    OPENAI_MODEL_NAME= 한 줄이 모델명 없는 호출이 됐다. .env 경로는 같은 경우에 기본값을 쓰므로
    두 경로의 판정이 갈라져 있었다. 빈 값이 .env로 넘어가지 않는다는 점은 그대로 지킨다.
    """
    from loan_agent import settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("SETTINGS_PROBE=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(settings, "DOTENV_PATH", dotenv)
    monkeypatch.setenv("SETTINGS_PROBE", "")

    assert settings.read("SETTINGS_PROBE", "fallback") == "fallback"


def test_a_missing_dotenv_file_falls_back_to_the_default(tmp_path, monkeypatch):
    from loan_agent import settings

    monkeypatch.setattr(settings, "DOTENV_PATH", tmp_path / "absent.env")
    monkeypatch.delenv("SETTINGS_PROBE", raising=False)

    assert settings.read("SETTINGS_PROBE", "fallback") == "fallback"
