"""
PDF 书签注入流水线核心逻辑
整合自: step1_extract_toc.py, step3_parse_inject.py, step_clause_a.py, step_clause_c.py

所有 print() 替换为 emit(type, msg, ...) 调用，向 SSE 队列发送事件。
"""
import os, re, io, json, glob, shutil, requests, zipfile, time

import fitz
import pytesseract
from PIL import Image


def _setup_tesseract():
    """自动定位 tesseract 和包含 chi_sim.traineddata 的 tessdata 目录。"""
    cmd = os.environ.get("TESSERACT_CMD",
                         r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    pytesseract.pytesseract.tesseract_cmd = cmd

    # 候选 tessdata 目录（按优先级）
    candidates = [
        os.environ.get("TESSDATA_PREFIX", ""),                        # 环境变量
        os.path.join(os.path.dirname(os.path.abspath(cmd)), "tessdata"),  # exe 同级
        r"C:\Program Files\Tesseract-OCR\tessdata",                   # 默认安装路径
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    ]
    for p in candidates:
        if p and os.path.isfile(os.path.join(p, "chi_sim.traineddata")):
            os.environ["TESSDATA_PREFIX"] = p
            return


_setup_tesseract()

MINERU_API_TOKEN = os.environ.get('MINERU_API_TOKEN', '')
MINERU_API_BASE  = 'https://mineru.net/api/v4'


# ══════════════════════════════════════════════════════
# Step 1 辅助：页面缩略图 & 目录页自动检测
# ══════════════════════════════════════════════════════

def get_pdf_page_count(pdf_path):
    """返回 PDF 总页数。"""
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return n


def render_page_thumbnail(pdf_path, page_num, width=130):
    """将指定页渲染为 PNG bytes（低分辨率，用于预览）。"""
    doc = fitz.open(pdf_path)
    if page_num < 0 or page_num >= len(doc):
        doc.close()
        return None
    page  = doc[page_num]
    scale = width / page.rect.width
    mat   = fitz.Matrix(scale, scale)
    pix   = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    data  = pix.tobytes("png")
    doc.close()
    return data


def _score_page_for_toc(page):
    """对单页做轻量 OCR 打分，返回 (score, has_toc_word)。"""
    # 优先使用内嵌文本（born-digital PDF 瞬间完成）
    text = page.get_text()
    if len(text.strip()) < 30:
        # 扫描版：OCR，用 1.0x 比 1.5x 快约 40%
        mat = fitz.Matrix(1.0, 1.0)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    has_toc_word  = any("目录" in l or "目 录" in l for l in lines)
    dot_num_lines = sum(1 for l in lines
                        if re.search(r'[\.\s]{3,}\d+\s*$', l) or
                           re.search(r'\s+\d+\s*$', l) and re.match(r'^[1-9]', l))
    section_nums  = sum(1 for l in lines if re.match(r'^[1-9]\d*(\.\d+)?\s+\S', l))
    score = (3 if has_toc_word else 0) + min(dot_num_lines, 5) + min(section_nums, 5)
    return score, has_toc_word


def detect_toc_pages(pdf_path, scan_limit=25):
    """
    OCR 扫描前 scan_limit 页，返回每页评分列表：
      [{'page': int, 'score': int, 'detected': bool}, ...]
    后台线程调用，不阻塞主进程。
    """
    doc     = fitz.open(pdf_path)
    total   = len(doc)
    results = []
    for i in range(min(scan_limit, total)):
        score, _ = _score_page_for_toc(doc[i])
        results.append({'page': i, 'score': score, 'detected': score >= 4})
    doc.close()
    return results


# ══════════════════════════════════════════════════════
# Step 1: 将用户选定的页面提取为独立 PDF
# ══════════════════════════════════════════════════════

def extract_toc_pages(pdf_path, selected_pages, toc_out, emit):
    """
    将用户选定的页面（0-indexed）保存为 toc_out PDF。
    返回后续章节扫描起始页（0-indexed）。
    """
    emit('step_start', '提取目录页...', step=1, progress=0)

    doc      = fitz.open(pdf_path)
    total    = len(doc)
    selected = sorted(set(p for p in selected_pages if 0 <= p < total))

    emit('log', f'原始 PDF: {total} 页')
    emit('log', f'目录页: PDF 第 {[p+1 for p in selected]} 页')

    toc_doc = fitz.open()
    for i in selected:
        toc_doc.insert_pdf(doc, from_page=i, to_page=i)
    toc_doc.save(toc_out)
    toc_doc.close()
    doc.close()

    size_kb = os.path.getsize(toc_out) / 1024
    emit('log', f'已保存目录 PDF: {toc_out}  ({size_kb:.0f} KB, {len(selected)} 页)')

    scan_start = (max(selected) + 1) if selected else 7
    return scan_start


# ══════════════════════════════════════════════════════
# Step 2 / Step 5: MinerU Cloud API
# ══════════════════════════════════════════════════════

def _run_mineru_api(pdf_path, out_dir, emit, step_num, start_pct):
    """调用 MinerU Cloud API 解析 PDF，替代本地 magic-pdf。"""
    token = MINERU_API_TOKEN
    if not token:
        raise RuntimeError('未设置 MINERU_API_TOKEN')

    emit('step_start', 'MinerU Cloud API 处理中...', step=step_num, progress=start_pct)
    headers = {
        'Authorization': f'Bearer {MINERU_API_TOKEN}',
        'Content-Type': 'application/json',
    }

    # 1. 获取预签名上传地址
    emit('log', '正在获取上传地址...')
    filename = os.path.basename(pdf_path)
    resp = requests.post(
        f'{MINERU_API_BASE}/file-urls/batch',
        headers=headers,
        json={'files': [{'name': filename, 'is_ocr': True, 'data_id': filename}]},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get('code') != 0:
        raise RuntimeError(f'获取上传地址失败: {body}')
    batch_id   = body['data']['batch_id']
    upload_url = body['data']['file_urls'][0]

    # 2. 上传 PDF
    size_kb = os.path.getsize(pdf_path) // 1024
    emit('log', f'上传 PDF（{size_kb} KB）...')
    with open(pdf_path, 'rb') as f:
        requests.put(upload_url, data=f, timeout=120).raise_for_status()
    emit('log', '上传完成，等待云端解析...')

    # 3. 轮询结果（最多等 10 分钟）
    auth_headers = {'Authorization': f'Bearer {MINERU_API_TOKEN}'}
    for attempt in range(120):
        time.sleep(5)
        r = requests.get(
            f'{MINERU_API_BASE}/extract-results/batch/{batch_id}',
            headers=auth_headers,
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()
        if result.get('code') != 0:
            raise RuntimeError(f'查询失败: {result}')
        files = result['data'].get('extract_result', [])
        if not files:
            continue
        state = files[0].get('state', '')
        emit('log', f'[MinerU] 状态: {state}（已等待 {attempt * 5}s）')
        if state == 'done':
            zip_url = files[0]['full_zip_url']
            break
        if state == 'failed':
            raise RuntimeError(f'MinerU 解析失败: {files[0].get("err_msg")}')
    else:
        raise RuntimeError('MinerU API 超时（10 分钟）')

    # 4. 下载并解压 ZIP
    emit('log', '下载解析结果...')
    zip_resp = requests.get(zip_url, timeout=120)
    zip_resp.raise_for_status()
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        zf.extractall(out_dir)
    emit('log', 'MinerU Cloud API 处理完成')


# ══════════════════════════════════════════════════════
# 共用解析工具函数
# ══════════════════════════════════════════════════════

RE_SEC_PREFIX = re.compile(r'^([1-9]\d*(?:\.\d+)*)\s*(.*)')
_TRAIL = re.compile(r'[\u2026\u00b7\uff0e\uff0c.\s\uff08\uff3b（【(\uff1a:\u3001\uff09）】\uff3d]+$')

_SPECIALS = [
    ('附：条文说明',   '条文说明'),
    ('标准用词说明',   '标准用词说明'),
    ('本规范用词说明', '本规范用词说明'),
    ('引用标准名录',   '引用标准名录'),
    ('条文说明',       '条文说明'),
]


def _clean_title(t):
    return _TRAIL.sub('', t).strip()


def _find_page_num(text):
    m = re.search(r'[\uff08（(\[【]\s*[=＝]?\s*(\d{1,4})\s*[\uff09）)\]】]\s*$', text)
    if m:
        return m, int(m.group(1))
    m = re.search(r'(\d{1,4})\s*$', text)
    if m:
        return m, int(m.group(1))
    return None, None


def _parse_toc_line(line):
    line = line.strip()
    if not line:
        return None

    # 附录格式：允许 "附录 B"（有空格）和小写字母
    app_m = re.match(r'^附录\s*([A-Za-z])\s*(.*)', line)
    if app_m:
        sec  = f"附录{app_m.group(1).upper()}"
        rest = app_m.group(2)
        pm, page = _find_page_num(rest)
        if pm and 1 <= page <= 600:
            title = _clean_title(rest[:pm.start()])
            # 标题为空时用附录编号作为标题，避免漏掉附录条目
            return (1, sec, title or sec, page)

    # 特殊条目
    for kw, label in _SPECIALS:
        if line.startswith(kw):
            pm, page = _find_page_num(line[len(kw):])
            if pm and 1 <= page <= 600:
                return (1, label, "", page)

    # 数字编号章节
    m = RE_SEC_PREFIX.match(line)
    if not m:
        return None
    sec  = m.group(1)
    rest = m.group(2).strip()
    if not rest:
        return None
    pm, page = _find_page_num(rest)
    if not pm:
        if sec == '1':
            title = _clean_title(rest)
            if title:
                return (1, sec, title, 1)
        return None
    if page < 1 or page > 600:
        return None
    title = _clean_title(rest[:pm.start()])
    if not title:
        return None
    return (len(sec.split('.')), sec, title, page)


def _split_merged_entries(line):
    parts = re.split(
        r'(?<=[）)】\]])\s*'
        r'(?=[1-9]\d*(?:\.\d+)?\s*[\u4e00-\u9fff]'
        r'|附录\s*[A-Za-z]|附：|标准用词|本规范用词|引用标准)',
        line,
    )
    return [p.strip() for p in parts if p.strip()]


def _preprocess_lines(lines):
    merged, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if (re.match(r'^附录\s*[A-Za-z]', line)
                and not re.search(r'\d+\s*$', line)
                and not re.search(r'[）)】\]]\s*$', line)):
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt:
                    line = line + nxt
                    i += 1
        merged.append(line)
        i += 1
    result = []
    for line in merged:
        result.extend(_split_merged_entries(line))
    return result


def _load_mineru_outputs(mineru_dir):
    cl = glob.glob(os.path.join(mineru_dir, '**', '*content_list.json'), recursive=True)
    md = glob.glob(os.path.join(mineru_dir, '**', '*.md'), recursive=True)
    lines = []
    if cl:
        for f in cl:
            with open(f, encoding='utf-8') as fh:
                items = json.load(fh)
            for item in items:
                t = item.get('text', '').strip()
                if t:
                    lines.extend(t.splitlines())
    elif md:
        for f in md:
            with open(f, encoding='utf-8') as fh:
                lines.extend(fh.read().splitlines())
    return lines


# ══════════════════════════════════════════════════════
# Step 3+4: 解析 MinerU 输出，注入 TOC 书签
# ══════════════════════════════════════════════════════

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')


def _parse_toc_with_ai(all_lines, emit):
    """
    用 DeepSeek API 将 MinerU 输出解析为书签条目列表。
    返回 [(level, section, title, page), ...] 格式，与正则解析结果一致。
    """
    from openai import OpenAI

    api_key = DEEPSEEK_API_KEY
    if not api_key:
        raise RuntimeError('请设置 DEEPSEEK_API_KEY 环境变量后再使用 AI 解析功能')

    # 取前 300 行，避免 token 超限
    toc_text = '\n'.join(all_lines[:300])
    emit('log', f'发送 {len(toc_text)} 字符到 DeepSeek API...')

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    resp = client.chat.completions.create(
        model='deepseek-chat',
        max_tokens=4096,
        messages=[{
            'role': 'user',
            'content': (
                '以下是从中文PDF目录页OCR提取的文本，请解析为书签列表。\n\n'
                f'OCR文本：\n{toc_text}\n\n'
                '返回JSON数组，每项格式：\n'
                '{"level": 层级, "section": "章节编号", "title": "标题", "page": 页码}\n\n'
                '说明：\n'
                '- level 1=章级（如"1"、"2"、"附录A"），level 2=节级（如"1.1"、"2.3"）\n'
                '- section 例如 "1"、"2.3"、"附录A"、"条文说明"\n'
                '- title 只含标题文字，不含编号和页码\n'
                '- page 为目录中显示的书内页码（整数）\n'
                '- 只提取有明确页码的条目\n'
                '只返回JSON数组，不要任何其他文字或代码块标记。'
            ),
        }],
    )
    raw_json = resp.choices[0].message.content.strip()

    # 兼容模型有时会用 ```json ... ``` 包裹的情况
    if raw_json.startswith('```'):
        raw_json = re.sub(r'^```[a-z]*\n?', '', raw_json)
        raw_json = re.sub(r'\n?```$', '', raw_json)

    emit('log', 'DeepSeek 返回响应，解析 JSON...')
    entries = json.loads(raw_json)

    raw_entries = []
    for e in entries:
        try:
            level   = int(e['level'])
            section = str(e['section'])
            title   = str(e['title'])
            page    = int(e['page'])
            raw_entries.append((level, section, title, page))
            emit('log', f"  L{level}  {section:10s}  p={page:3d}  '{title[:40]}'")
        except (KeyError, ValueError, TypeError):
            continue

    emit('log', f'AI 共解析 {len(raw_entries)} 条目录条目')
    return raw_entries


def step3_parse_inject(pdf_path, mineru_dir, output_pdf, toc_scan_start, emit,
                       toc_page_indices=None, use_ai=False):
    """解析 MinerU 输出，注入 TOC 书签。返回 (offset, bookmark_count, clause_pdf_page)。"""
    if use_ai:
        emit('step_start', 'AI 智能解析目录中...', step=3, progress=45)
    else:
        emit('step_start', '解析目录并注入书签...', step=3, progress=45)

    all_lines = _load_mineru_outputs(mineru_dir)
    if not all_lines:
        raise RuntimeError(f'未找到 MinerU 输出文件！目录: {mineru_dir}')

    emit('log', f'加载 {len(all_lines)} 行 MinerU 输出')
    all_lines = _preprocess_lines(all_lines)

    if use_ai:
        raw_entries = _parse_toc_with_ai(all_lines, emit)
    else:
        raw_entries = []
        for line in all_lines:
            e = _parse_toc_line(line)
            if e:
                raw_entries.append(e)
                emit('log', f"  L{e[0]}  {e[1]:10s}  p={e[3]:3d}  '{e[2][:40]}'")
        emit('log', f'共解析 {len(raw_entries)} 条目录条目')
    if not raw_entries:
        emit('log', '⚠ 无法解析任何目录条目。MinerU 原始输出（前25行）：')
        for raw_l in all_lines[:25]:
            emit('log', f'  >> {repr(raw_l)}')
        raise RuntimeError('解析到 0 条目录，请检查上方日志中的 MinerU 输出格式')

    # 确定页码偏移（OCR 扫描正文找第一章）
    doc = fitz.open(pdf_path)
    total = len(doc)

    first_sec = next((e for e in raw_entries if e[1] == '1'), None)
    if first_sec is None:
        first_sec = raw_entries[0]
    book_page_1 = first_sec[3]
    sec_num_1   = first_sec[1]
    emit('log', f'目录显示：{sec_num_1} 章 → 书页码 {book_page_1}')

    def quick_ocr(page):
        """优先用内嵌文本（born-digital PDF），扫描版才走 Tesseract。"""
        text = page.get_text()
        if len(text.strip()) > 50:
            return text
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

    # 预扫描页面文本（每页只扫一次）
    emit('log', f'扫描正文页定位章节起始（PDF第{toc_scan_start+1}页起）...')
    page_texts = {}
    for i in range(toc_scan_start, min(toc_scan_start + 80, total)):
        page_texts[i] = quick_ocr(doc[i])

    # 多章节交叉投票确定 offset
    # 取前5个1级章节作为参考（数字编号）
    ref_entries = [e for e in raw_entries if e[0] == 1 and re.match(r'^\d+$', e[1])][:5]
    if not ref_entries:
        ref_entries = raw_entries[:3]

    offset_votes: dict = {}
    for ref_lvl, ref_sec, ref_title, ref_book_page in ref_entries:
        ref_pat = re.compile(r'^' + re.escape(ref_sec) + r'\s+\S')
        ref_sub = re.compile(r'^' + re.escape(ref_sec) + r'\.')
        for i, text in page_texts.items():
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for j, line in enumerate(lines[:15]):
                if not ref_pat.match(line):
                    continue
                following = lines[j+1 : j+6]
                has_subsec = any(ref_sub.match(fl) for fl in following)
                if following and not has_subsec and j >= 5:
                    continue
                cand = i - (ref_book_page - 1)
                offset_votes[cand] = offset_votes.get(cand, 0) + 1
                emit('log', f"  '{ref_sec}' 章在PDF第{i+1}页，书页码={ref_book_page}，候选offset={cand}")
                break

    if offset_votes:
        offset = max(offset_votes, key=offset_votes.get)
        emit('log', f'投票结果: {dict(sorted(offset_votes.items()))} → offset={offset}')
    else:
        offset = toc_scan_start - (book_page_1 - 1)
        emit('log', f'未找到章节起始页，估算 offset={offset}')

    # 构建书签
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
        if level > 2 or sec in seen:
            continue
        seen.add(sec)
        pdf_page_1idx = book_page - 1 + offset + 1
        if pdf_page_1idx < 1 or pdf_page_1idx > total:
            emit('log', f'  跳过越界: {sec} book_p={book_page} → pdf_p={pdf_page_1idx}')
            continue
        full_title = f"{sec}  {title}" if title else sec
        bookmarks.append([level, full_title, pdf_page_1idx])

    bookmarks = normalize_levels(bookmarks)

    # 在最前面插入"目录"书签，指向用户选定的第一个目录页
    if toc_page_indices:
        toc_pdf_page = min(toc_page_indices) + 1   # 0-indexed → 1-indexed
        if 1 <= toc_pdf_page <= total:
            bookmarks = [[1, '目录', toc_pdf_page]] + bookmarks

    emit('log', f'注入 {len(bookmarks)} 个书签')
    for b in bookmarks:
        emit('log', f"  L{b[0]}  p{b[2]:3d}  {b[1][:60]}")
    if len(bookmarks) == 0:
        emit('log', '⚠ 书签数为 0！所有条目可能均超出页码范围，请检查 offset 是否正确')

    # 找条文说明书签页码（用于后续交互）
    clause_pdf_page = next(
        (b[2] for b in bookmarks if '条文说明' in b[1]), None
    )

    doc.set_toc(bookmarks)
    doc.save(output_pdf)
    doc.close()
    emit('log', f'已保存: {output_pdf}')
    return offset, len(bookmarks), clause_pdf_page


# ══════════════════════════════════════════════════════
# Step 4: 提取条文说明目录页
# ══════════════════════════════════════════════════════

def step_clause_a(bm_pdf, orig_pdf, output_pdf, emit):
    """从条文说明起始页扫描目录页，保存为 output_pdf。返回 True 表示找到。"""
    emit('step_start', '提取条文说明目录页...', step=4, progress=60)

    def find_clause_start(pdf_path):
        doc = fitz.open(pdf_path)
        toc = doc.get_toc()
        doc.close()
        for item in toc:
            if '条文说明' in item[1]:
                return item[2] - 1  # 1-indexed → 0-indexed
        return None

    clause_0idx = find_clause_start(bm_pdf)
    if clause_0idx is None:
        clause_0idx = 211
        emit('log', f'书签中未找到条文说明，使用默认: PDF第{clause_0idx+1}页')
    else:
        emit('log', f'条文说明起始: PDF第{clause_0idx+1}页')

    doc = fitz.open(orig_pdf)
    total = len(doc)

    def ocr_page(page):
        """优先用内嵌文本，扫描版才走 Tesseract。"""
        text = page.get_text()
        if len(text.strip()) > 50:
            return text
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")

    def score_toc(text):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        score = 0
        if any('目次' in l or '目录' in l for l in lines):
            score += 3
        score += min(sum(1 for l in lines
                         if re.search(r'[\u4e00-\u9fff\w]\s*\d+\s*$', l)), 6)
        score += min(sum(1 for l in lines
                         if re.match(r'^[1-9]\d*(?:\.\d+)*[\s\u3000]', l)), 5)
        return score

    scan_start = clause_0idx
    emit('log', f'扫描 PDF第{scan_start+1}页 → 第{min(scan_start+15, total)}页...')

    candidates = []
    for i in range(scan_start, min(scan_start + 15, total)):
        text = ocr_page(doc[i])
        s = score_toc(text)
        emit('log', f'  PDF第{i+1}页: score={s}')
        if s >= 5:
            candidates.append(i)

    if not candidates:
        emit('log', '未检测到条文说明目录页，跳过条文说明书签注入')
        doc.close()
        return False

    cluster = [candidates[0]]
    for p in candidates[1:]:
        if p == cluster[-1] + 1:
            cluster.append(p)
        else:
            break

    pages = list(range(cluster[0], cluster[-1] + 1))
    if pages[-1] + 1 < total:
        pages.append(pages[-1] + 1)

    emit('log', f'提取条文说明目录页（PDF页码）: {[p+1 for p in pages]}')
    out = fitz.open()
    for p in pages:
        out.insert_pdf(doc, from_page=p, to_page=p)
    out.save(output_pdf)
    out.close()
    doc.close()
    emit('log', f'已保存: {output_pdf}（{len(pages)}页）')
    return True


# ══════════════════════════════════════════════════════
# Step 6: 注入条文说明子书签
# ══════════════════════════════════════════════════════

def step_clause_c(bm_pdf, mineru_dir, output_pdf, offset, emit):
    """解析条文说明目录 MinerU 输出，注入子书签。返回总书签数。"""
    emit('step_start', '注入条文说明子书签...', step=6, progress=90)

    all_lines = _load_mineru_outputs(mineru_dir)
    if not all_lines:
        raise RuntimeError(f'未找到条文说明 MinerU 输出！目录: {mineru_dir}')

    emit('log', f'加载 {len(all_lines)} 行 MinerU 输出')
    all_lines = _preprocess_lines(all_lines)

    raw = []
    for line in all_lines:
        e = _parse_toc_line(line)
        if e:
            raw.append(e)
            emit('log', f"  L{e[0]}  {e[1]:10s}  p={e[3]:3d}  '{e[2][:40]}'")

    emit('log', f'共解析 {len(raw)} 条')
    if not raw:
        raise RuntimeError('条文说明解析到 0 条！')

    doc   = fitz.open(bm_pdf)
    total = len(doc)
    toc   = doc.get_toc()

    clause_1idx = clause_idx = None
    for i, item in enumerate(toc):
        if '条文说明' in item[1]:
            clause_1idx = item[2]
            clause_idx  = i
            break

    if clause_1idx is None:
        raise RuntimeError('书签中未找到条文说明！')

    emit('log', f'条文说明: PDF第{clause_1idx}页，书签下标={clause_idx}')
    emit('log', f'使用页码偏移 offset={offset}')

    seen = set()
    sub  = []
    for level, sec, title, book_page in raw:
        if level > 2 or sec in seen:
            continue
        seen.add(sec)
        pdf_p = book_page - 1 + offset + 1   # 1-indexed
        if pdf_p < clause_1idx or pdf_p > total:
            emit('log', f'  跳过越界: {sec} book_p={book_page} → pdf_p={pdf_p}')
            continue
        full = f"{sec}  {title}" if title else sec
        sub.append([level + 1, full, pdf_p])

    emit('log', f'子书签数: {len(sub)}')
    for b in sub:
        emit('log', f"  L{b[0]}  p{b[2]:3d}  {b[1][:60]}")

    new_toc = toc[:clause_idx+1] + sub + toc[clause_idx+1:]
    doc.set_toc(new_toc)

    if os.path.abspath(output_pdf) == os.path.abspath(bm_pdf):
        tmp = output_pdf + '.tmp'
        doc.save(tmp)
        doc.close()
        os.replace(tmp, output_pdf)
    else:
        doc.save(output_pdf)
        doc.close()

    size_mb = os.path.getsize(output_pdf) / 1024 / 1024
    emit('log', f'完成！总书签: {len(new_toc)}，文件大小: {size_mb:.1f}MB')
    return len(new_toc)


# ══════════════════════════════════════════════════════
# 完整流水线入口
# ══════════════════════════════════════════════════════

def _save_pages_as_pdf(src_pdf, page_indices, out_pdf):
    """将指定页面（0-indexed）提取为独立 PDF。"""
    doc   = fitz.open(src_pdf)
    total = len(doc)
    out   = fitz.open()
    for i in sorted(set(p for p in page_indices if 0 <= p < total)):
        out.insert_pdf(doc, from_page=i, to_page=i)
    out.save(out_pdf)
    out.close()
    doc.close()


def run_pipeline(pdf_path, job_dir, emit, toc_pages, clause_event, clause_pages_holder, use_ai=False):
    """
    6 步完整流水线。
    toc_pages:            用户选定的主目录页列表（0-indexed）。
    clause_event:         threading.Event，step3 完成后等待用户确认条文说明。
    clause_pages_holder:  长度为 1 的列表，用于接收用户选定的条文说明目录页；
                          None 表示跳过。
    """
    toc_pdf       = os.path.join(job_dir, 'toc_only.pdf')
    toc_mineru    = os.path.join(job_dir, 'toc_mineru_out')
    toc_bm_pdf    = os.path.join(job_dir, 'toc_bm.pdf')
    clause_toc    = os.path.join(job_dir, 'clause_toc.pdf')
    clause_mineru = os.path.join(job_dir, 'clause_mineru_out')
    final_pdf     = os.path.join(job_dir, 'final.pdf')

    # Step 1: 提取用户选定的目录页
    toc_scan_start = extract_toc_pages(pdf_path, toc_pages, toc_pdf, emit)

    # Step 2: MinerU Cloud API OCR 目录页
    _run_mineru_api(toc_pdf, toc_mineru, emit, step_num=2, start_pct=15)

    # Step 3: 解析 MinerU 输出，注入主目录书签
    offset, toc_count, clause_pdf_page = step3_parse_inject(
        pdf_path, toc_mineru, toc_bm_pdf, toc_scan_start, emit,
        toc_page_indices=toc_pages, use_ai=use_ai)

    # Step 4: 询问用户是否添加条文说明子目录
    if clause_pdf_page is not None:
        # 通知前端展示条文说明目录页选择器（clause_page 为 0-indexed 起始展示页）
        emit('select_clause',
             f'主目录书签已注入（共 {toc_count} 个）。'
             f'条文说明在第 {clause_pdf_page} 页，是否添加子目录书签？',
             step=4, progress=60,
             clause_page=clause_pdf_page - 1)   # 转为 0-indexed
        clause_event.wait(timeout=600)           # 等待用户操作（最多 10 分钟）
        clause_pages = clause_pages_holder[0]
    else:
        emit('log', '未找到条文说明书签，跳过子目录注入')
        emit('step_start', '准备完成...', step=4, progress=60)
        clause_pages = None

    if clause_pages:
        # Step 5: MinerU OCR 条文说明目录
        emit('log', f'条文说明目录页（0-indexed）: {clause_pages}')
        _save_pages_as_pdf(pdf_path, clause_pages, clause_toc)
        _run_mineru_api(clause_toc, clause_mineru, emit, step_num=5, start_pct=65)

        # Step 6: 注入条文说明子书签
        try:
            total_bookmarks = step_clause_c(
                toc_bm_pdf, clause_mineru, final_pdf, offset, emit)
        except Exception as e:
            emit('log', f'⚠ 条文说明子书签注入失败（{e}），将以主目录书签完成')
            shutil.copy2(toc_bm_pdf, final_pdf)
            total_bookmarks = toc_count
            emit('step_start', '完成最后处理...', step=6, progress=90)
    else:
        shutil.copy2(toc_bm_pdf, final_pdf)
        total_bookmarks = toc_count
        emit('log', '跳过条文说明子目录，直接完成')
        emit('step_start', '完成最后处理...', step=6, progress=90)

    emit('done', f'完成！共注入 {total_bookmarks} 个书签', progress=100)
