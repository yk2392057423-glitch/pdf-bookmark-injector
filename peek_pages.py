import fitz, io, os
import pytesseract
from PIL import Image

os.environ["TESSDATA_PREFIX"] = r"D:\claudecode_test\01pdf\tessdata"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

doc = fitz.open(r"D:\claudecode_test\01pdf\my_book3.pdf")
for idx in [113, 114, 115]:   # PDF 第114、115、116页（0-indexed）
    page = doc[idx]
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    print(f"=== PDF第{idx+1}页（前15行）===")
    for l in lines[:15]:
        print(f"  {l}")
