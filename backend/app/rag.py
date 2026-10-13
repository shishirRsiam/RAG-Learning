"""
২. RETRIEVAL PIPELINE (প্রশ্নের উত্তর দেওয়া)

    Query -> Embedding -> Retriever (Vector DB সার্চ) -> Top-K Chunks
          -> Prompt (Chunks + Question) -> LLM -> Answer

এখানে LangChain এর "chain" ম্যাজিক ইচ্ছে করেই ব্যবহার করা হয়নি — প্রতিটা ধাপ আলাদা
ফাংশনে লেখা, যাতে কোন ধাপে কী হচ্ছে স্পষ্ট দেখা যায়।
"""

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
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ]
)


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
def generate(question: str, context: str) -> str:
    # timeout না দিলে মডেল ব্যস্ত থাকলে রিকোয়েস্ট অনন্তকাল ঝুলে থাকতে পারে
    llm = ChatGoogleGenerativeAI(model=config.CHAT_MODEL, timeout=120)
    messages = PROMPT.format_messages(context=context, question=question)
    response = llm.invoke(messages)
    # Gemini 3 মডেল content কে লিস্ট আকারে দিতে পারে; .text সবসময় শুধু টেক্সটটা দেয়।
    return response.text


def answer(question: str, k: int = config.TOP_K) -> dict:
    """পুরো RAG: retrieve -> context -> generate"""
    chunks = retrieve(question, k)
    if not chunks:
        return {
            "answer": "Vector DB খালি। আগে ডকুমেন্ট ingest করো।",
            "sources": [],
            "prompt": None,
        }

    context = build_context(chunks)
    return {
        "answer": generate(question, context),
        "sources": chunks,
        # শেখার জন্য: LLM আসলে কী prompt পেয়েছে সেটাও ফেরত দিই
        "prompt": PROMPT.format(context=context, question=question),
    }
