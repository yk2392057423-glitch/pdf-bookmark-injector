"""快速查看 my_book2.pdf 第1页图片，用英文 OCR 试识别"""
import fitz
import pytesseract
from PIL import Image
import io

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

doc = fitz.open("my_book2.pdf")
page = doc[0]

# 渲染为高分辨率图片
mat = fitz.Matrix(2, 2)  # 2x 缩放
pix = page.get_pixmap(matrix=mat)
img = Image.open(io.BytesIO(pix.tobytes("png")))

# 用英文先试一下
text = pytesseract.image_to_string(img, lang="eng", config="--psm 3")
print("=== 第1页（英文OCR试识别）===")
print(text[:800])
doc.close()
