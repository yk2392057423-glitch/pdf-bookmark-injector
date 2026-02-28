"""
Step 3+4: 解析 MinerU 输出的 Markdown → 提取目录条目 → 注入书签

支持两种 MinerU 输出格式：
  - *_content_list.json（结构化，优先）
  - *.md（Markdown 文本，备用）
"""
import os, re, io, sys, json, glob
os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"
import fitz
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF_PATH     = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2.pdf"
MINERU_DIR   = sys.argv[2] if len(sys.argv) >= 3 else r"D:\claudecode_test\01pdf\toc_mineru_out"
OUTPUT_PDF   = sys.argv[3] if len(sys.argv) >= 4 else r"D:\claudecode_test\01pdf\my_book2_toc_bookmarks.pdf"
# 目录页在原始 PDF 中的起始物理页（0-indexed，默认 3 即第4页）
TOC_START_PAGE = int(sys.argv[4]) if len(sys.argv) >= 5 else 3

# ── 解析一行目录条目 ────────────────────────────────────────────
# 目标格式：章节编号  标题文字  ........  页码
# MinerU OCR 后可能是：
#   "3.2 材料强度标准值与设计值规定 18"
#   "3.2 材料强度...............18"
#   "3.2材料强度18"
RE_SEC_PREFIX = re.compile(r'^([1-9]\d*(?:\.\d+)*)\s*(.*)')

# 去除标题末尾的省略号/点号/左括号（含全角）
_TRAIL = re.compile(r'[\u2026\u00b7\uff0e\uff0c\uff0e.\s\uff08\uff3b（【(]+$')

def clean_title(t):
    return _TRAIL.sub('', t).strip()

def find_page_num(text):
    """从行尾提取页码，支持 '123'、'(123)'、'（123）'、'（=123）' 等格式"""
    # 全角/半角括号，允许括号内含 = 等 OCR 噪音
    m = re.search(r'[\uff08（(\[【]\s*[=＝]?\s*(\d{1,4})\s*[\uff09）)\]】]\s*$', text)
    if m:
        return m, int(m.group(1))
    # 裸数字
    m = re.search(r'(\d{1,4})\s*$', text)
    if m:
        return m, int(m.group(1))
    return None, None

# 特殊条目关键词 → 书签标题映射
_SPECIALS = [
    ('附：条文说明',   '条文说明'),
    ('标准用词说明',   '标准用词说明'),
    ('本规范用词说明', '本规范用词说明'),
    ('引用标准名录',   '引用标准名录'),
    ('条文说明',       '条文说明'),
]

def parse_toc_line(line):
    """返回 (level, section_num, title, book_page) 或 None"""
    line = line.strip()
    if not line:
        return None

    # ── 附录格式："附录A 标题 184" 或 "附录B标题（49）"（各种页码格式）──
    app_m = re.match(r'^附录([A-Z])\s*(.*)', line)
    if app_m:
        sec  = f"附录{app_m.group(1)}"
        rest = app_m.group(2)
        pm, page = find_page_num(rest)
        if pm and 1 <= page <= 600:
            title = clean_title(rest[:pm.start()])
            if title:
                return (1, sec, title, page)

    # ── 特殊条目："标准用词说明"/"条文说明"/"本规范用词说明" 等 ──
    for kw, label in _SPECIALS:
        if line.startswith(kw):
            pm, page = find_page_num(line[len(kw):])
            if pm and 1 <= page <= 600:
                # 以 label 作为 sec（去重键+显示名），title 留空避免重复显示
                return (1, label, "", page)

    # ── 数字编号章节 ──
    m = RE_SEC_PREFIX.match(line)
    if not m:
        return None

    sec  = m.group(1)
    rest = m.group(2).strip()
    if not rest:
        return None

    pm, page = find_page_num(rest)
    if not pm:
        if sec == '1':           # 第1章常常没有页码，默认页码 1
            title = clean_title(rest)
            if title:
                return (1, sec, title, 1)
        return None

    if page < 1 or page > 600:
        return None

    title = clean_title(rest[:pm.start()])
    if not title:
        return None

    level = len(sec.split('.'))
    return (level, sec, title, page)


def split_merged_entries(line):
    """拆分同行里的多个目录条目（括号页码后紧接新条目）"""
    parts = re.split(
        r'(?<=[）)】\]])\s*'
        r'(?=[1-9]\d*(?:\.\d+)?\s*[\u4e00-\u9fff]'
        r'|附录[A-Z]|附：|标准用词|本规范用词|引用标准)',
        line
    )
    return [p.strip() for p in parts if p.strip()]

def preprocess_lines(lines):
    """预处理：① 合并跨行附录条目；② 拆分同行多条目"""
    # 第一步：合并跨行附录（如附录D标题被换行截断）
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # 附录行无末尾数字且无右括号 → 与下一行合并
        if (re.match(r'^附录[A-Z]', line)
                and not re.search(r'\d+\s*$', line)
                and not re.search(r'[）)】\]]\s*$', line)):
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt:
                    line = line + nxt
                    i += 1
        merged.append(line)
        i += 1
    # 第二步：拆分同行多条目（支持括号页码格式，如 book3）
    result = []
    for line in merged:
        result.extend(split_merged_entries(line))
    return result

# ── 从 content_list.json 提取文本行 ────────────────────────────
def load_from_content_list(path):
    with open(path, encoding='utf-8') as f:
        items = json.load(f)
    lines = []
    for item in items:
        t = item.get('text', '').strip()
        if t:
            lines.extend(t.splitlines())
    return lines

