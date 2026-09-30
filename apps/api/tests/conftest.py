"""测试夹具：使用独立测试库（BEACON_TEST_DATABASE_URL），每个会话先 alembic upgrade head，结束后 downgrade base。
普通测试不访问网络、不调用真实模型。"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

API_DIR = Path(__file__).resolve().parents[1]
TEST_URL = os.environ.get("BEACON_TEST_DATABASE_URL", "postgresql+psycopg://beacon:beacon@localhost:5433/beacon_test")


def pytest_configure() -> None:
    # 测试进程内固定配置：指向测试库与临时数据目录，避免读到开发 .env
    os.environ["BEACON_DATABASE_URL"] = TEST_URL
    os.environ["BEACON_TEST_DATABASE_URL"] = TEST_URL
    os.environ.setdefault("BEACON_DATA_DIR", tempfile.mkdtemp(prefix="beacon-test-data-"))
    os.environ.setdefault("BEACON_SECRET_KEY", "test-secret-key-0123456789abcdef0123456789abcdef")
    os.environ.pop("BEACON_BOOTSTRAP_OPERATOR", None)
    os.environ.pop("BEACON_BOOTSTRAP_PASSWORD", None)
    # 测试不读取 apps/api/.env（其中可能有真实密钥）
    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    for k in (
        "BEACON_LLM_PROVIDER",
        "BEACON_DEEPSEEK_API_KEY",
        "BEACON_ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        os.environ.pop(k, None)


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={TEST_URL}"]})()  # -x url=
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    try:
        eng = create_engine(TEST_URL)
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # pragma: no cover
        pytest.exit(
            f"测试库不可达（{TEST_URL}）。先运行 docker compose -f infra/docker-compose.yml up -d。{e}", returncode=3
        )
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_URL
    command.downgrade(cfg, "base")


@pytest.fixture
def db(migrated_db: str) -> Iterator[Session]:
    eng = create_engine(migrated_db)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        # 每个测试后清空业务表，保证独立
        with eng.begin() as c:
            for t in [
                "batch_job",
                "batch_run",
                "audit_log",
                "cost_entry",
                "suppression",
                "event",
                "manual_task",
                "channel_eligibility",
                "approval",
                "content_piece",
                "analysis_correction",
                "menu_analysis",
                "menu_asset",
                "import_run",
                "batch_lead",
                "lead",
                "batch",
                "operator",
            ]:
                c.execute(text(f'truncate table "{t}" cascade'))
        eng.dispose()


@pytest.fixture
def client(migrated_db: str) -> Iterator[TestClient]:
    from app.core import config as cfg_mod
    from app.core import db as db_mod
    from app.main import app

    cfg_mod.get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    with TestClient(app) as c:
        yield c
