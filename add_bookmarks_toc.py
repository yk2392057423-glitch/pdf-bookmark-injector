"""
从 PDF 目录页提取书签（适合扫描版中文标准/规范）

思路：
  1. OCR 前 20 页，识别目录页（有大量"章节号 ... 页码"格式的行）
  2. 从目录页解析 L1/L2 书签（只要编号+页码，忽略乱码标题）
  3. 找到正文首页对应 PDF 页索引（页码偏移量）
  4. 写入书签
"""
import os, re, io, sys
os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"

import fitz
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

INPUT_PDF  = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2.pdf"
OUTPUT_PDF = sys.argv[2] if len(sys.argv) >= 3 else INPUT_PDF.replace(".pdf", "_with_bookmarks_toc.pdf")

# ── OCR 一页 ──────────────────────────────────────
def ocr_page(page, dpi=250):
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    raw = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")
    return [l.strip() for l in raw.splitlines() if l.strip()]

# ── 从一行中提取目录条目 ────────────────────────────
# 目录行格式: "3.2  基本规定 ............ 18"
# OCR 后可能: "3.2 ??P?......... 18" 或 "3.2 ??P? 18"
def parse_toc_line(line):
    """返回 (section_num, title_text, book_page) 或 None"""
    # 行首必须是章节编号（最多两级：1 或 1.1）
    m = re.match(r'^([1-9]\d{0,1}(?:\.\d{1,2})?)\s+(.+)', line)
    if not m:
        return None
    section_num = m.group(1)
    rest = m.group(2)
    # 行尾必须有数字（页码），前面可以是点、空格、任意字符
    page_m = re.search(r'[.\s](\d{1,3})\s*$', rest)
    if not page_m:
        # 也尝试直接结尾
        page_m = re.search(r'(\d{1,3})\s*$', rest)
    if not page_m:
        return None
    book_page = int(page_m.group(1))
    if book_page < 1 or book_page > 500:
        return None
    # 提取标题（点号前的内容）
    title = rest[:page_m.start()].strip(' .')
    # 去掉末尾连续的点或空格
    title = re.sub(r'[.\s]+$', '', title).strip()
    return section_num, title, book_page

# ── 判断是否目录页（有≥5条合法目录行）──────────────
def is_toc_page(lines):
    count = sum(1 for l in lines if parse_toc_line(l) is not None)
    return count >= 5

# ── 主流程 ─────────────────────────────────────────
doc = fitz.open(INPUT_PDF)
total = len(doc)
print(f"PDF: {total} 页")

# 第一步：扫描前 20 页，提取目录
print("\n[1/4] 扫描目录页（前 20 页）...")
all_entries = []   # [(section_num, title, book_page)]
toc_pages_found = []

for i in range(min(20, total)):
    lines = ocr_page(doc[i])
    if is_toc_page(lines):
        toc_pages_found.append(i+1)
        page_entries = []
        for line in lines:
            e = parse_toc_line(line)
            if e:
                page_entries.append(e)
        all_entries.extend(page_entries)
        print(f"  PDF第{i+1}页 → 目录页，提取 {len(page_entries)} 条")
        for e in page_entries[:5]:
            print(f"    {e[0]:8s}  book_p={e[2]:3d}  title={repr(e[1][:30])}")
        if len(page_entries) > 5:
            print(f"    ...共 {len(page_entries)} 条")

if not all_entries:
    print("  未找到目录页！改为尝试更宽松的扫描（前30页）...")
    for i in range(min(30, total)):
        lines = ocr_page(doc[i])
        for line in lines:
            e = parse_toc_line(line)
            if e:
                all_entries.append(e)

print(f"\n  原始目录条目总数: {len(all_entries)}")

# 第二步：去重 + 只保留 L1/L2
print("\n[2/4] 过滤 L1/L2，去重...")
def get_level(s):
    return 1 if '.' not in s else 2

seen = {}
for section_num, title, book_page in all_entries:
    if section_num not in seen:
        seen[section_num] = (title, book_page)
    # 如果已有，保留页码较小的（更可能是正确的）

entries_l1l2 = []
for section_num, (title, book_page) in seen.items():
    lvl = get_level(section_num)
    entries_l1l2.append((lvl, section_num, title, book_page))

# 按章节编号排序
def sort_key(e):
    parts = e[1].split('.')
    return tuple(int(x) for x in parts) + (0,) * (4 - len(parts))

entries_l1l2.sort(key=sort_key)
print(f"  L1/L2 条目数: {len(entries_l1l2)}")
for e in entries_l1l2[:10]:
    print(f"  L{e[0]} {e[1]:8s}  book_p={e[3]:3d}")

# 第三步：找页码偏移量
print("\n[3/4] 确定页码偏移量...")
offset = None

# 从目录中找第1章的书页码
ch1_book_page = None
for lvl, section_num, title, book_page in entries_l1l2:
    if section_num == '1' and lvl == 1:
        ch1_book_page = book_page
        print(f"  目录中第1章的书页码: {ch1_book_page}")
        break

if ch1_book_page is not None:
    # 从 PDF 第4页开始扫描，找第1章出现的页面
    print("  在 PDF 中寻找第1章起始位置...")
    for i in range(3, min(25, total)):
        lines = ocr_page(doc[i])
        for line in lines[:6]:  # 只看每页前6行（标题在页面顶部）
            if re.match(r'^1\s+\S', line) or re.match(r'^1\s*$', line):
                offset = i - (ch1_book_page - 1)
                print(f"  第1章出现在 PDF 第{i+1}页，书页码={ch1_book_page}，offset={offset}")
                break
        if offset is not None:
            break

if offset is None:
    # 启发式：假设正文从 PDF 第 8 页开始，书页码为 1
    offset = 7
    print(f"  未自动找到，使用默认 offset={offset}")

# 第四步：构建书签列表
print("\n[4/4] 生成书签...")

def normalize_levels(toc):
    result, prev = [], 1
    for entry in toc:
        lvl = max(1, min(entry[0], prev + 1))
        result.append([lvl, entry[1], entry[2]])
        prev = lvl
    return result

bookmarks = []
for lvl, section_num, title, book_page in entries_l1l2:
    pdf_page = book_page - 1 + offset  # 0-indexed → PyMuPDF 需要 1-indexed
    pdf_page_1idx = pdf_page + 1
    if pdf_page_1idx < 1 or pdf_page_1idx > total:
        print(f"  跳过越界: {section_num} book_p={book_page} → pdf_p={pdf_page_1idx}")
        continue
    # 使用章节号作为书签标题前缀，OCR 中文标题作为后缀（可能乱码但有参考价值）
    if title and len(title) > 1:
        full_title = f"{section_num}  {title}"
    else:
        full_title = section_num
    bookmarks.append([lvl, full_title, pdf_page_1idx])

bookmarks = normalize_levels(bookmarks)

print(f"  最终书签数: {len(bookmarks)}")
print("  预览（前 20 条）:")
for b in bookmarks[:20]:
    print(f"  L{b[0]}  p{b[2]:3d}  {b[1][:60]}")

doc.set_toc(bookmarks)
doc.save(OUTPUT_PDF)
print(f"\n完成！输出: {OUTPUT_PDF}")
print(f"  文件大小: {os.path.getsize(OUTPUT_PDF)/1024/1024:.1f} MB")
