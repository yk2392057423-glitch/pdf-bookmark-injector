"""检查 OCR 输出内容 + 查看已生成书签"""
import os
os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"

import fitz
import pytesseract
import io
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF = r"D:\claudecode_test\01pdf\my_book2.pdf"
doc = fitz.open(PDF)

# 1. 查看已生成书签
bm_pdf = r"D:\claudecode_test\01pdf\my_book2_with_bookmarks.pdf"
if os.path.exists(bm_pdf):
    doc2 = fitz.open(bm_pdf)
    toc = doc2.get_toc()
    print(f"=== 书签总数: {len(toc)} ===")
    print("前 30 个书签:")
    for i, (lvl, title, pg) in enumerate(toc[:30]):
        print(f"  L{lvl} p{pg:3d}: {title}")
    doc2.close()

# 2. OCR 前 5 页内容（找到有文字的页面）
print("\n=== 前 8 页 OCR 文本（每页前 10 行）===")
mat = fitz.Matrix(150/72, 150/72)
for page_num in range(min(8, len(doc))):
    page = doc[page_num]
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    raw = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    print(f"\n--- 第 {page_num+1} 页 ({len(lines)} 行) ---")
    for line in lines[:10]:
        print(f"  {repr(line)}")
