"""readiness 판정 — DB에 붙는가, 그리고 스키마가 코드가 기대하는 버전인가.

두 가지를 함께 봐야 하는 이유가 있다. DB가 살아 있어도 마이그레이션이 뒤처져 있으면
코드가 없는 컬럼을 읽거나 이름이 바뀐 제약을 건드리다 런타임에 깨진다. 배포 직후
이 상태가 흔하므로, 「연결됨」만으로 ready라고 답하면 트래픽을 받자마자 500이 쏟아진다.

LLM 제공자는 여기서 확인하지 않는다. 결정적 판정은 제공자와 무관하게 동작하므로
제공자 장애를 readiness에 묶으면 멀쩡한 판정 경로가 함께 차단된다.
"""
import os

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _expected_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check(engine: Engine) -> dict:
    """`{"database": ..., "migration": ...}`을 돌려준다. 값은 각각 "ok" 또는 실패 사유."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            applied = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    except Exception:
        # 어느 예외든 결론은 같다 — 지금은 트래픽을 받을 수 없다. 상세는 로그의 몫이고
        # readiness 응답 본문에 담지 않는다(접속 정보가 섞여 나갈 수 있다).
        return {"database": "error", "migration": "unknown"}

    if applied == _expected_head():
        return {"database": "ok", "migration": "ok"}
    return {"database": "ok", "migration": "behind"}


__all__ = ["check"]
