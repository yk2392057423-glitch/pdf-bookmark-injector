import fitz
from collections import Counter
import sys

doc = fitz.open("my_book2.pdf")
print(f"页数: {len(doc)}")

# 检查前5页是否是图片（扫描件）
for i in range(min(5, len(doc))):
    page = doc[i]
    text = page.get_text().strip()
    images = page.get_images()
    print(f"第{i+1}页: 文字{len(text)}字符, 图片{len(images)}个")

# 统计字号分布
sizes = Counter()
for page in doc:
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if len(t) > 3:
                    sizes[round(span.get("size", 0), 1)] += 1

print(f"\nTop10 字号分布: {sizes.most_common(10)}")

# 输出前3页每行的字号和文字
for pg in range(min(3, len(doc))):
    page = doc[pg]
    print(f"\n=== 第{pg+1}页 ===")
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
            ms = max(s.get("size", 0) for s in spans)
            bold = any((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans)
            print(f"  sz={ms:.2f} bold={bold}  {text[:70]}")

doc.close()
