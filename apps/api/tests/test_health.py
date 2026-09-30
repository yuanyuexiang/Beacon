def test_health_without_db(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_db(client):
    r = client.get("/api/health/db")
    assert r.status_code == 200 and r.json()["database"] == "reachable"
