"""서비스 코드가 프로세스 환경변수에 값을 쓰지 않게 고정한다.

키는 인자로만 흐르고 전역 환경에 남기지 않는다는 것이 이 서비스의 규칙이다(금지 행위 ⑦).
환경은 같은 프로세스의 모든 요청과 하위 라이브러리가 함께 읽으므로, 한 번 쓰면 누가 그 키를
쓰는지 코드로 추적할 수 없게 된다. 그런데 화면 코드 첫머리에 Streamlit secrets의 서버 키를
환경변수로 옮기는 블록이 남아 있었다. 폐기한 Streamlit Cloud 배포를 위한 것이라 운영 컨테이너
에서는 돌지 않았지만, 로컬에 secrets 파일을 두면 그대로 실행되는 경로였다.

환경을 실제로 바꾸는지 실행으로 보려면 secrets 파일과 Streamlit 런타임이 있어야 하므로, 쓰기
형태를 구문 트리로 찾는다. 대입·삭제·setdefault·update·putenv 중 무엇이 다시 들어와도 깨진다.

잡는 것은 서비스 코드의 직접 쓰기뿐이다. 라이브러리가 대신 환경에 쓰는 호출(load_dotenv 같은)은
구문만으로는 쓰기인지 알 수 없어 여기서 다루지 않고, tests/test_settings.py가 그 호출 자체를 막는다.
"""
import ast
import os

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loan_agent")
_WRITING_METHODS = {"setdefault", "update", "pop", "popitem", "clear"}


def _is_os_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _environ_writes():
    offenders = []
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
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
                if hit:
                    offenders.append(f"{os.path.relpath(path, PACKAGE)}:{node.lineno}")
    return offenders


def test_ui_no_longer_copies_the_server_key_into_os_environ_and_no_service_code_writes_it_directly():
    assert _environ_writes() == []
