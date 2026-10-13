"""
২. RETRIEVAL PIPELINE (প্রশ্নের উত্তর দেওয়া)

    Query -> Embedding -> Retriever (Vector DB সার্চ) -> Top-K Chunks
          -> Prompt (Chunks + Question) -> LLM -> Answer

এখানে LangChain এর "chain" ম্যাজিক ইচ্ছে করেই ব্যবহার করা হয়নি — প্রতিটা ধাপ আলাদা
ফাংশনে লেখা, যাতে কোন ধাপে কী হচ্ছে স্পষ্ট দেখা যায়।
"""

import time

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from app import config
from app.vectorstore import get_vectorstore

# system = নিয়মকানুন (সব প্রশ্নে একই), human = এই প্রশ্নের context + প্রশ্ন।
# context কে system এ রাখলে ছোট মডেল প্রায়ই context এর ভাষায় (যেমন বাংলা) উত্তর দিয়ে ফেলে।
PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful assistant that answers questions using ONLY the provided context.\n"
            "- Reply in the same language as the question (an English question gets an English answer).\n"
            "- Cite the sources you used like [1], [2] (the numbers of the context blocks).\n"
            "- If the context does not contain the answer, just say that you don't know based on "
            "the given documents. Do not cite anything and never make things up.",
        ),
        # উত্তরের ভাষা মডেলের উপর না ছেড়ে কোডে ঠিক করে প্রশ্নের ঠিক পরে বলে দিই —
        # নাহলে context এ বাংলা চাঙ্ক থাকলে ছোট মডেল ইংরেজি প্রশ্নেরও বাংলায় উত্তর দেয়।
        ("human", "Context:\n{context}\n\nQuestion: {question}\n\nAnswer in {language}."),
    ]
)


def detect_language(text: str) -> str:
    """প্রশ্নে একটাও বাংলা অক্ষর (Unicode U+0980–U+09FF) থাকলে Bengali, নাহলে English।"""
    return "Bengali" if any("ঀ" <= ch <= "৿" for ch in text) else "English"


def prompt_vars(question: str, context: str) -> dict:
    return {"context": context, "question": question, "language": detect_language(question)}


# ---------------------------------------------------------------------------
# ধাপ ১ + ২: প্রশ্ন এম্বেড করে Vector DB থেকে সবচেয়ে কাছের চাঙ্কগুলো আনা
# ---------------------------------------------------------------------------
def retrieve(question: str, k: int = config.TOP_K) -> list[dict]:
    vectorstore = get_vectorstore()

    # similarity_search_with_score() ভেতরে:
    #   (ক) প্রশ্নটাকে একই embedding মডেল দিয়ে vector বানায়
    #   (খ) ChromaDB তে ঐ vector এর সবচেয়ে কাছের k টা চাঙ্ক খোঁজে
    # score এখানে cosine distance — যত ছোট, তত বেশি মিল।
    results: list[tuple[Document, float]] = vectorstore.similarity_search_with_score(question, k=k)

    return [
        {
            "source": doc.metadata.get("source", "unknown"),
            # load_file() এ পেজ 0 থেকে গোনা, মানুষের জন্য +1 করে দেখাই
            "page": doc.metadata["page"] + 1 if "page" in doc.metadata else None,
            "chunk_id": doc.metadata.get("chunk_id"),
            # distance (0..2) কে similarity (1..-1) তে বদলাই, যাতে "বড় = ভালো" হয়
            "similarity": round(1 - distance, 4),
            "content": doc.page_content,
        }
        for doc, distance in results
    ]


# ---------------------------------------------------------------------------
# ধাপ ৩: চাঙ্কগুলো দিয়ে LLM এর জন্য context বানানো
# ---------------------------------------------------------------------------
def build_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        where = c["source"] + (f", page {c['page']}" if c["page"] else "")
        blocks.append(f"[{i}] ({where})\n{c['content']}")
    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# ধাপ ৪: Prompt + LLM -> Answer
# ---------------------------------------------------------------------------
def get_llm() -> ChatGoogleGenerativeAI:
    # timeout না দিলে মডেল ব্যস্ত থাকলে রিকোয়েস্ট অনন্তকাল ঝুলে থাকতে পারে
    return ChatGoogleGenerativeAI(model=config.CHAT_MODEL, timeout=120)


def generate(question: str, context: str) -> str:
    messages = PROMPT.format_messages(**prompt_vars(question, context))
    response = get_llm().invoke(messages)
    # Gemini 3 মডেল content কে লিস্ট আকারে দিতে পারে; .text সবসময় শুধু টেক্সটটা দেয়।
    return response.text


EMPTY_DB_MESSAGE = "Vector DB খালি। আগে ডকুমেন্ট ingest করো।"


def answer(question: str, k: int = config.TOP_K) -> dict:
    """পুরো RAG: retrieve -> context -> generate"""
    chunks = retrieve(question, k)
    if not chunks:
        return {"answer": EMPTY_DB_MESSAGE, "sources": [], "prompt": None}

    context = build_context(chunks)
    return {
        "answer": generate(question, context),
        "sources": chunks,
        # শেখার জন্য: LLM আসলে কী prompt পেয়েছে সেটাও ফেরত দিই
        "prompt": PROMPT.format(**prompt_vars(question, context)),
    }


def answer_stream(question: str, k: int = config.TOP_K):
    """answer() এর মতোই, কিন্তু উত্তর একবারে না দিয়ে টুকরো টুকরো (event) আকারে দেয়।

    ChatGPT এর মতো "টাইপ হতে হতে" উত্তর দেখানোর জন্য। প্রতিটা yield হলো (event_name, data):
      ("sources", {...})  -> retrieval শেষ, কোন চাঙ্ক পাওয়া গেল
      ("token",   {...})  -> LLM এর উত্তরের পরের টুকরো
      ("done",    {...})  -> শেষ, সাথে কোন ধাপে কত সময় লাগল
    """
    start = time.perf_counter()
    chunks = retrieve(question, k)
    retrieval_ms = round((time.perf_counter() - start) * 1000)

    if not chunks:
        yield "sources", {"sources": [], "prompt": None, "retrieval_ms": retrieval_ms}
        yield "token", {"text": EMPTY_DB_MESSAGE}
        yield "done", {"retrieval_ms": retrieval_ms, "generation_ms": 0}
        return

    context = build_context(chunks)
    yield "sources", {
        "sources": chunks,
        "prompt": PROMPT.format(**prompt_vars(question, context)),
        "retrieval_ms": retrieval_ms,
    }

    start = time.perf_counter()
    # invoke() পুরো উত্তর শেষ হলে একবারে দেয়; stream() যত লেখা হয় তত টুকরো দিতে থাকে
    for piece in get_llm().stream(PROMPT.format_messages(**prompt_vars(question, context))):
        if piece.text:
            yield "token", {"text": piece.text}

    yield "done", {
        "retrieval_ms": retrieval_ms,
        "generation_ms": round((time.perf_counter() - start) * 1000),
    }
