"""Review-only regression probes; synthetic fixtures and isolated audit database."""
import uuid
from datetime import UTC, datetime, timedelta
import os
from urllib.parse import urlparse

# Existing test fixtures drop/recreate tables; only permit a dedicated audit database.
assert urlparse(os.environ.get("BEACON_TEST_DATABASE_URL", "")).path.startswith("/beacon_audit_"), "Set a dedicated beacon_audit_* test database before running review probes."
from tests.test_sales import _ready, _elig
from tests.test_imports import create_batch, upload
from tests.test_assets import setup_lead
from tests.test_content import IDENT, OPTOUT


def test_untrusted_html_is_isolated(client, db):
    lead = setup_lead(client, db)
    html = b'<!doctype html><html><script>window.__BEACON_AUDIT__=1</script></html>'
    r = client.post(f'/api/leads/{lead}/assets/upload', files={'file': ('menu.html', html, 'text/html')})
    assert r.status_code == 201
    page = client.get('/api/files/' + r.json()['storage_path'])
    assert page.status_code == 200
    assert 'sandbox' in page.headers.get('content-security-policy', '') or 'attachment' in page.headers.get('content-disposition', ''), dict(page.headers)


def test_reply_prevents_new_followup_task(client, db):
    lead, a, c = _ready(client, db)
    e = _elig(client, lead).json()
    assert client.post(f'/api/leads/{lead}/events', json={'event_key': 'audit-reply', 'kind': 'reply', 'channel': 'email'}).status_code == 200
    r = client.post(f'/api/leads/{lead}/tasks', json={'eligibility_id': e['id'], 'content_id': c['id']})
    assert r.status_code == 409, f'new task allowed after unhandled reply: {r.status_code}'


def test_content_cannot_use_another_leads_analysis(client, db):
    lead, a, c = _ready(client, db)
    upload(client, 'b1', 'fhrsid,name\n2,Another Restaurant\n')
    other = next(x['id'] for x in client.get('/api/leads').json() if x['id'] != lead)
    r = client.post(f'/api/leads/{other}/content', json={'kind': 'message_short', 'analysis_id': a['id'], 'sender_identity': IDENT, 'opt_out_text': OPTOUT})
    assert r.status_code in (400, 409), f'foreign restaurant analysis accepted: {r.status_code}'


def test_refreshing_source_invalidates_approval(client, db, monkeypatch):
    from app.modules.menus.models import MenuAsset
    from app.integrations import fetcher
    from tests.test_assets import FIX
    lead, a, c = _ready(client, db)
    asset = db.get(MenuAsset, uuid.UUID(a['asset_id']))
    old_hash = asset.sha256
    asset.source_url = 'https://example.com/menu.pdf'
    db.commit()
    monkeypatch.setattr(fetcher, 'fetch', lambda *args, **kwargs: fetcher.FetchResult('https://example.com/menu.pdf', 'https://example.com/menu.pdf', 200, 'application/pdf', (FIX/'mini.pdf').read_bytes(), 'pdf'))
    refreshed = client.post(f'/api/assets/{asset.id}/retry')
    assert refreshed.status_code == 200 and refreshed.json()['sha256'] != old_hash
    current = client.get(f"/api/content/{c['id']}").json()
    assert current['approval_valid'] is False, 'approval remains valid after source file changed'


def test_reused_event_key_cannot_swallow_unsubscribe(client, db):
    lead, a, c = _ready(client, db)
    assert client.post(f'/api/leads/{lead}/events', json={'event_key':'audit-event', 'kind':'note'}).status_code == 200
    r = client.post(f'/api/leads/{lead}/events', json={'event_key':'audit-event', 'kind':'unsubscribe'})
    assert r.status_code == 409, f'changed payload silently treated as duplicate: {r.status_code}, {r.json()["kind"]}'


def test_expired_eligibility_not_counted_contactable(client, db):
    lead, a, c = _ready(client, db)
    client.patch(f'/api/leads/{lead}', json={'screening_class':'candidate'})
    _elig(client, lead, review_due_at=(datetime.now(UTC)-timedelta(days=1)).isoformat())
    counts=client.get('/api/batches/b1/summary').json()['counts']
    assert counts['E'] == 0, counts


def test_new_batch_does_not_inherit_previous_outreach(client, db):
    lead, a, c = _ready(client, db)
    e = _elig(client, lead).json()
    t = client.post(f'/api/leads/{lead}/tasks', json={'eligibility_id':e['id'],'content_id':c['id']}).json()
    client.post(f"/api/tasks/{t['id']}/open")
    assert client.post(f"/api/tasks/{t['id']}/sent", json={'sent_at':datetime.now(UTC).isoformat()}).status_code == 200
    create_batch(client, 'audit-new-batch')
    upload(client, 'audit-new-batch', 'fhrsid,name\n1,Test Restaurant\n')
    s=client.get('/api/batches/audit-new-batch/summary').json()
    assert s['counts']['S'] == 0, s['counts']


def test_non_menu_html_not_counted_as_menu_obtained(client, db):
    lead = setup_lead(client, db)
    html=b'<!doctype html><html><body><h1>Welcome to our restaurant</h1><p>No online menu</p></body></html>'
    r=client.post(f'/api/leads/{lead}/assets/upload',files={'file':('home.html',html,'text/html')})
    assert r.status_code == 201
    assert client.post(f"/api/assets/{r.json()['id']}/analyses").status_code == 200
    counts=client.get('/api/batches/b1/summary').json()['counts']
    assert counts['M'] == 0, counts
