"""生成脱敏测试夹具（不含真实餐厅数据）。运行一次：uv run python tests/fixtures/make_fixtures.py"""

from pathlib import Path

HERE = Path(__file__).parent
# 最小合法 PDF（单页，含文本 "Soup 5"）
MINI_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 12 Tf 72 770 Td (Soup 5) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
trailer << /Size 6 /Root 1 0 R >>
startxref
0
%%EOF
"""
(HERE / "mini.pdf").write_bytes(MINI_PDF)
(HERE / "mini.html").write_text(
    "<!doctype html><html><body><h1>Menu</h1><p>Soup £5.00</p><p>Bread £2.5</p></body></html>"
)
(HERE / "mini.png").write_bytes(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000d4944415478da63f8cfc0f01f0005000101"
        "0b3d5a3a0000000049454e44ae426082"
    )
)


def pdf_with_lines(lines):
    """lines: [(x, y, text)] 生成单页多文本对象 PDF（Helvetica 10pt）。"""
    content = "BT /F1 10 Tf " + " ".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >> stream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj {o} endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


(HERE / "two_col.pdf").write_bytes(
    pdf_with_lines(
        [
            (72, 770, "STARTERS"),
            (72, 750, "Soup of the day 5"),
            (72, 730, "Bread and butter 3.50"),
            (330, 770, "MAINS"),
            (330, 750, "Steak and chips 22"),
            (330, 730, "Fish pie 18"),
        ]
    )
)
(HERE / "no_text.pdf").write_bytes(pdf_with_lines([]))
print("fixtures written")
