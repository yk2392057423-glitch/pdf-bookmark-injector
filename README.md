# PDF Bookmark Injector

自动为中文规范/标准 PDF 注入书签的 Web 工具。
通过 MinerU Cloud API 解析目录页，支持主目录和条文说明双层书签。

> 本功能适用于 PDF 规范生成书签目录。

## 功能

- 上传 PDF，自动扫描前 25 页，标记目录页候选
- 用户确认目录页后，调用 MinerU Cloud API 进行 OCR
- 自动解析章节编号，注入多级书签
- 支持条文说明子目录书签（二次 OCR + 注入）
- 实时进度日志（SSE 流式推送）

## 快速开始（Windows）

**第一步：安装前置软件（一次性）**

| 软件 | 下载地址 | 备注 |
|------|----------|------|
| Python 3.10+ | https://www.python.org/downloads/ | 安装时勾选 "Add Python to PATH" |
| Tesseract OCR | https://github.com/UB-Mannheim/tesseract/wiki | 安装时勾选 chi_sim 中文语言包 |

**第二步：双击 `启动.bat`**

脚本会自动安装 Python 依赖并打开浏览器，无需其他操作。

> 如果 Tesseract 安装在非默认路径，启动前设置环境变量：
> ```
> set TESSERACT_CMD=D:\your\path\tesseract.exe
> ```

## 手动启动

```bash
pip install -r requirements.txt
python webapp/app.py
```

浏览器访问 http://localhost:5000

## 项目结构

```
pdf-bookmark-injector/
├── README.md
├── requirements.txt
├── .env.example
└── webapp/
    ├── app.py               # Flask 后端
    ├── pipeline_core.py     # 6步流水线核心逻辑
    └── templates/
        └── index.html       # 单页 UI
```
