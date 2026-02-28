"""
自动为 PDF 添加目录书签
核心策略：
  1. 字号必须比正文大至少 1.5pt（排除目录页、正文数字）
  2. 行文本必须匹配章节编号格式（要求编号后有真正的标题文字）
  3. 过滤明显的代码/数据行
层级：1级=单数字(1)  2级=两段(1.1)  3级=三段(1.1.1)  中文章节也支持
"""
import re
import sys
from collections import Counter
import fitz  # PyMuPDF

if len(sys.argv) >= 2:
    INPUT_PDF = sys.argv[1]
    OUTPUT_PDF = sys.argv[2] if len(sys.argv) >= 3 else INPUT_PDF.replace(".pdf", "_with_bookmarks.pdf")
else:
    INPUT_PDF  = "my_book.pdf"
    OUTPUT_PDF = "my_book_with_bookmarks.pdf"

CN_NUMS = "一二三四五六七八九十百千"

# 严格编号模式：编号后必须有「空白」再接非数字标题文字
# L1: "1 标题"  —— 单数字 + 至少一个空格 + 非数字字符
RE_L1 = re.compile(r"^\d+\s+[^\d\s]")
# L2: "1.1 标题" —— 两段数字 + 空格 + 非数字字符
RE_L2 = re.compile(r"^\d+\.\d+\s+[^\d\s]")
# L3: "1.1.1 标题" —— 三段数字 + 空格 + 非数字字符
RE_L3 = re.compile(r"^\d+\.\d+\.\d+\s+[^\d\s]")
# 中文章节
RE_CN1 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*[章篇卷部]\s*\S")
RE_CN2 = re.compile(r"^第\s*[" + CN_NUMS + r"\d]+\s*节\s*\S")

# 代码/数据行的特征词（不应出现在标题里）
CODE_WORDS = re.compile(r"\b(null|true|false|none|undefined|nan)\b", re.IGNORECASE)


def get_body_font_size(doc: fitz.Document) -> float:
    """统计全文最常见字号（=正文字号），用精确值（未四舍五入）。"""
    # 收集所有超过3字符的 span 字号，取最高频者
    from collections import Counter
    buckets = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if len(span.get("text", "").strip()) > 3:
                        # 精确到 0.1pt 做分桶
                        size = round(span.get("size", 0), 1)
                        if size > 0:
                            buckets[size] += 1
    if not buckets:
        return 10.0
    # 返回真实最大精确值（如 11.04 对应分桶 11.0，返回 11.04 偏大端）
    body_bucket = buckets.most_common(1)[0][0]
    return body_bucket  # 用分桶代表值


def is_valid_title(text: str) -> bool:
    """标题文字的合理性检查：必须含字母或汉字，不能是代码数据。"""
    # 含有字母或汉字
    if not re.search(r"[a-zA-Z\u4e00-\u9fff]", text):
        return False
    # 不含编程关键词
    if CODE_WORDS.search(text):
        return False
    return True


def classify_heading(text: str):
    """返回标题层级 (1/2/3)，或 None（不是标题）。"""
    t = text.strip()
    if RE_L3.match(t):
        return 3, t
    if RE_L2.match(t):
        return 2, t
    if RE_L1.match(t):
        return 1, t
    if RE_CN1.match(t):
        return 1, t
    if RE_CN2.match(t):
        return 2, t
    return None, None


def normalize_levels(toc: list) -> list:
    """修正层级跳跃（PyMuPDF 要求不能跳级）。"""
    result = []
    prev = 1
    for entry in toc:
        lvl = max(1, min(entry[0], prev + 1))
        result.append([lvl, entry[1], entry[2]])
        prev = lvl
    return result


def extract_bookmarks(doc: fitz.Document, body_size: float) -> list:
    # 字号必须比正文大至少 1.5pt 才算标题
    size_threshold = body_size + 1.5
    bookmarks = []
    seen = set()

    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text or len(line_text) > 100:
                    continue

                # ★ 字号过滤
                max_size = max(s.get("size", 0) for s in spans)
                if max_size < size_threshold:
                    continue

                # 编号格式匹配
                level, title = classify_heading(line_text)
                if level is None:
                    continue

                # 合理性检查
                if not is_valid_title(line_text):
                    continue

                # 全局去重（同一标题只保留第一次出现）
                key = line_text[:80]
                if key in seen:
                    continue
                seen.add(key)

                bookmarks.append((level, title, page_num))

    return bookmarks


def main():
    print(f"正在打开：{INPUT_PDF}")
    doc = fitz.open(INPUT_PDF)
    print(f"共 {len(doc)} 页")

    body_size = get_body_font_size(doc)
    threshold = body_size + 1.5
    print(f"正文字号 ≈ {body_size}pt，标题阈值 > {threshold}pt\n")

    bookmarks = extract_bookmarks(doc, body_size)
    print(f"识别到 {len(bookmarks)} 个书签\n")

    if not bookmarks:
        print("未识别到任何书签。")
        print("可能原因：PDF 为扫描图片版，或标题与正文字号相同。")
        doc.close()
        return

    print("--- 书签预览 ---")
    for lvl, title, pg in bookmarks:
        indent = "  " * (lvl - 1)
        print(f"  第{pg+1:>3}页  {indent}[L{lvl}] {title}")

    toc = normalize_levels([[lvl, t, pg + 1] for lvl, t, pg in bookmarks])
    doc.set_toc(toc)
    doc.save(OUTPUT_PDF)
    doc.close()
    print(f"\n完成！已保存：{OUTPUT_PDF}")


if __name__ == "__main__":
    main()
