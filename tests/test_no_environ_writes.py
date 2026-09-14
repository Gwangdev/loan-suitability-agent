"""서비스 코드가 프로세스 환경변수에 값을 쓰지 않게 고정한다.

키는 인자로만 흐르고 전역 환경에 남기지 않는다는 것이 이 서비스의 규칙이다(금지 행위 ⑦).
환경은 같은 프로세스의 모든 요청과 하위 라이브러리가 함께 읽으므로, 한 번 쓰면 누가 그 키를
쓰는지 코드로 추적할 수 없게 된다. 그런데 화면 코드 첫머리에 Streamlit secrets의 서버 키를
환경변수로 옮기는 블록이 남아 있었다. 폐기한 Streamlit Cloud 배포를 위한 것이라 운영 컨테이너
에서는 돌지 않았지만, 로컬에 secrets 파일을 두면 그대로 실행되는 경로였다.

환경을 실제로 바꾸는지 실행으로 보려면 secrets 파일과 Streamlit 런타임이 있어야 하므로, 쓰기
형태를 구문 트리로 찾는다. 대입·삭제·setdefault·update·putenv 중 무엇이 다시 들어와도 깨진다.

허용하는 쓰기는 하나다. `loan_agent/llm.py`의 `os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")`는
crewai가 import될 때 부르는 `load_dotenv()`가 작업 폴더의 `.env`(서버 키 포함)를 환경에 올리지 못하게
python-dotenv의 스위치를 켠다. 쓰는 값은 키가 아니고, 이미 명시된 값을 덮지 않는다. 이 한 형태만
문자 그대로 비교해 통과시키므로 이름·값·쓰기 방식이 조금만 달라도 여전히 잡힌다.

잡는 것은 서비스 코드의 직접 쓰기뿐이다. 라이브러리가 대신 환경에 쓰는 호출(load_dotenv 같은)은
구문만으로는 쓰기인지 알 수 없어 여기서 다루지 않고, tests/test_settings.py가 그 호출 자체를 막는다.
"""
import ast
import os

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loan_agent")
_WRITING_METHODS = {"setdefault", "update", "pop", "popitem", "clear"}
_ALLOWED_SETDEFAULT = ("PYTHON_DOTENV_DISABLED", "1")


def _is_os_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _is_allowed(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefault" and _is_os_environ(node.func.value)
            and not node.keywords and len(node.args) == 2
            and all(isinstance(arg, ast.Constant) for arg in node.args)
            and tuple(arg.value for arg in node.args) == _ALLOWED_SETDEFAULT)


def _write_lines(tree):
    lines = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.Delete)):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        hit = any(isinstance(t, ast.Subscript) and _is_os_environ(t.value) for t in targets)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            hit = hit or (node.func.attr in _WRITING_METHODS and _is_os_environ(node.func.value))
            hit = hit or (node.func.attr == "putenv" and isinstance(node.func.value, ast.Name)
                          and node.func.value.id == "os")
        if hit and not _is_allowed(node):
            lines.append(node.lineno)
    return lines


def _environ_writes():
    offenders = []
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            offenders += [f"{os.path.relpath(path, PACKAGE)}:{line}" for line in _write_lines(tree)]
    return offenders


def test_ui_no_longer_copies_the_server_key_into_os_environ_and_no_service_code_writes_it_directly():
    assert _environ_writes() == []


def test_the_single_allowed_write_is_matched_literally_and_nothing_near_it_passes():
    """허용은 스위치를 켜는 한 형태뿐이다. 이름·값·쓰기 방식을 바꾼 호출은 모두 쓰기로 잡혀야 한다."""
    allowed = 'import os\nos.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")\n'
    near_misses = [
        'import os\nos.environ.setdefault("OPENAI_API_KEY", "sk-server")\n',
        'import os\nos.environ.setdefault("PYTHON_DOTENV_DISABLED", "0")\n',
        'import os\nos.environ["PYTHON_DOTENV_DISABLED"] = "1"\n',
        'import os\nos.environ.update({"PYTHON_DOTENV_DISABLED": "1"})\n',
        'import os\nname = "PYTHON_DOTENV_DISABLED"\nos.environ.setdefault(name, "1")\n',
        'import os\nos.environ.setdefault(key="PYTHON_DOTENV_DISABLED", value="1")\n',
    ]

    assert _write_lines(ast.parse(allowed)) == []
    assert [bool(_write_lines(ast.parse(source))) for source in near_misses] == [True] * len(near_misses)
