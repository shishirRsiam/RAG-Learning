"""
সব কনফিগারেশন এক জায়গায়।

প্রতিটা ভ্যালু environment variable থেকে আসে (docker-compose.yml / .env ফাইলে সেট করা),
না থাকলে ডিফল্ট ভ্যালু ব্যবহার হয়। কোড না বদলেই এক্সপেরিমেন্ট করা যায় —
শুধু .env বদলে `docker compose up -d` দিলেই হবে।
"""

import os

# --- Google Gemini ---
# API key এখানে পড়তে হয় না — langchain-google-genai নিজেই GOOGLE_API_KEY env variable পড়ে নেয়।
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.5-flash-lite")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

# --- Vector DB (ChromaDB server, আলাদা container এ চলে) ---
# "chromadb" হলো docker-compose এর service নাম; Docker এর ভেতরের DNS এই নামকে
# ঐ container এর IP তে রিজলভ করে দেয়।
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "rag_docs")

# --- Ingestion ---
DOCS_DIR = os.getenv("DOCS_DIR", "/app/docs")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
# একবারে কয়টা চাঙ্ক এম্বেডিং API তে পাঠাবো (rate limit এড়াতে ছোট রাখা)
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "50"))

# --- Retrieval ---
# প্রশ্নের জন্য সবচেয়ে কাছের কয়টা চাঙ্ক আনবো
TOP_K = int(os.getenv("TOP_K", "4"))

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
