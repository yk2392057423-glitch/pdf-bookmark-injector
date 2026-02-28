"""检查第1页和第33页的精确字号（未四舍五入）"""
import fitz

doc = fitz.open("my_book.pdf")

for pg in [0, 1, 31, 32]:
    if pg >= len(doc):
        continue
    page = doc[pg]
    print(f"\n===== 第{pg+1}页 =====")
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            sizes = [s.get("size", 0) for s in spans]
            print(f"  sz={max(sizes):.4f}  {text[:70]}")

doc.close()
