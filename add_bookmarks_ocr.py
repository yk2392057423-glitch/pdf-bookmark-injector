"""
扫描版 PDF 自动生成目录书签（OCR 版）
流程：逐页渲染图片 → Tesseract OCR 识别文字 → 检测章节标题 → 写入书签
支持：中文 + 英文混排
"""
import re
import sys
import io
import os
import fitz        # PyMuPDF
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR = r"D:\claudecode_test\01pdf\tessdata"
os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
OCR_LANG = "chi_sim+eng"

# 渲染分辨率（越高越准，越慢；150dpi 是速度/质量平衡点）
DPI_SCALE = 150 / 72  # PDF默认72dpi，×比例得到目标DPI

INPUT_PDF  = sys.argv[1] if len(sys.argv) >= 2 else "my_book2.pdf"
OUTPUT_PDF = sys.argv[2] if len(sys.argv) >= 3 else INPUT_PDF.replace(".pdf", "_with_bookmarks.pdf")

CN_NUMS = "一二三四五六七八九十百千"

# 章节标题正则：首段数字限制1-2位（1-99），避免年份、编号被误匹配
RE_L1 = re.compile(r"^[1-9]\d?\s+[^\d\s]")              # 1-99 + 空格 + 标题文字
RE_L2 = re.compile(r"^[1-9]\d?\.\d{1,2}\s+[^\d\s]")    # 1.1 - 99.99 + 标题文字
RE_L3 = re.compile(r"^[1-9]\d?\.\d{1,2}\.\d{1,2}\s+[^\d\s]")  # 1.1.1 - 99.99.99
RE_CN1 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*[章篇卷部]\s*\S")
RE_CN2 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*节\s*\S")

# 单页命中数量上限：超过此值视为目录页，整页跳过
TOC_PAGE_THRESHOLD = 8

CODE_WORDS = re.compile(r"\b(null|true|false|none|undefined)\b", re.IGNORECASE)


def classify_heading(text: str):
    t = text.strip()
    if RE_L3.match(t): return 3
    if RE_L2.match(t): return 2
    # L1（章）：标题极短，总长 ≤ 20字符，且标题部分（数字后）含汉字
    if RE_L1.match(t) and len(t) <= 20:
        title_part = re.sub(r"^[1-9]\d?\s+", "", t)
        if re.search(r"[\u4e00-\u9fff]", title_part):
            return 1
    if RE_CN1.match(t): return 1
    if RE_CN2.match(t): return 2
    return None


def is_valid_title(text: str) -> bool:
    if not re.search(r"[a-zA-Z\u4e00-\u9fff]", text):
        return False
    if CODE_WORDS.search(text):
        return False
    return True


def ocr_page(page: fitz.Page) -> list[str]:
    """将 PDF 页渲染为图片，OCR 后返回文字行列表。"""
    mat = fitz.Matrix(DPI_SCALE, DPI_SCALE)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)  # 灰度，速度更快
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    # image_to_string 返回整页文字（保留换行）
    raw = pytesseract.image_to_string(
        img,
        lang=OCR_LANG,
        config="--psm 3"
    )
    return [line.strip() for line in raw.splitlines() if line.strip()]


def normalize_levels(toc: list) -> list:
    result = []
    prev = 1
    for entry in toc:
        lvl = max(1, min(entry[0], prev + 1))
        result.append([lvl, entry[1], entry[2]])
        prev = lvl
    return result


def main():
    print(f"正在打开：{INPUT_PDF}")
    doc = fitz.open(INPUT_PDF)
    total = len(doc)
    print(f"共 {total} 页（OCR模式，中文+英文）\n")

    bookmarks = []
    seen = set()

    for page_num in range(total):
        if page_num % 10 == 0:
            print(f"  OCR 进度：{page_num}/{total} 页...", flush=True)

        page = doc[page_num]
        lines = ocr_page(page)

        # 先统计本页候选数量，超过阈值则视为目录页跳过
        page_hits = [l for l in lines
                     if l and len(l) <= 100
                     and classify_heading(l) is not None
                     and is_valid_title(l)]
        if len(page_hits) > TOC_PAGE_THRESHOLD:
            continue  # 跳过目录页

        for line in page_hits:
            key = line[:80]
            if key in seen:
                continue
            seen.add(key)
            bookmarks.append((classify_heading(line), line, page_num))

    print(f"\n识别到 {len(bookmarks)} 个书签\n")

    if not bookmarks:
        print("未识别到任何书签。")
        print("可能原因：扫描质量差、版式特殊，或标题格式不匹配。")
        doc.close()
        return

    print("--- 书签预览 ---")
    for lvl, title, pg in bookmarks:
        indent = "  " * (lvl - 1)
        print(f"  第{pg+1:>4}页  {indent}[L{lvl}] {title}")

    toc = normalize_levels([[lvl, t, pg + 1] for lvl, t, pg in bookmarks])
    doc.set_toc(toc)
    doc.save(OUTPUT_PDF)
    doc.close()
    print(f"\n完成！已保存：{OUTPUT_PDF}")


if __name__ == "__main__":
    main()
