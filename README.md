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

**第二步：配置 API Key**

本工具依赖以下云端 API，需提前申请：

| 服务 | 用途 | 申请地址 |
|------|------|----------|
| MinerU Cloud | PDF OCR 解析（必需） | https://mineru.net |
| DeepSeek | AI 智能解析目录（可选） | https://platform.deepseek.com |

复制 `.env.example` 为 `.env`，填入你的 Key：

```
cp .env.example .env
# 用文本编辑器打开 .env，填入对应的值
```

**第三步：双击 `启动.bat`**

脚本会自动读取 `.env`、安装 Python 依赖并打开浏览器。

> 如果 Tesseract 安装在非默认路径，在 `.env` 中额外设置：
> ```
> TESSERACT_CMD=D:\your\path\tesseract.exe
> ```

## 手动启动

```bash
# 加载环境变量（Windows CMD）
set /p MINERU_API_TOKEN=<.env
# 或直接 export（Git Bash）
export $(cat .env | xargs)

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
