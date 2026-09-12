"""설정값을 읽는 유일한 자리.

설정은 실제 환경변수에서 먼저 찾고, 없으면 저장소 루트의 .env에서 찾는다. .env는 값을 돌려주기만
하고 os.environ에 쓰지 않는다. 예전에는 core가 import되는 순간 load_dotenv(override=True)로 .env
전체를 환경에 덮어써서, .env에 둔 서버 OpenAI 키가 core를 불러오는 모든 프로세스 — 화면·API·워커
— 의 전역 환경에 들어갔다. 키는 인자로만 흐른다는 규칙을 import 한 줄이 무너뜨리던 구조라, 필요한
자리에서 값을 받아 가는 함수로 바꿨다.

실제 환경변수가 파일보다 이긴다. compose가 env_file로 넣은 값이나 셸에서 명시한 값이 파일보다
의도가 분명하기 때문이다. 예전의 override=True는 반대로 파일이 이겼다.
"""
import os
from pathlib import Path

from dotenv import dotenv_values

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def read(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    # 빈 문자열도 명시된 값이다. 키를 끄려고 `OPENAI_API_KEY=`로 둔 환경변수가 .env에 지면
    # 끈 줄 알았던 키로 실행되므로, 존재 여부로 판정한다.
    if value is not None:
        return value
    return dotenv_values(DOTENV_PATH).get(name) or default
