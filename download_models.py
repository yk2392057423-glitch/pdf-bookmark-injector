import os
os.environ["MINERU_MODEL_SOURCE"] = "modelscope"

print("正在加载 MinerU 模型（首次需下载，请稍候）...")
from magic_pdf.model.doc_analyze_by_custom_model import ModelSingleton
m = ModelSingleton()
print("模型加载完成！")
