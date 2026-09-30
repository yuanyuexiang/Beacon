"""HTML v2：分标签排版的价格—菜名关联；多价条目；候选文件发现；噪声（购物车小计）不成条目。"""

from app.modules.menus import analysis as rules
from app.modules.menus import html_extract

CARDS = """<html><body><div class="cart"><span>Subtotal:</span><strong>£0.00</strong></div>
<div class="menu">
 <div class="card"><h3>Margherita</h3><div class="desc">Tomato, mozzarella</div>
   <div class="prices"><div><img alt="12 inch"><div>£10.5</div></div>
   <div><img alt="18 inch"><div>£19</div></div></div></div>
 <div class="card"><h3>Salmon Nigiri</h3><div class="desc">2 pcs</div><div class="price">£4.70</div></div>
 <p>Edamame with sea salt &nbsp; £3.50</p>
 <p>£17.50 Thin Sliced Beef</p>
</div>
<a href="/menus/main.pdf">Download</a>
<img src="https://images.squarespace-cdn.com/content/v1/x/menu1.png?format=1500w" alt="">
</body></html>"""


def test_dom_linking_and_multi_price():
    ex = html_extract.extract(CARDS, "https://example.com/menu/")
    got = [(i["name"], i["price_text"]) for i in ex["items"]]
    assert ("Margherita", "£10.5") in got and ("Margherita", "£19") in got
    assert ("Salmon Nigiri", "£4.70") in got
    assert ("Edamame with sea salt", "£3.50") in got
    assert ("Thin Sliced Beef", "£17.50") in got
    assert not any(i["name"].lower().startswith("subtotal") for i in ex["items"])
    assert ex["pdf_links"] == ["https://example.com/menus/main.pdf"]
    assert ex["image_candidates"][0]["src"].endswith("menu1.png")
    linked = [i for i in ex["items"] if i["name"] == "Salmon Nigiri"][0]
    assert linked["evidence"]["linked"] is True and linked["evidence"]["name_line"] < linked["evidence"]["line"]


def test_menu_not_in_html_issue_with_candidates():
    r = rules.analyze_html(b'<html><body><p>Welcome</p><a href="/x/menu.pdf">Menu</a></body></html>', "https://a.test/")
    assert r.status == "needs_review" and r.issues[0]["issue_code"] == "menu_not_in_html"
    assert r.issues[0]["evidence"]["pdf_links"] == ["https://a.test/x/menu.pdf"]


def test_mixed_decimals_detected_from_cards():
    r = rules.analyze_html(CARDS.encode(), "https://example.com/")
    assert any(i["issue_code"] == "price_format_mixed_decimals" for i in r.issues)
