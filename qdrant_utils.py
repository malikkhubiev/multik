import os
import re
from utils import send_request
from typing import List
import httpx
from config import QDRANT_URL, QDRANT_API_KEY, VECTOR_SERVER, DEEPSEEK_API_KEY

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

# Асинхронные функции для Qdrant

HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

async def create_collection(collection_name: str) -> None:
    url = f"{QDRANT_URL}/collections/{collection_name}"
    payload = {
        "vectors": {"size": 384, "distance": "Cosine"}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, json=payload, headers=HEADERS)
        resp.raise_for_status()

async def upsert_points(collection_name: str, points: list) -> None:
    url = f"{QDRANT_URL}/collections/{collection_name}/points"
    payload = {"points": points}
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, json=payload, headers=HEADERS)
        resp.raise_for_status()

async def search_points(collection_name: str, query_vector: list, limit: int = 5) -> list:
    url = f"{QDRANT_URL}/collections/{collection_name}/points/search"
    payload = {"vector": query_vector, "limit": limit, "with_payload": True}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        return resp.json().get("result", [])

async def vectorize(text: str) -> List[float]:
    """Векторизация через сервер"""
    try:
        data = await send_request(
            f"{VECTOR_SERVER}/vectorize",
            data={"text": text},
            method="POST"
        )
        if 'vector' not in data:
            raise ValueError(f"Ключ 'vector' отсутствует в ответе сервера. Полученный ответ: {data}")
        dim = data.get('dim', len(data['vector']))
        return data["vector"], dim
    except Exception as e:
        raise ValueError(f"Ошибка при векторизации: {str(e)}") 