# ── 从 Markdown 文件提取文本行 ──────────────────────────────────
def load_from_markdown(path):
    with open(path, encoding='utf-8') as f:
        return f.read().splitlines()

# ── 寻找 MinerU 输出文件 ────────────────────────────────────────
def find_mineru_outputs(mineru_dir):
    cl = glob.glob(os.path.join(mineru_dir, '**', '*content_list.json'), recursive=True)
    md = glob.glob(os.path.join(mineru_dir, '**', '*.md'), recursive=True)
    return cl, md

# ── 主流程 ──────────────────────────────────────────────────────
print("=== Step 3: 解析 MinerU 输出 ===")
cl_files, md_files = find_mineru_outputs(MINERU_DIR)
print(f"content_list.json: {cl_files}")
print(f"Markdown files:    {md_files}")

all_lines = []
if cl_files:
    for f in cl_files:
        all_lines.extend(load_from_content_list(f))
    print(f"从 content_list.json 读取 {len(all_lines)} 行")
elif md_files:
    for f in md_files:
        all_lines.extend(load_from_markdown(f))
    print(f"从 Markdown 读取 {len(all_lines)} 行")
else:
    print("错误：未找到 MinerU 输出文件！")
    sys.exit(1)

all_lines = preprocess_lines(all_lines)

# 解析目录条目
print("\n--- 解析目录条目 ---")
raw_entries = []  # [(level, sec, title, book_page)]
for line in all_lines:
    e = parse_toc_line(line)
    if e:
        raw_entries.append(e)
        print(f"  L{e[0]}  {e[1]:10s}  p={e[3]:3d}  '{e[2][:40]}'")

print(f"\n共解析 {len(raw_entries)} 条目录条目")

if not raw_entries:
    print("警告：解析到 0 条，请检查 MinerU 输出内容")
    print("原始行（前30行）：")
    for l in all_lines[:30]:
        print(f"  {repr(l)}")
    sys.exit(1)

# ── Step 4: 确定物理页码偏移 ────────────────────────────────────
print("\n=== Step 4: 确定页码偏移量 ===")
doc = fitz.open(PDF_PATH)
total = len(doc)

# 找第一章（编号="1"）的书页码
first_sec = next((e for e in raw_entries if e[1] == '1'), None)
if first_sec is None:
    first_sec = raw_entries[0]  # 用第一个条目

book_page_1 = first_sec[3]  # 第一章在书中的页码
sec_num_1   = first_sec[1]
print(f"目录显示：{sec_num_1} 章 → 书页码 {book_page_1}")

# 在 PDF 正文中 OCR 找该章节编号
def quick_ocr(page):
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

offset = None
pat     = re.compile(r'^' + re.escape(sec_num_1) + r'\s+\S')  # "1 某字"
sub_pat = re.compile(r'^' + re.escape(sec_num_1) + r'\.')      # "1." 子条文（内容页特征）
for i in range(TOC_START_PAGE, min(TOC_START_PAGE + 30, total)):
    lines = [l.strip() for l in quick_ocr(doc[i]).splitlines() if l.strip()]
    for j, line in enumerate(lines[:8]):  # 只看页面顶部几行
        if not pat.match(line):
            continue
        # 验证：正文章节页的后续行包含 "1.X.Y" 子条文；
        # 目录页的后续行是 "2 术语 ..." 等其他章节编号 → 跳过
        following = lines[j+1 : j+6]
        if following and not any(sub_pat.match(fl) for fl in following):
            continue  # 疑似目录页，继续找下一行/下一页
        offset = i - (book_page_1 - 1)
        print(f"在 PDF 第{i+1}页找到 '{sec_num_1}' 章，书页码={book_page_1}，offset={offset}")
        break
    if offset is not None:
        break

if offset is None:
    offset = TOC_START_PAGE + 4  # 启发式默认值
    print(f"未自动找到，使用估算 offset={offset}")

# ── 构建书签列表（只取 L1 + L2）──────────────────────────────────
print("\n=== 构建书签 ===")

def normalize_levels(toc):
    result, prev = [], 1
    for e in toc:
        lvl = max(1, min(e[0], prev + 1))
        result.append([lvl, e[1], e[2]])
        prev = lvl
    return result

seen = set()
bookmarks = []
for level, sec, title, book_page in raw_entries:
    if level > 2:           # 只要 L1 和 L2
        continue
    if sec in seen:
        continue
    seen.add(sec)
    pdf_page = book_page - 1 + offset   # 0-indexed → PyMuPDF 1-indexed
    pdf_page_1idx = pdf_page + 1
    if pdf_page_1idx < 1 or pdf_page_1idx > total:
        print(f"  跳过越界: {sec} book_p={book_page} → pdf_p={pdf_page_1idx}")
        continue
    full_title = f"{sec}  {title}" if title else sec
    bookmarks.append([level, full_title, pdf_page_1idx])

bookmarks = normalize_levels(bookmarks)

print(f"最终书签数: {len(bookmarks)}")
for b in bookmarks:
    print(f"  L{b[0]}  p{b[2]:3d}  {b[1][:60]}")

# ── 写入 PDF ────────────────────────────────────────────────────
doc.set_toc(bookmarks)
doc.save(OUTPUT_PDF)
print(f"\n完成！输出: {OUTPUT_PDF}")
print(f"文件大小: {os.path.getsize(OUTPUT_PDF)/1024/1024:.1f} MB")
