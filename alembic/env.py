"""Alembic 실행 환경.

접속 URL은 두 곳에서 온다 — `alembic.ini`의 `sqlalchemy.url`, 또는 환경변수
`DATABASE_URL`. 배포·CI는 환경변수로 주고, 로컬에서 손으로 돌릴 때만 ini 값을 쓴다.
환경변수가 있으면 그쪽이 이긴다.

`target_metadata`는 모델을 가리키지만 이 프로젝트는 마이그레이션을 손으로 쓴다.
autogenerate로 부분 인덱스·순환 FID·CHECK 이름을 맡기면 재현되지 않는 diff가 나오기
때문이다. 메타데이터는 `--autogenerate`로 초안을 뽑을 때만 참고용으로 붙여 둔다.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_env_url = os.getenv("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

from loan_agent.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
