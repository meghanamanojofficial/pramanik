import pytesseract
from PIL import Image

img = Image.open("../demo_docs/genuine.jpg")
print(pytesseract.image_to_string(img))