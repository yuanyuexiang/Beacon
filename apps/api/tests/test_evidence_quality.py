from app.integrations import fetcher, page_cache
from app.modules.menus.quality import assess


def test_cache_reuses_success_expires_and_never_caches_failure(monkeypatch, tmp_path):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(fetcher, "check_url", lambda *a, **k: None)
    calls = []
    clock = [1000]
    monkeypatch.setattr(page_cache.time, "time", lambda: clock[0])

    def fetch(url, **kwargs):
        calls.append(url)
        return fetcher.FetchResult(url, url, 200, "text/html", b"<html>sample</html>", "html")

    monkeypatch.setattr(fetcher, "fetch", fetch)
    url = "https://sample.example/"
    kwargs = dict(max_bytes=1000, timeout=1, user_agent="test")
    assert page_cache.fetch(url, **kwargs).body == page_cache.fetch(url, **kwargs).body
    assert len(calls) == 1
    clock[0] += 3601
    page_cache.fetch(url, **kwargs)
    assert len(calls) == 2
    monkeypatch.setattr(fetcher, "fetch", lambda url, **k: fetcher.FetchResult(url, url, 403, None, b"", "html"))
    clock[0] += 3601
    assert page_cache.fetch(url, **kwargs).status == 403
    assert page_cache.fetch(url, **kwargs).status == 403


def test_quality_flags_missing_and_duplicates_without_claiming_menu_defects():
    assert assess([])["status"] == "review"
    result = assess([{"name": "Soup", "evidence": {"page": 1}}, {"name": "Soup"}])
    assert result["item_numbers"] == [1, 2]
    assert assess([{"name": "Soup", "evidence": {"page": 1}}])["status"] == "no_obvious_anomaly"


def test_text_menu_empty_rules_escalates_only_to_real_provider(client, db, monkeypatch, tmp_path):
    import hashlib
    import uuid

    from app.core.config import get_settings
    from app.integrations.llm import ProviderResult
    from app.modules.menus import service
    from app.modules.menus.models import AssetKind, FetchStatus, MenuAsset
    from tests.test_assets import setup_lead

    identity = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    data = b"<html><body><p>Soup</p><p>five pounds</p></body></html>"
    (tmp_path / "menu.html").write_bytes(data)
    asset = MenuAsset(
        lead_id=uuid.UUID(identity),
        kind=AssetKind.html,
        fetch_status=FetchStatus.fetched,
        storage_path="menu.html",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(asset)
    db.commit()
    first, _ = service.run_analysis(db, asset, engine="auto")
    assert first.engine == "rules"
    assert first.measurements is not None
    assert first.measurements["extraction_quality"]["status"] == "review"
    calls = []

    class Provider:
        name = "deepseek"
        model = "mock"

        def analyze_text(self, text, context):
            calls.append(text)
            return ProviderResult(
                engine="deepseek",
                engine_version="mock",
                items=[{"name": "Soup", "price_text": "five pounds", "evidence": {"line": 1}}],
                issues=[],
                notes="mock",
                usage={},
            )

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(service, "get_provider", lambda: Provider())
    monkeypatch.setattr(service.ai_runtime, "available", lambda *args: True)
    second, _ = service.run_analysis(db, asset, engine="auto")
    assert calls and second.engine == "deepseek" and second.status.value == "needs_review"
    assert first.review_state is None and second.review_state is None
