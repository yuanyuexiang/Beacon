from collections import Counter

from app.integrations import fetcher, website_menus
from app.modules.menus import routes
from tests.test_imports import CSV_A, create_batch, login, upload


def result(url, html, final_url=None):
    return fetcher.FetchResult(url, final_url or url, 200, "text/html", html.encode(), "html")


def test_menu_discovery_follows_redirects_and_excludes_unrelated_images():
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            return result(
                url,
                '<a href="/menus">Menus</a><a href="/privacy.pdf">Privacy</a><img src="cocktail.jpg" alt="Drink">',
                "https://www.restaurant.example/",
            )
        return result(
            url,
            '<a href="https://cdn.example/drinks-menu.pdf?download=1">Menu</a><a href="http://127.0.0.1/menu.pdf">Menu</a>'
            '<img src="/menu.png">',
        )

    r = website_menus.discover("http://old.example", fetch)
    assert calls == ["http://old.example", "https://www.restaurant.example/menus"]
    assert [c["kind"] for c in r["candidates"]] == ["pdf", "image", "html"]
    assert r["candidates"][0]["source_url"] == "https://www.restaurant.example/menus"
    assert "127.0.0.1" not in str(r["candidates"])


def test_discovery_is_bounded_and_reports_failures():
    seen: Counter[str] = Counter()

    def fetch(url):
        seen[url] += 1
        if "/menu0" in url:
            raise TimeoutError("network unavailable")
        return result(url, "".join(f'<a href="/menu{i}">menu</a>' for i in range(20)))

    r = website_menus.discover("https://restaurant.example", fetch)
    assert len(r["pages"]) == 5 and max(seen.values()) == 1
    assert len([p for p in r["pages"] if not p["ok"]]) == 1


def test_menu_endpoint_requires_website_and_rejects_concurrent_change(client, db, monkeypatch):
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead_id = client.get("/api/leads").json()[0]["id"]
    path = f"/api/leads/{lead_id}"
    assert client.post(path + "/menu-candidates").status_code == 400
    client.patch(path, json={"website": "https://restaurant.example"})

    def fetch(url):
        client.patch(path, json={"website": "https://changed.example"})
        return result(url, '<a href="/menu.pdf">Menu</a>')

    monkeypatch.setattr(routes, "site_fetch", lambda: fetch)
    assert client.post(path + "/menu-candidates").status_code == 409
