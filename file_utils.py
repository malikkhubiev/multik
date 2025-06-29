import os
import re
from typing import List

def safe_read_file(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="ignore")

def extract_text_from_file(filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".txt":
        return safe_read_file(content)
    elif ext == ".docx":
        from io import BytesIO
        from docx import Document
        doc = Document(BytesIO(content))
        return "\n".join([p.text for p in doc.paragraphs])
    elif ext == ".pdf":
        from io import BytesIO
        import PyPDF2
        reader = PyPDF2.PdfReader(BytesIO(content))
        text = []
        for page in reader.pages:
            text.append(page.extract_text() or "")
        return "\n".join(text)
    else:
        raise ValueError("Неподдерживаемый формат файла. Поддерживаются: .txt, .docx, .pdf")

def extract_assertions(text: str) -> list:
    """Простая функция: каждое предложение — отдельное утверждение."""
    # Разделяем по точкам, восклицательным и вопросительным знакам
    sentences = re.split(r'[.!?]\s+', text.strip())
    # Убираем пустые строки и пробелы
    return [s.strip() for s in sentences if s.strip()] 