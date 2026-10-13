"""
Vector DB আর Embedding মডেলের সাথে কানেকশন।

Ingestion আর Retrieval — দুই পাইপলাইনই এই ফাইল থেকে একই embedding মডেল আর
একই collection নেয়। এটা খুব জরুরি: যে মডেল দিয়ে ডকুমেন্ট এম্বেড করা হয়েছে,
প্রশ্নও ঠিক সেই মডেল দিয়েই এম্বেড করতে হবে। নাহলে vector গুলো একই "ভাষায়" থাকবে না
(এমনকি dimension-ও না মিলতে পারে) আর সার্চ ভুল রেজাল্ট দেবে।
"""

import chromadb
from chromadb.api import ClientAPI
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app import config


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    # টেক্সট -> সংখ্যার লিস্ট (vector)। gemini-embedding-001 প্রতিটা টেক্সটের জন্য
    # 3072টা সংখ্যার একটা vector দেয়।
    return GoogleGenerativeAIEmbeddings(model=config.EMBEDDING_MODEL)


def get_chroma_client() -> ClientAPI:
    # ChromaDB আলাদা container এ সার্ভার হিসেবে চলছে, তাই HTTP দিয়ে কানেক্ট করি।
    return chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)


def get_vectorstore(client: ClientAPI | None = None) -> Chroma:
    return Chroma(
        client=client or get_chroma_client(),
        collection_name=config.COLLECTION_NAME,
        embedding_function=get_embeddings(),
        # cosine distance: 0 মানে একদম একই দিকে, যত বড় তত দূরে।
        collection_metadata={"hnsw:space": "cosine"},
    )


def count_chunks() -> int:
    """Vector DB তে এখন কয়টা চাঙ্ক আছে (collection না থাকলে 0)।"""
    client = get_chroma_client()
    try:
        return client.get_collection(config.COLLECTION_NAME).count()
    except Exception:
        return 0
