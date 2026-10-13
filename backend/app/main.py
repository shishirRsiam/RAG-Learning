"""
FastAPI backend — পুরো RAG সিস্টেমকে HTTP API হিসেবে খুলে দেয়।

ব্রাউজারে http://localhost:8000/docs খুললে সব endpoint নিজে চালিয়ে দেখা যাবে (Swagger UI)।
"""

import json
import os
import threading

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import config, rag
from app.ingest import run_ingestion
from app.vectorstore import count_chunks, get_chroma_client

app = FastAPI(title="RAG Learning API", version="1.0")


@app.middleware("http")
async def utf8_json(request, call_next):
    """সব JSON উত্তরের header এ charset=utf-8 যোগ করি (error উত্তর সহ)।

    না বললে Windows PowerShell 5.1 উত্তরকে Latin-1 ধরে পড়ে, আর বাংলা লেখা ভেঙে যায়।
    """
    response = await call_next(request)
    if response.headers.get("content-type") == "application/json":
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


# একসাথে দুইবার ingest চললে collection নষ্ট হতে পারে, তাই lock
_ingest_lock = threading.Lock()


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["What is the annual leave policy?"])
    k: int = Field(config.TOP_K, ge=1, le=20, description="কয়টা চাঙ্ক retrieve করবো")


def upstream_error(e: Exception) -> HTTPException:
    """Gemini বা ChromaDB তে সমস্যা হলে শুধু "Internal Server Error" না দিয়ে আসল কারণ জানাই।

    502 (Bad Gateway) মানে: আমাদের সার্ভার ঠিক আছে, কিন্তু যার উপর নির্ভর করে (upstream) সে ব্যর্থ হয়েছে।
    """
    return HTTPException(502, f"{type(e).__name__}: {e}")


@app.get("/health")
def health():
    """API আর ChromaDB দুটোই চলছে কিনা।"""
    try:
        get_chroma_client().heartbeat()
        chroma = "ok"
    except Exception as e:
        chroma = f"error: {e}"
    return {"api": "ok", "chromadb": chroma}


@app.get("/stats")
def stats():
    try:
        chunks = count_chunks()
    except Exception as e:
        raise upstream_error(e)
    return {
        "collection": config.COLLECTION_NAME,
        "chunks": chunks,
        "files": list_documents(),
        "chat_model": config.CHAT_MODEL,
        "embedding_model": config.EMBEDDING_MODEL,
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
    }


@app.get("/documents")
def list_documents() -> list[str]:
    """docs ফোল্ডারে কোন কোন ফাইল আছে (এখনো ingest না হলেও)।"""
    found = []
    for root, _, files in os.walk(config.DOCS_DIR):
        for f in files:
            if os.path.splitext(f)[1].lower() in config.SUPPORTED_EXTENSIONS:
                found.append(os.path.relpath(os.path.join(root, f), config.DOCS_DIR))
    return sorted(found)


@app.post("/upload")
def upload(files: list[UploadFile]):
    """ফাইল docs ফোল্ডারে সেভ করে। এরপর /ingest কল করলে Vector DB তে যাবে।"""
    # basename: "../../etc/x.pdf" এর মতো নাম দিয়ে docs ফোল্ডারের বাইরে লেখা আটকাই
    names = [os.path.basename(f.filename or "") for f in files]

    # আগে সব নাম চেক, তারপর সেভ — যাতে একটা ভুল ফাইলের জন্য অর্ধেক সেভ হয়ে না থাকে
    bad = [n for n in names if os.path.splitext(n)[1].lower() not in config.SUPPORTED_EXTENSIONS]
    if bad:
        raise HTTPException(400, f"সাপোর্টেড না: {bad}। শুধু: {sorted(config.SUPPORTED_EXTENSIONS)}")

    for f, name in zip(files, names):
        with open(os.path.join(config.DOCS_DIR, name), "wb") as out:
            out.write(f.file.read())
    return {"saved": names}


@app.post("/ingest")
def ingest():
    """docs ফোল্ডার থেকে পুরো knowledge-base নতুন করে বানায়।"""
    if not _ingest_lock.acquire(blocking=False):
        raise HTTPException(409, "আরেকটা ingestion এখন চলছে, একটু পরে চেষ্টা করো।")
    try:
        return run_ingestion()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise upstream_error(e)
    finally:
        _ingest_lock.release()


@app.post("/search")
def search(req: QuestionRequest):
    """শুধু Retrieval — LLM ছাড়া। দেখার জন্য যে retriever কোন চাঙ্কগুলো আনছে।"""
    try:
        return {"question": req.question, "results": rag.retrieve(req.question, req.k)}
    except Exception as e:
        raise upstream_error(e)


@app.post("/ask")
def ask(req: QuestionRequest):
    """পুরো RAG — retrieve করে LLM দিয়ে উত্তর বানায়।"""
    try:
        return {"question": req.question, **rag.answer(req.question, req.k)}
    except Exception as e:
        raise upstream_error(e)


@app.post("/ask/stream")
def ask_stream(req: QuestionRequest):
    """পুরো RAG, কিন্তু উত্তর টাইপ হতে হতে আসে (Server-Sent Events)।

    রেসপন্স একটা লম্বা টেক্সট স্ট্রিম, যেখানে প্রতিটা event এরকম:
        event: token
        data: {"text": "..."}
        <ফাঁকা লাইন>
    web UI (frontend/public/app.js) এটা পড়ে পড়ে স্ক্রিনে বসায়।
    """

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def events():
        try:
            for event, data in rag.answer_stream(req.question, req.k):
                yield sse(event, data)
        except Exception as e:
            # stream শুরু হয়ে যাওয়ার পর আর HTTP status বদলানো যায় না, তাই error ও একটা event
            yield sse("error", {"message": str(e)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # proxy (nginx) যেন টুকরোগুলো জমিয়ে না রেখে সাথে সাথে পাঠায়
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
