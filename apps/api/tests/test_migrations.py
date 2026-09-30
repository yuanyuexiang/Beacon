"""空库可初始化，且升级/降级往返后 schema 一致（无遗漏的 autogenerate 差异）。"""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.models_all import Base
from tests.conftest import alembic_config


def test_upgrade_downgrade_roundtrip(migrated_db):
    cfg = alembic_config()
    eng = create_engine(migrated_db)
    names = set(inspect(eng).get_table_names())
    expected = {t.name for t in Base.metadata.sorted_tables}
    assert expected <= names, expected - names
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"模型与迁移不一致：{diff}"
    command.downgrade(cfg, "base")
    assert set(inspect(create_engine(migrated_db)).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
