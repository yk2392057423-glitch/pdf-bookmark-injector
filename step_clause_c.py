"""
Step Clause-C: 解析条文说明目录的 MinerU 输出 → 注入子书签至现有 PDF
子书签层级：条文说明(L1) → 各章(L2) → 各节(L3)
"""
import os, re, sys, json, glob
import fitz

BOOKMARKED_PDF = sys.argv[1] if len(sys.argv) >= 2 else r"D:\claudecode_test\01pdf\my_book2_final.pdf"
MINERU_DIR     = sys.argv[2] if len(sys.argv) >= 3 else r"D:\claudecode_test\01pdf\clause_mineru_out"
OUTPUT_PDF     = sys.argv[3] if len(sys.argv) >= 4 else r"D:\claudecode_test\01pdf\my_book2_final.pdf"
# 已知主内容页码偏移（book_page + offset = pdf_page_0idx + 1）
OFFSET_HINT    = int(sys.argv[4]) if len(sys.argv) >= 5 else 7

# ── 解析函数（与 step3 相同，保持同步） ─────────────────────────
RE_SEC  = re.compile(r'^([1-9]\d*(?:\.\d+)*)\s*(.*)')
_TRAIL  = re.compile(r'[\u2026\u00b7\uff0e\uff0c\uff0e.\s\uff08\uff3b（【(]+$')

def clean_title(t):
    return _TRAIL.sub('', t).strip()

def find_page_num(text):
    """从行尾提取页码，支持 '123'、'(123)'、'（123）'、'（=123）' 等格式"""
    m = re.search(r'[\uff08（(\[【]\s*[=＝]?\s*(\d{1,4})\s*[\uff09）)\]】]\s*$', text)
    if m:
        return m, int(m.group(1))
    m = re.search(r'(\d{1,4})\s*$', text)
    if m:
        return m, int(m.group(1))
    return None, None

_SPECIALS = [
    ('附：条文说明',   '条文说明'),
    ('标准用词说明',   '标准用词说明'),
    ('本规范用词说明', '本规范用词说明'),
    ('引用标准名录',   '引用标准名录'),
    ('条文说明',       '条文说明'),
]

def parse_toc_line(line):
    line = line.strip()
    if not line:
        return None
    # 附录格式
    app_m = re.match(r'^附录([A-Z])\s*(.*)', line)
    if app_m:
        sec  = f"附录{app_m.group(1)}"
        rest = app_m.group(2)
        pm, page = find_page_num(rest)
        if pm and 1 <= page <= 600:
            title = clean_title(rest[:pm.start()])
            if title:
                return (1, sec, title, page)
    # 特殊条目
    for kw, label in _SPECIALS:
        if line.startswith(kw):
            pm, page = find_page_num(line[len(kw):])
            if pm and 1 <= page <= 600:
                return (1, label, "", page)
    # 数字编号章节
    m = RE_SEC.match(line)
    if not m:
        return None
    sec  = m.group(1)
    rest = m.group(2).strip()
    if not rest:
        return None
    pm, page = find_page_num(rest)
    if not pm:
        return None
    if not (1 <= page <= 600):
        return None
    title = clean_title(rest[:pm.start()])
    if not title:
        return None
    return (len(sec.split('.')), sec, title, page)

def split_merged_entries(line):
    parts = re.split(
        r'(?<=[）)】\]])\s*'
        r'(?=[1-9]\d*(?:\.\d+)?\s*[\u4e00-\u9fff]'
        r'|附录[A-Z]|附：|标准用词|本规范用词|引用标准)',
        line
    )
    return [p.strip() for p in parts if p.strip()]

def preprocess_lines(lines):
    merged, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if (re.match(r'^附录[A-Z]', line)
                and not re.search(r'\d+\s*$', line)
                and not re.search(r'[）)】\]]\s*$', line)):
            if i + 1 < len(lines) and lines[i+1].strip():
                line += lines[i+1].strip()
                i += 1
        merged.append(line)
        i += 1
    result = []
    for line in merged:
        result.extend(split_merged_entries(line))
    return result

