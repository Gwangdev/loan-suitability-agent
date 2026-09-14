"""화면에서 처리되지 않은 예외의 상세가 브라우저로 내려가지 않는다는 것을 고정한다.

Streamlit은 설정이 없으면 `client.showErrorDetails`를 `full`로 둔다. 그러면 화면 코드에서
잡지 않은 예외가 예외 메시지와 서버 파일 경로·코드 줄이 담긴 traceback째 화면에 뜨고,
같은 내용이 WebSocket으로 내려가 방문자의 개발자도구에서도 보였다. 운영 이미지는 저장소의
`.streamlit/` 설정을 그대로 복사하고 다른 경로로 덮지 않으므로, 설정 파일의 값이 곧 운영 값이다.
`none`이면 브라우저에는 일반 오류 문구만 보이고 상세는 서버 콘솔에만 남는다.
"""
import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def test_uncaught_ui_exceptions_show_only_a_generic_message_in_the_browser():
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))

    assert config.get("client", {}).get("showErrorDetails") == "none"
