import os
import re
import sys
import time
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pypdf import PdfReader

load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "chroma_db")

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
EMBED_BATCH_SIZE = 20

DOCS_ROOT = Path("Documentos")
COURSE_FOLDERS = {
    "cc": "Ciencia da Computacao",
    "es": "Eng. Software",
    "ep": "Eng. Producao",
    "ec": "Eng. Civil",
    "em": "Eng. Mecanica",
}

CC_FILES = [
    "cc_atividades-complementares_regulamento_2019.pdf",
    "cc_estagio_manual-normatizacao_2020.1.pdf",
    "cc_tcc_regulamento_2020.1.pdf",
    "cc_fluxograma_integralizacao-curricular_2018.pdf",
    "cc_ppc_2022.pdf",
]

ES_FILES = [
    "es_atividades-complementares_regulamento_2019.pdf",
    "es_ppc_2017.pdf",
    "es_fluxograma_ppc-completo.pdf",
    "es_estagio_manual-normatizacao_grade-2018_v2025.pdf",
    "es_estagio_manual-normatizacao_grade-2025_v2025.pdf",
    "es_estagio_fluxograma-matricula-etapas.pdf",
    "es_tcc_regulamento_2024.1.pdf",
    "es_tcc_fluxograma-tcc1-etapas.pdf",
    "es_tcc_fluxograma-tcc1-matricula.pdf",
    "es_tcc_fluxograma-tcc2-matricula-etapas.pdf",
]

EC_FILES = [
    "ec_atividades-complementares_manual_2023.1.pdf",
    "ec_estagio_manual-normatizacao_2023.1.pdf",
    "ec_extensao_manual-curricularizacao_2026.pdf",
    "ec_tcc_diretrizes-avaliacao-banca.pdf",
    "ec_tcc_regulamento_2018.pdf",
]

EP_FILES = [
    "ep_estagio_manual-normatizacao_2020.pdf",
    "ep_fluxograma_integralizacao-curricular_2019.2.pdf",
    "ep_ppc_2023.pdf",
    "ep_tcc_regulamento_2020.pdf",
]

COURSE_FILES = {
    "cc": CC_FILES,
    "es": ES_FILES,
    "ec": EC_FILES,
    "ep": EP_FILES,
}

client = genai.Client(api_key=GEMINI_API_KEY)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection("ufc_russas_docs")


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _retry_delay_seconds(error: APIError, fallback: float) -> float:
    body = getattr(error, "details", None) or {}
    if isinstance(body, dict):
        body = body.get("error", body)
    else:
        body = {}
    for detail in body.get("details", []):
        if detail.get("@type", "").endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            if raw.endswith("s"):
                try:
                    return float(raw[:-1]) + 1
                except ValueError:
                    pass
    return fallback


def embed_batch(texts: list[str], tries: int = 6) -> list[list[float]]:
    for exp in range(tries):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            return [e.values for e in response.embeddings]
        except APIError as e:
            if exp == tries - 1:
                raise
            delay = _retry_delay_seconds(e, fallback=2 ** exp)
            print(f"  cota momentaneamente excedida, esperando {delay:.1f}s...")
            time.sleep(delay)


def ingest_file(course: str, folder: Path, filename: str) -> None:
    chunks = chunk_text(extract_text(folder / filename))
    ids = [f"{course}:{filename}:{i}" for i in range(len(chunks))]

    existing = collection.get(ids=ids)
    if len(existing["ids"]) == len(ids):
        print(f"{filename}: já ingerido ({len(chunks)} chunks), pulando")
        return

    metadatas = [{"course": course, "filename": filename, "chunk_index": i} for i in range(len(chunks))]
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        embeddings = embed_batch(batch)
        collection.upsert(
            ids=ids[i : i + EMBED_BATCH_SIZE],
            embeddings=embeddings,
            documents=batch,
            metadatas=metadatas[i : i + EMBED_BATCH_SIZE],
        )
        print(f"  {filename}: {min(i + EMBED_BATCH_SIZE, len(chunks))}/{len(chunks)} chunks")

    print(f"{filename}: {len(chunks)} chunks ingeridos")


def ingest_course(course: str, filenames: list[str]) -> None:
    folder = DOCS_ROOT / COURSE_FOLDERS[course]
    for filename in filenames:
        ingest_file(course, folder, filename)


if __name__ == "__main__":
    course = sys.argv[1] if len(sys.argv) > 1 else "cc"
    ingest_course(course, COURSE_FILES[course])
