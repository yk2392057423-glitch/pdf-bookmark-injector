"""
Step 1: 找出 PDF 中的目录页，保存为 toc_only.pdf
- 对前 20 页做低精度 OCR，检测含"目录"字样或大量"点+数字"的页面
"""
import os, io, re, sys
os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"
import fitz
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF_PATH   = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2.pdf"
TOC_OUTPUT = sys.argv[2] if len(sys.argv) >= 3 else r"D:\claudecode_test\01pdf\toc_only.pdf"

doc = fitz.open(PDF_PATH)
print(f"原始 PDF: {len(doc)} 页")

def quick_ocr(page):
    """低分辨率 OCR（只用于页面类型判断）"""
    mat = fitz.Matrix(1.5, 1.5)  # ~108 DPI
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

print("扫描前 20 页，寻找目录页...")
toc_pages = []
for i in range(min(20, len(doc))):
    text = quick_ocr(doc[i])
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 判断依据 1：含"目录"字样
    has_toc_word = any("目录" in l or "目 录" in l for l in lines)
    # 判断依据 2：大量"... 数字"结尾的行（典型目录格式）
    dot_num_lines = sum(1 for l in lines
                        if re.search(r'[\.\s]{3,}\d+\s*$', l) or
                           re.search(r'\s+\d+\s*$', l) and
                           re.match(r'^[1-9]', l))
    # 判断依据 3：包含多个章节编号（如 1.1、2.3 等）
    section_nums = sum(1 for l in lines if re.match(r'^[1-9]\d*(\.\d+)?\s+\S', l))

    score = (3 if has_toc_word else 0) + min(dot_num_lines, 5) + min(section_nums, 5)
    print(f"  第{i+1:2d}页: 目录词={has_toc_word}, 点数行={dot_num_lines}, 编号行={section_nums}, 得分={score}")

    if score >= 4:
        toc_pages.append(i)
        print(f"         ↑ 识别为目录页")

if not toc_pages:
    print("  未自动识别到目录页，使用第 4-8 页作为备用")
    toc_pages = list(range(3, min(8, len(doc))))
else:
    # 只保留最前面的连续簇（避免把正文页也算进来）
    toc_pages.sort()
    cluster = [toc_pages[0]]
    for p in toc_pages[1:]:
        if p <= cluster[-1] + 2:   # 允许1页间隔
            cluster.append(p)
        else:
            break  # 第一个连续簇结束
    # 填充簇内的空隙
    toc_pages = list(range(cluster[0], cluster[-1] + 1))
    # 往后多加1页防止漏掉
    toc_pages.append(min(cluster[-1] + 1, len(doc) - 1))

print(f"\n目录页范围: PDF 第 {[p+1 for p in toc_pages]} 页")

# 保存为独立 PDF
toc_doc = fitz.open()
for i in toc_pages:
    toc_doc.insert_pdf(doc, from_page=i, to_page=i)
toc_doc.save(TOC_OUTPUT)
toc_doc.close()

size_kb = os.path.getsize(TOC_OUTPUT) / 1024
print(f"\n已保存: {TOC_OUTPUT}  ({size_kb:.0f} KB, {len(toc_pages)} 页)")
print(f"TOC_PAGES={','.join(str(p) for p in toc_pages)}")  # 供后续步骤读取
