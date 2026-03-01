"""
Flask 后端：PDF 书签注入工具网页版
v1.0 - 2026-02-28
路由:
  GET  /                          → index.html
  POST /upload                    → {job_id, total_pages}
  GET  /thumbnail/<job_id>/<n>    → PNG 缩略图（第 n 页，0-indexed）
  GET  /detect/<job_id>           → {status, pages}  (轮询目录页自动检测)
  POST /start/<job_id>            → body:{toc_pages:[...]}  启动流水线
  GET  /progress/<job_id>         → SSE 实时进度
  GET  /download/<job_id>         → 下载 final.pdf
"""
import os
import uuid
import time
import json
import shutil
import threading
from queue import Queue, Empty

from flask import (Flask, request, jsonify, send_file,
                   stream_with_context, Response, render_template)

import pipeline_core

app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# job 注册表
# {job_id: {
#   'queue':          Queue,
#   'status':         'uploaded'|'detecting'|'selecting'|'running'|'done'|'error',
#   'created':        float,
#   'total_pages':    int,
#   'detected_pages': None | [int, ...]
# }}
_jobs: dict = {}
_jobs_lock = threading.Lock()

JOB_TTL = 3600   # 1 小时后自动清理


# ── 后台清理线程 ────────────────────────────────────────────────────
def _cleanup_loop():
    while True:
        time.sleep(600)
        now = time.time()
        with _jobs_lock:
            expired = [jid for jid, j in _jobs.items()
                       if now - j['created'] > JOB_TTL]
        for jid in expired:
            job_dir = os.path.join(UPLOAD_DIR, jid)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
            with _jobs_lock:
                _jobs.pop(jid, None)


threading.Thread(target=_cleanup_loop, daemon=True, name='cleanup').start()


# ── 路由 ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': '请选择 PDF 文件'}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': '只支持 PDF 格式'}), 400

    job_id  = str(uuid.uuid4())
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir)

    pdf_path = os.path.join(job_dir, 'input.pdf')
    f.save(pdf_path)

    try:
        total_pages = pipeline_core.get_pdf_page_count(pdf_path)
    except Exception:
        total_pages = 0

    with _jobs_lock:
        _jobs[job_id] = {
            'queue':          Queue(),
            'status':         'uploaded',
            'created':        time.time(),
            'total_pages':    total_pages,
            'detected_pages': None,
        }

    return jsonify({'job_id': job_id, 'total_pages': total_pages})


@app.route('/thumbnail/<job_id>/<int:page_num>')
def thumbnail(job_id, page_num):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return '', 404

    pdf_path = os.path.join(UPLOAD_DIR, job_id, 'input.pdf')
    if not os.path.exists(pdf_path):
        return '', 404

    data = pipeline_core.render_page_thumbnail(pdf_path, page_num, width=130)
    if data is None:
        return '', 404

    return Response(data, content_type='image/png',
                    headers={'Cache-Control': 'public, max-age=3600'})


