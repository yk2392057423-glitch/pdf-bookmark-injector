"""
Step Clause-A: 提取条文说明目录页 → clause_toc.pdf
从已有书签的 PDF 中定位"条文说明"起始页，OCR 扫描后续页面识别目录页。
"""
import os, re, io, sys
import fitz
import pytesseract
from PIL import Image

os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

BOOKMARKED_PDF = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2_final.pdf"
ORIG_PDF       = sys.argv[2] if len(sys.argv) >= 3 else r"D:\claudecode_test\01pdf\my_book2.pdf"
OUTPUT_PDF     = sys.argv[3] if len(sys.argv) >= 4 else r"D:\claudecode_test\01pdf\clause_toc.pdf"

# ── 从书签找条文说明的 PDF 页（0-indexed） ──────────────────────
def find_clause_start(pdf_path):
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    doc.close()
    for item in toc:
        if '条文说明' in item[1]:
            return item[2] - 1  # 1-indexed → 0-indexed
    return None

clause_0idx = find_clause_start(BOOKMARKED_PDF)
if clause_0idx is None:
    clause_0idx = 211
    print(f"书签中未找到条文说明，使用默认: PDF第{clause_0idx+1}页")
else:
    print(f"条文说明起始: PDF第{clause_0idx+1}页（0-indexed {clause_0idx}）")

doc = fitz.open(ORIG_PDF)
total = len(doc)

def ocr_page(page):
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

def score_toc(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    score = 0
    if any('目次' in l or '目录' in l for l in lines):
        score += 3
    # 末尾有数字（目录条目特征：标题文字 + 页码）
    score += min(sum(1 for l in lines
                     if re.search(r'[\u4e00-\u9fff\w]\s*\d+\s*$', l)), 6)
    # 章节编号开头的行
    score += min(sum(1 for l in lines
                     if re.match(r'^[1-9]\d*(?:\.\d+)*[\s\u3000]', l)), 5)
    return score

# 从条文说明起始页本身开始扫描（标题页可能含目录），最多 15 页
scan_start = clause_0idx   # 包含标题页
print(f"\n扫描 PDF第{scan_start+1}页 → 第{min(scan_start+15, total)}页...")

candidates = []
for i in range(scan_start, min(scan_start + 15, total)):
    text = ocr_page(doc[i])
    s = score_toc(text)
    print(f"  PDF第{i+1}页: score={s}")
    if s >= 5:           # 高阈值，只取真正目录页（避免把正文误判）
        candidates.append(i)

if not candidates:
    print("未检测到条文说明目录页（该书可能无条文说明子目录），跳过提取。")
    import sys; sys.exit(0)

# 取第一个【严格连续】簇（不跳页，避免把正文页混入）
cluster = [candidates[0]]
for p in candidates[1:]:
    if p == cluster[-1] + 1:   # 严格连续，无间隔
        cluster.append(p)
    else:
        break

pages = list(range(cluster[0], cluster[-1] + 1))
if pages[-1] + 1 < total:
    pages.append(pages[-1] + 1)  # 额外包含下一页（安全边界）

print(f"\n提取页面（PDF页码）: {[p+1 for p in pages]}")
out = fitz.open()
for p in pages:
    out.insert_pdf(doc, from_page=p, to_page=p)
out.save(OUTPUT_PDF)
print(f"已保存: {OUTPUT_PDF}（{len(out)}页，{os.path.getsize(OUTPUT_PDF)//1024}KB）")
