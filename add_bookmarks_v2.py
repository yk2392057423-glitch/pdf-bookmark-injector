"""
扫描版 PDF 书签生成 v2
核心改进：
  1. 顺序验证：章节号必须递增，过滤乱序误匹配
  2. 只要 L1+L2（不要 L3），消灭 341 个条款误匹配
  3. 250 DPI（比 150 DPI 识别率更高）
  4. 跳过前 N 页（封面/前言/目录）
"""
import os, re, io, sys
os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"

import fitz
import pytesseract
from PIL import Image
from collections import Counter

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

INPUT_PDF  = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2.pdf"
OUTPUT_PDF = sys.argv[2] if len(sys.argv) >= 3 else INPUT_PDF.replace(".pdf", "_with_bookmarks_v2.pdf")

# ── 正则：L1 = 单个数字(1-19)，L2 = 两级数字(1.1-19.9) ─────────
# 要求：编号后跟空格，后面必须有非数字非空格字符（排除纯数字行）
RE_L1 = re.compile(r'^([1-9]\d?)\s+[^\d\s]')  # "3 xxx"
RE_L2 = re.compile(r'^([1-9]\d?)\.(\d{1,2})\s+[^\d\s]')  # "3.1 xxx"

CN_NUMS = "一二三四五六七八九十百千"
RE_CN1 = re.compile(r'^第\s*[' + CN_NUMS + r'\d]+\s*[章篇卷]\s*\S')

# ── OCR 一页 ───────────────────────────────────────────────────
def ocr_page(page, dpi=250):
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    raw = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")
    return [l.strip() for l in raw.splitlines() if l.strip()]

# ── 从 OCR 行提取章节级别 ──────────────────────────────────────
def classify_line(text):
    """返回 (level, chapter, section, full_text) 或 None"""
    t = text.strip()
    m2 = RE_L2.match(t)
    if m2:
        ch, sec = int(m2.group(1)), int(m2.group(2))
        return (2, ch, sec, t)
    m1 = RE_L1.match(t)
    if m1:
        ch = int(m1.group(1))
        if ch > 20:  # 章序号不超过 20
            return None
        return (1, ch, 0, t)
    if RE_CN1.match(t):
        return (1, -1, 0, t)  # 中文章节，章号未知
    return None

# ── 顺序验证器 ─────────────────────────────────────────────────
class SequentialValidator:
    def __init__(self):
        self.last_l1 = 0       # 上一个 L1 章号
        self.last_l2_ch = 0    # L2 所属章号
        self.last_l2_sec = 0   # L2 节号

    def validate(self, level, ch, sec):
        if level == 1:
            if ch <= 0:  # 中文章节，无法验证，直接接受
                self.last_l1 += 1
                self.last_l2_ch = 0
                self.last_l2_sec = 0
                return True
            # 章号必须大于上一章，且跳跃不超过 2
            if ch <= self.last_l1:
                return False  # 重复或倒退
            if ch > self.last_l1 + 1:
                return False  # 必须顺序递增，不允许跳章
            self.last_l1 = ch
            self.last_l2_ch = 0
            self.last_l2_sec = 0
            return True

        elif level == 2:
            # 所属章必须是当前章（允许稍微超前 1 章，防止漏掉章标题）
            if ch < self.last_l1:
                return False  # 节所属章早于当前章
            if ch > self.last_l1 + 1:
                return False  # 节所属章超出当前章太多
            # 节号必须递增（同章内）
            if ch == self.last_l2_ch:
                if sec <= self.last_l2_sec:
                    return False  # 同章内节号倒退或重复
            # 接受
            if ch > self.last_l1:
                self.last_l1 = ch  # 隐式升章
            self.last_l2_ch = ch
            self.last_l2_sec = sec
            return True

        return False

# ── 去重标题（同一标题只保留第一次出现）────────────────────────
def normalize_levels(toc):
    result, prev = [], 1
    for entry in toc:
        lvl = max(1, min(entry[0], prev + 1))
        result.append([lvl, entry[1], entry[2]])
        prev = lvl
    return result

# ── 主流程 ──────────────────────────────────────────────────────
doc = fitz.open(INPUT_PDF)
total = len(doc)
print(f"PDF: {total} 页")

# 自动探测跳过前几页（找到正文起始页：出现"1 xxx"的第一个有内容页）
SKIP_PAGES = 7  # 默认跳过前 7 页
for i in range(3, min(20, total)):
    lines = ocr_page(doc[i], dpi=200)
    for line in lines[:8]:
        r = classify_line(line)
        if r and r[0] == 1 and r[1] == 1:
            SKIP_PAGES = i
            print(f"检测到第1章起始于 PDF 第{i+1}页，跳过前 {SKIP_PAGES} 页")
            break
    else:
        continue
    break
else:
    print(f"未检测到第1章，使用默认跳过前 {SKIP_PAGES} 页")

print(f"扫描 PDF 第 {SKIP_PAGES+1} ~ {total} 页...\n")

validator = SequentialValidator()
bookmarks = []
seen_titles = set()

for page_idx in range(SKIP_PAGES, total):
    lines = ocr_page(doc[page_idx])
    page_num_1idx = page_idx + 1  # PyMuPDF 1-indexed

    for line in lines:
        r = classify_line(line)
        if r is None:
            continue
        level, ch, sec, full_text = r

        if not validator.validate(level, ch, sec):
            continue

        # 去重：完全相同的标题只保留一次
        key = full_text[:50]
        if key in seen_titles:
            continue
        seen_titles.add(key)

        bookmarks.append([level, full_text, page_num_1idx])

# 层级规范化
bookmarks = normalize_levels(bookmarks)

print(f"书签总数: {len(bookmarks)}")
l1_count = sum(1 for b in bookmarks if b[0]==1)
l2_count = sum(1 for b in bookmarks if b[0]==2)
print(f"  L1(章): {l1_count}  L2(节): {l2_count}")
print("\n全部书签:")
for b in bookmarks:
    print(f"  L{b[0]}  p{b[2]:3d}  {b[1][:70]}")

doc.set_toc(bookmarks)
doc.save(OUTPUT_PDF)
print(f"\n输出: {OUTPUT_PDF}")
print(f"文件大小: {os.path.getsize(OUTPUT_PDF)/1024/1024:.1f} MB")
