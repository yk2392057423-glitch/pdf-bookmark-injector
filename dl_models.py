"""使用 modelscope 下载 MinerU 所需的模型文件"""
import os
os.environ["MINERU_MODEL_SOURCE"] = "modelscope"

from magic_pdf.config.make_content_config import DropMode, MakeMode

# 从 modelscope 下载
try:
    from modelscope import snapshot_download
    model_dir = snapshot_download("opendatalab/MinerU", local_dir="C:/Users/23920/magic-pdf-models")
    print(f"模型下载到：{model_dir}")
except ImportError:
    print("modelscope 未安装，尝试安装...")
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "modelscope",
                    "-i", "https://mirrors.aliyun.com/pypi/simple"], check=True)
    from modelscope import snapshot_download
    model_dir = snapshot_download("opendatalab/MinerU", local_dir="C:/Users/23920/magic-pdf-models")
    print(f"模型下载到：{model_dir}")
