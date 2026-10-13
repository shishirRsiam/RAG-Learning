"""
১. INGESTION PIPELINE (Knowledge-base তৈরি)

    Source Documents -> Chunking -> Embedding -> Vector DB

এই ফাইল দুইভাবে চালানো যায়:
  - কমান্ড লাইন থেকে:   docker compose run --rm ingest
  - API থেকে:            POST /ingest  (UI এর "Ingest" বাটন এটাই কল করে)

প্রতিবার ingest করলে পুরনো collection মুছে নতুন করে বানানো হয় (full rebuild)।
এতে কোনো ফাইল মুছে দিলে বা বদলালে তার পুরনো চাঙ্ক DB তে থেকে যায় না।
"""

import os
import time

import docx2txt
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app import config
from app.vectorstore import get_chroma_client, get_vectorstore


# ---------------------------------------------------------------------------
# ধাপ ১: Source Documents লোড করা
# ---------------------------------------------------------------------------
def load_file(path: str) -> list[Document]:
    """একটা ফাইল থেকে টেক্সট বের করে Document বানায়।

    Document = টেক্সট (page_content) + তার সম্পর্কে তথ্য (metadata)।
    PDF এর প্রতিটা পেজ আলাদা Document হয়, যাতে উত্তরে পেজ নম্বর দেখানো যায়।
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        pages = PdfReader(path).pages
        return [
            Document(page_content=page.extract_text() or "", metadata={"page": i})
            for i, page in enumerate(pages)
        ]
    if ext in (".txt", ".md"):
        with open(path, encoding="utf-8") as f:
            return [Document(page_content=f.read())]
    if ext == ".docx":
        return [Document(page_content=docx2txt.process(path))]
    return []


def load_documents(docs_dir: str = config.DOCS_DIR) -> list[Document]:
    """docs ফোল্ডারের সব সাপোর্টেড ফাইল পড়ে Document লিস্ট বানায়।"""
    documents: list[Document] = []

    for root, _, files in os.walk(docs_dir):
        for file in sorted(files):
            path = os.path.join(root, file)
            if os.path.splitext(file)[1].lower() not in config.SUPPORTED_EXTENSIONS:
                continue

            try:
                docs = load_file(path)
            except Exception as e:
                print(f"  [skip] {file}: {e}")
                continue

            # পুরো container path (/app/docs/x.pdf) না রেখে শুধু ফাইলের নাম রাখি,
            # যাতে উত্তরে সুন্দরভাবে "কোন ফাইল থেকে এসেছে" দেখানো যায়।
            for d in docs:
                d.metadata["source"] = os.path.relpath(path, docs_dir)

            documents.extend(docs)
            print(f"  [loaded] {file} ({len(docs)} page/document)")

    return documents


# ---------------------------------------------------------------------------
# ধাপ ২: Chunking
# ---------------------------------------------------------------------------
def split_documents(documents: list[Document]) -> list[Document]:
    """বড় ডকুমেন্টকে ছোট ছোট টুকরায় (chunk) ভাঙে।

    RecursiveCharacterTextSplitter প্রথমে প্যারাগ্রাফ (\\n\\n) দিয়ে ভাঙার চেষ্টা করে,
    না হলে লাইন, তারপর শব্দ — তাই যতটা সম্ভব অর্থ ঠিক রেখে কাটে।
    chunk_overlap রাখা হয় যাতে কোনো বাক্য দুই চাঙ্কের মাঝখানে কেটে গেলেও context হারায় না।
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    # প্রতিটা চাঙ্কের একটা নম্বর রাখি — UI তে দেখতে সুবিধা হয়।
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i

    return chunks


# ---------------------------------------------------------------------------
# ধাপ ৩ + ৪: Embedding তৈরি করে Vector DB তে রাখা
# ---------------------------------------------------------------------------
def store_chunks(chunks: list[Document]) -> None:
    client = get_chroma_client()

    # পুরনো collection মুছে ফেলি (প্রথমবার না থাকলে error আসবে, সেটা ইগনোর)।
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:
        pass

    vectorstore = get_vectorstore(client)

    # add_documents() ভেতরে ভেতরে দুটো কাজ করে:
    #   (ক) প্রতিটা চাঙ্কের টেক্সট Gemini embedding API তে পাঠিয়ে vector আনে
    #   (খ) টেক্সট + vector + metadata একসাথে ChromaDB তে সেভ করে
    # ব্যাচে পাঠাই যাতে API এর rate limit এ না আটকাই।
    batch_size = config.EMBED_BATCH_SIZE
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        _add_with_retry(vectorstore, batch)
        print(f"  [embedded] {min(start + batch_size, len(chunks))}/{len(chunks)} chunks")


def _add_with_retry(vectorstore, batch: list[Document], attempts: int = 5) -> None:
    """Free tier এ rate limit (429) খুব কমন — একটু অপেক্ষা করে আবার চেষ্টা করি।"""
    for attempt in range(1, attempts + 1):
        try:
            vectorstore.add_documents(batch)
            return
        except Exception as e:
            msg = str(e)
            retryable = any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if not retryable or attempt == attempts:
                raise
            wait = 15 * attempt
            print(f"  [rate limit] {wait} সেকেন্ড অপেক্ষা করে আবার চেষ্টা ({attempt}/{attempts})...")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# পুরো পাইপলাইন একসাথে
# ---------------------------------------------------------------------------
def run_ingestion() -> dict:
    print(f"--- Ingestion শুরু: {config.DOCS_DIR} ---")

    documents = load_documents()
    if not documents:
        raise ValueError(
            f"'{config.DOCS_DIR}' ফোল্ডারে কোনো সাপোর্টেড ফাইল নেই "
            f"({', '.join(sorted(config.SUPPORTED_EXTENSIONS))})।"
        )

    chunks = split_documents(documents)
    if not chunks:
        raise ValueError("ফাইলগুলো থেকে কোনো টেক্সট পাওয়া যায়নি (স্ক্যান করা PDF হলে টেক্সট থাকে না)।")

    print(f"  মোট page/document: {len(documents)}, মোট chunk: {len(chunks)}")
    store_chunks(chunks)

    files = sorted({d.metadata["source"] for d in documents})
    print(f"--- Ingestion শেষ: {len(files)} ফাইল, {len(chunks)} chunk ---")
    return {"files": files, "documents": len(documents), "chunks": len(chunks)}


if __name__ == "__main__":
    run_ingestion()