def load_content_list(path):
    items = json.load(open(path, encoding='utf-8'))
    lines = []
    for it in items:
        t = it.get('text', '').strip()
        if t:
            lines.extend(t.splitlines())
    return lines

def load_markdown(path):
    return open(path, encoding='utf-8').read().splitlines()

# ── 加载 MinerU 输出 ────────────────────────────────────────────
print("=== Step Clause-C: 解析条文说明目录 ===")
cl = glob.glob(os.path.join(MINERU_DIR, '**', '*content_list.json'), recursive=True)
md = glob.glob(os.path.join(MINERU_DIR, '**', '*.md'), recursive=True)
print(f"content_list.json: {cl}")
print(f"Markdown files:    {md}")

all_lines = []
if cl:
    for f in cl:
        all_lines.extend(load_content_list(f))
    print(f"从 content_list.json 读取 {len(all_lines)} 行")
elif md:
    for f in md:
        all_lines.extend(load_markdown(f))
    print(f"从 Markdown 读取 {len(all_lines)} 行")
else:
    print("错误：未找到 MinerU 输出！")
    sys.exit(1)

all_lines = preprocess_lines(all_lines)

print("\n--- 解析条目 ---")
raw = []
for line in all_lines:
    e = parse_toc_line(line)
    if e:
        raw.append(e)
        print(f"  L{e[0]}  {e[1]:10s}  p={e[3]:3d}  '{e[2][:40]}'")

print(f"\n共解析 {len(raw)} 条")
if not raw:
    print("警告：未解析到任何条目！原始行（前30行）：")
    for l in all_lines[:30]:
        print(f"  {repr(l)}")
    sys.exit(1)

# ── 从已书签 PDF 定位条文说明 ───────────────────────────────────
print("\n=== 打开已书签 PDF ===")
doc   = fitz.open(BOOKMARKED_PDF)
total = len(doc)
toc   = doc.get_toc()

clause_1idx = clause_idx = None
for i, item in enumerate(toc):
    if '条文说明' in item[1]:
        clause_1idx = item[2]   # 1-indexed PDF 页
        clause_idx  = i
        break

if clause_1idx is None:
    print("错误：书签中未找到条文说明！")
    sys.exit(1)

clause_0idx = clause_1idx - 1
print(f"条文说明: PDF第{clause_1idx}页，书签下标={clause_idx}")

offset = OFFSET_HINT
print(f"\n使用页码偏移 offset={offset}")

# ── 构建子书签（L1→L2, L2→L3，只取两层） ───────────────────────
print("\n=== 构建子书签 ===")
seen = set()
sub  = []
for level, sec, title, book_page in raw:
    if level > 2 or sec in seen:
        continue
    seen.add(sec)
    pdf_p = book_page - 1 + offset + 1   # 转为 1-indexed
    if pdf_p < clause_1idx or pdf_p > total:
        print(f"  跳过越界: {sec} book_p={book_page} → pdf_p={pdf_p}")
        continue
    full = f"{sec}  {title}" if title else sec
    sub.append([level + 1, full, pdf_p])  # 升一级

print(f"子书签数: {len(sub)}")
for b in sub:
    print(f"  L{b[0]}  p{b[2]:3d}  {b[1][:60]}")

# ── 插入到现有书签并保存 ─────────────────────────────────────────
new_toc = toc[:clause_idx+1] + sub + toc[clause_idx+1:]
doc.set_toc(new_toc)

# 若输出路径与输入相同，先写临时文件再替换
if os.path.abspath(OUTPUT_PDF) == os.path.abspath(BOOKMARKED_PDF):
    tmp = OUTPUT_PDF + ".tmp"
    doc.save(tmp)
    doc.close()
    os.replace(tmp, OUTPUT_PDF)
else:
    doc.save(OUTPUT_PDF)
    doc.close()

print(f"\n完成！输出: {OUTPUT_PDF}")
print(f"总书签: {len(new_toc)}，文件大小: {os.path.getsize(OUTPUT_PDF)/1024/1024:.1f}MB")