@app.route('/detect/<job_id>')
def detect(job_id):
    """
    轮询接口。首次调用启动后台 OCR 检测线程。
    返回:
      {'status': 'detecting'}           — 仍在检测中
      {'status': 'done', 'pages': [...]} — 检测完成，pages 为建议目录页（0-indexed）
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job 不存在'}), 404

    status = job['status']

    # 已经完成检测（或直接进入后续阶段）
    if status in ('selecting', 'running', 'done', 'error'):
        return jsonify({'status': 'done', 'pages': job.get('detected_pages') or []})

    # 检测正在进行
    if status == 'detecting':
        return jsonify({'status': 'detecting'})

    # status == 'uploaded'：启动检测线程
    job['status'] = 'detecting'
    pdf_path    = os.path.join(UPLOAD_DIR, job_id, 'input.pdf')
    total_pages = job['total_pages']

    def _run_detect():
        try:
            results = pipeline_core.detect_toc_pages(pdf_path)
            detected_raw = sorted(r['page'] for r in results if r['detected'])

            if detected_raw:
                # 取第一个连续簇
                cluster = [detected_raw[0]]
                for p in detected_raw[1:]:
                    if p <= cluster[-1] + 2:
                        cluster.append(p)
                    else:
                        break
                pages = list(range(cluster[0], cluster[-1] + 1))
            else:
                pages = list(range(3, min(8, total_pages)))
        except Exception:
            pages = list(range(3, min(8, total_pages)))

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]['detected_pages'] = pages
                _jobs[job_id]['status'] = 'selecting'

    threading.Thread(target=_run_detect, daemon=True,
                     name=f'detect-{job_id[:8]}').start()
    return jsonify({'status': 'detecting'})


@app.route('/start/<job_id>', methods=['POST'])
def start(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job 不存在'}), 404

    if job['status'] == 'running':
        return jsonify({'error': '已在运行中'}), 409

    body      = request.get_json(silent=True) or {}
    toc_pages = body.get('toc_pages')
    if not toc_pages or not isinstance(toc_pages, list) or len(toc_pages) == 0:
        return jsonify({'error': '请至少选择一个目录页'}), 400

    use_ai = bool(body.get('use_ai', False))

    job['status'] = 'running'
    job_dir  = os.path.join(UPLOAD_DIR, job_id)
    pdf_path = os.path.join(job_dir, 'input.pdf')

    # 条文说明交互机制
    clause_event          = threading.Event()
    clause_pages_holder   = [None]   # [0] 由 /start_clause 填入
    job['clause_event']         = clause_event
    job['clause_pages_holder']  = clause_pages_holder

    def _emit(type_, msg='', step=None, progress=None, **kwargs):
        event = {'type': type_, 'msg': msg}
        if step     is not None: event['step']     = step
        if progress is not None: event['progress'] = progress
        event.update(kwargs)
        job['queue'].put(event)

    def _run():
        try:
            pipeline_core.run_pipeline(
                pdf_path, job_dir, _emit, toc_pages,
                clause_event, clause_pages_holder, use_ai=use_ai)
            job['status'] = 'done'
        except Exception as exc:
            _emit('error', f'处理失败: {exc}')
            job['status'] = 'error'
        finally:
            job['queue'].put(None)   # sentinel

    threading.Thread(target=_run, daemon=True,
                     name=f'pipeline-{job_id[:8]}').start()
    return jsonify({'ok': True})


@app.route('/start_clause/<job_id>', methods=['POST'])
def start_clause(job_id):
    """
    用户确认条文说明目录页选择（或跳过）后调用。
    body: {clause_pages: [0-indexed 页码列表] | null}
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job 不存在'}), 404

    body         = request.get_json(silent=True) or {}
    clause_pages = body.get('clause_pages')   # None → 跳过

    holder = job.get('clause_pages_holder')
    event  = job.get('clause_event')
    if holder is None or event is None:
        return jsonify({'error': 'pipeline 尚未就绪'}), 409

    holder[0] = clause_pages   # 写入结果（None 或页码列表）
    event.set()                 # 唤醒流水线线程
    return jsonify({'ok': True})


@app.route('/progress/<job_id>')
def progress(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job 不存在'}), 404

    q = job['queue']

    def _generate():
        while True:
            try:
                event = q.get(timeout=30)
            except Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue

            if event is None:
                yield f"data: {json.dumps({'type': 'end'})}\n\n"
                break

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(_generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':        'keep-alive',
        },
    )


@app.route('/download/<job_id>')
def download(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job 不存在'}), 404

    final_pdf = os.path.join(UPLOAD_DIR, job_id, 'final.pdf')
    if not os.path.exists(final_pdf):
        return jsonify({'error': 'PDF 尚未生成'}), 404

    return send_file(
        final_pdf,
        as_attachment=True,
        download_name='result_with_bookmarks.pdf',
        mimetype='application/pdf',
    )


if __name__ == '__main__':
    print("启动 PDF 书签注入工具 Web 服务...")
    print("访问 http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
