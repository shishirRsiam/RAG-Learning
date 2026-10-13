"""
Vector DB এর ভেতরে আসলে কী আছে, সেটা নিজের চোখে দেখার টুল।

    docker compose exec api python -m app.inspect_db                  # প্রথম ৩টা চাঙ্ক দেখাও
    docker compose exec api python -m app.inspect_db "তোমার প্রশ্ন"     # নিজে হাতে similarity হিসাব

দ্বিতীয়টা দেখায় যে "retriever" আসলে কোনো জাদু না — প্রশ্নের vector আর প্রতিটা চাঙ্কের vector
এর মধ্যে cosine similarity হিসাব করে সবচেয়ে বড়গুলো নেওয়া। এখানকার সংখ্যাগুলো UI এর
Retrieval Playground এর similarity এর সাথে মিলিয়ে দেখো।
"""

import sys

import numpy as np

from app import config
from app.vectorstore import get_chroma_client, get_embeddings


def show_chunks(n: int = 3) -> None:
    collection = get_chroma_client().get_collection(config.COLLECTION_NAME)
    print(f"Collection '{collection.name}' এ মোট {collection.count()} টা চাঙ্ক। প্রথম {n} টা:\n")

    data = collection.get(limit=n, include=["documents", "metadatas", "embeddings"])
    for id_, text, meta, vector in zip(data["ids"], data["documents"], data["metadatas"], data["embeddings"]):
        print(f"id       : {id_}")
        print(f"metadata : {meta}")
        print(f"text     : {text[:150]!r}...")
        print(f"vector   : {len(vector)} টা সংখ্যা -> [{', '.join(f'{x:.4f}' for x in vector[:5])}, ...]\n")


def similarity_by_hand(question: str, top: int = 5) -> None:
    collection = get_chroma_client().get_collection(config.COLLECTION_NAME)
    data = collection.get(include=["documents", "metadatas", "embeddings"])

    q = np.array(get_embeddings().embed_query(question))  # প্রশ্ন -> vector
    chunks = np.array(data["embeddings"])  # সব চাঙ্কের vector (rows)

    # cosine similarity = (a · b) / (|a| * |b|)
    sims = chunks @ q / (np.linalg.norm(chunks, axis=1) * np.linalg.norm(q))

    print(f"প্রশ্ন: {question!r}  (vector এ {len(q)} টা সংখ্যা)\n")
    print("similarity  source                         text")
    for i in np.argsort(-sims)[:top]:
        source = data["metadatas"][i].get("source", "?")
        print(f"{sims[i]:.4f}      {source:<30} {data['documents'][i][:60]!r}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        similarity_by_hand(" ".join(sys.argv[1:]))
    else:
        show_chunks()
