# PDF Bookmark Injector

自动为中文规范/标准 PDF 注入书签的 Web 工具。
通过 MinerU Cloud API 解析目录页，支持主目录和条文说明双层书签。

## 功能

- 上传 PDF，自动扫描前 25 页，标记目录页候选
- 用户确认目录页后，调用 MinerU Cloud API 进行 OCR
- 自动解析章节编号，注入多级书签
- 支持条文说明子目录书签（二次 OCR + 注入）
- 实时进度日志（SSE 流式推送）

## 依赖安装

```bash
pip install -r requirements.txt
```

> **Tesseract OCR** 需单独安装：https://github.com/UB-Mannheim/tesseract/wiki

## 环境变量配置

复制 `.env.example` 为 `.env`，填写以下变量：

| 变量 | 说明 |
|------|------|
| `MINERU_API_TOKEN` | MinerU Cloud API Token，从 https://mineru.net/apiManage/token 获取 |
| `TESSERACT_CMD` | tesseract.exe 完整路径 |
| `TESSDATA_PREFIX` | tessdata 目录路径（含 chi_sim.traineddata） |

## 启动

```bash
# 设置环境变量后启动
set MINERU_API_TOKEN=your_token_here
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
