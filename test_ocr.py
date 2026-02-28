"""快速测试：OCR 前5页，看识别效果"""
import fitz, pytesseract, io
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR = r"D:\claudecode_test\01pdf\tessdata"
import os; os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
DPI_SCALE = 150 / 72

doc = fitz.open("my_book2.pdf")
for pg in range(min(5, len(doc))):
    page = doc[pg]
    mat = fitz.Matrix(DPI_SCALE, DPI_SCALE)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img, lang="chi_sim+eng",
        config="--psm 3")
    print(f"\n====== 第{pg+1}页 ======")
    for line in text.splitlines():
        line = line.strip()
        if line:
            print(f"  {line}")
doc.close()
