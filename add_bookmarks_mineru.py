"""
MinerU + PyMuPDF 自动生成 PDF 目录书签
流程：
  1. 用 magic-pdf CLI 解析 PDF → 输出 content_list.json
  2. 从 content_list.json 提取 type=="title" 的条目（含页码）
  3. 按编号模式判断层级（1→L1, 1.1→L2, 1.1.1→L3）
  4. 写入书签
用法：python add_bookmarks_mineru.py <input.pdf> [output.pdf]
"""
import re
import sys
import os
import json
import subprocess
import shutil
from pathlib import Path
import fitz  # PyMuPDF

# ── 配置 ────────────────────────────────────────────────────
PYTHON = r"C:\Users\23920\AppData\Local\Programs\Python\Python312\python.exe"
MAGIC_PDF = r"C:\Users\23920\AppData\Local\Programs\Python\Python312\Scripts\magic-pdf.exe"

INPUT_PDF  = sys.argv[1] if len(sys.argv) >= 2 else "my_book2.pdf"
OUTPUT_PDF = sys.argv[2] if len(sys.argv) >= 3 else INPUT_PDF.replace(".pdf", "_with_bookmarks.pdf")

CN_NUMS = "一二三四五六七八九十百千"

# 层级模式（与 add_bookmarks.py 一致）
RE_L1  = re.compile(r"^[1-9]\d?\s+[^\d\s]")
RE_L2  = re.compile(r"^[1-9]\d?\.\d{1,2}\s+[^\d\s]")
RE_L3  = re.compile(r"^[1-9]\d?\.\d{1,2}\.\d{1,2}\s+[^\d\s]")
RE_CN1 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*[章篇卷部]\s*\S")
RE_CN2 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*节\s*\S")


def classify_heading(text: str):
    t = text.strip()
    if RE_L3.match(t): return 3
    if RE_L2.match(t): return 2
    if RE_L1.match(t) and len(t) <= 25:
        title_part = re.sub(r"^[1-9]\d?\s+", "", t)
        if re.search(r"[\u4e00-\u9fff]", title_part):
            return 1
    if RE_CN1.match(t): return 1
    if RE_CN2.match(t): return 2
    return None


def normalize_levels(toc: list) -> list:
    result, prev = [], 1
    for entry in toc:
        lvl = max(1, min(entry[0], prev + 1))
        result.append([lvl, entry[1], entry[2]])
        prev = lvl
    return result


def run_mineru(pdf_path: str, out_dir: str) -> Path:
    """调用 magic-pdf CLI 解析 PDF，返回 content_list.json 路径。"""
    pdf_stem = Path(pdf_path).stem
    env = os.environ.copy()
    env["MINERU_MODEL_SOURCE"] = "modelscope"

    print(f"正在用 MinerU 解析：{pdf_path}")
    print("（首次运行会加载模型，请稍候…）\n")

    result = subprocess.run(
        [MAGIC_PDF, "-p", pdf_path, "-o", out_dir, "-m", "auto"],
        capture_output=False,
        env=env,
        cwd=str(Path(pdf_path).parent)
    )
    if result.returncode != 0:
        raise RuntimeError(f"magic-pdf 退出码 {result.returncode}")

    # 查找输出的 content_list.json
    out_path = Path(out_dir)
    candidates = list(out_path.rglob("*content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"未找到 content_list.json，请检查 {out_dir}")
    return candidates[0]


def extract_bookmarks_from_content_list(json_path: Path) -> list:
    """
    从 content_list.json 提取标题书签。
    MinerU 的 content_list.json 结构：
      [{"type": "title"/"text"/..., "text": "...", "page_no": 0, ...}, ...]
    type=="title" 的条目由 MinerU 版式分析识别为标题（准确率高）。
    """
    with open(json_path, encoding="utf-8") as f:
        items = json.load(f)

    bookmarks = []
    seen = set()

    for item in items:
        item_type = item.get("type", "")
        text = item.get("text", "").strip()
        page_no = item.get("page_no", 0)  # 0-indexed

        if not text:
            continue

        # MinerU 识别为 title 的条目，直接按编号判断层级
        if item_type == "title":
            level = classify_heading(text)
            if level is None:
                # MinerU 认为是标题但不符合编号格式，暂按 L2 处理
                level = 2
            key = text[:80]
            if key not in seen:
                seen.add(key)
                bookmarks.append((level, text, page_no))

    return bookmarks


def main():
    # 1. 运行 MinerU
    out_dir = str(Path(INPUT_PDF).parent / "mineru_output")
    content_list_path = run_mineru(INPUT_PDF, out_dir)
    print(f"\nMinerU 输出：{content_list_path}")

    # 2. 提取书签
    bookmarks = extract_bookmarks_from_content_list(content_list_path)
    print(f"识别到 {len(bookmarks)} 个书签\n")

    if not bookmarks:
        print("未识别到任何书签。MinerU 未检测到标题，可能文档格式特殊。")
        return

    # 3. 预览
    print("--- 书签预览 ---")
    for lvl, title, pg in bookmarks:
        indent = "  " * (lvl - 1)
        print(f"  第{pg+1:>4}页  {indent}[L{lvl}] {title}")

    # 4. 写入书签
    print(f"\n正在写入书签到：{OUTPUT_PDF}")
    doc = fitz.open(INPUT_PDF)
    toc = normalize_levels([[lvl, t, pg + 1] for lvl, t, pg in bookmarks])
    doc.set_toc(toc)
    doc.save(OUTPUT_PDF)
    doc.close()
    print(f"完成！已保存：{OUTPUT_PDF}")


if __name__ == "__main__":
    main()
