"""诊断脚本：输出 PDF 前5页的文字、字号、是否粗体"""
import fitz
from collections import Counter

doc = fitz.open("my_book.pdf")

# 统计全文最常见字号（= 正文字号）
all_sizes = []
for page in doc:
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if len(t) > 3:
                    all_sizes.append(round(span.get("size", 0), 1))

counter = Counter(all_sizes)
body_size = counter.most_common(1)[0][0]
print(f"[全文最常见字号（正文字号）= {body_size}pt]\n")
print("Top 5 字号分布:", counter.most_common(5))
print()

# 输出前5页每行文字信息
for page_num in range(min(5, len(doc))):
    page = doc[page_num]
    print(f"{'='*60}")
    print(f"第 {page_num+1} 页")
    print(f"{'='*60}")
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
            max_size = max(s.get("size", 0) for s in spans)
            bold = any((s.get("flags", 0) & 16) or "bold" in s.get("font","").lower() for s in spans)
            font = spans[0].get("font", "")
            marker = "★" if max_size > body_size + 1 else ("B" if bold else " ")
            print(f"  [{marker}] sz={max_size:.1f}  {text[:80]}")

doc.close()
