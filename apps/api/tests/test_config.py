"""必要配置缺失时明确报错，而不是静默默认。"""

import pytest


def test_missing_config_raises(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.delenv("BEACON_DATABASE_URL", raising=False)
    monkeypatch.setattr(cfg.Settings, "model_config", {**cfg.Settings.model_config, "env_file": None})
    with pytest.raises(cfg.ConfigError) as e:
        cfg.get_settings()
    assert "database_url" in str(e.value)
    cfg.get_settings.cache_clear()


def test_relative_data_dir_rejected(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("BEACON_DATA_DIR", "relative/path")
    with pytest.raises(cfg.ConfigError) as e:
        cfg.get_settings()
    assert "绝对路径" in str(e.value)
    cfg.get_settings.cache_clear()
