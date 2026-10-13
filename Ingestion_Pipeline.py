import os
from dotenv import load_dotenv

# Document Loaders
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
    UnstructuredMarkdownLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

DOCS_DIR = "./docs"
DB_DIR = "./chroma_db"

def load_documents_from_directory(directory_path: str):
    """বিভিন্ন ফরম্যাটের ফাইল রিড করার ফাংশন"""
    documents = []

    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"'{directory_path}' ফোল্ডারটি তৈরি করা হয়েছে। দয়া করে এর ভেতর ফাইল রাখুন।")
        return documents

    for root, _, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()

            try:
                if ext == ".pdf":
                    loader = PyPDFLoader(file_path)
                    documents.extend(loader.load())
                    print(f"Loaded PDF: {file}")
                elif ext in [".txt", ".md"]:
                    loader = TextLoader(file_path, encoding="utf-8")
                    documents.extend(loader.load())
                    print(f"Loaded Text/Markdown: {file}")
                elif ext == ".docx":
                    loader = Docx2txtLoader(file_path)
                    documents.extend(loader.load())
                    print(f"Loaded Word Doc: {file}")
            except Exception as e:
                print(f"Error loading {file}: {e}")

    return documents


def main():
    print("--- ডাটা ইনজেশন শুরু হচ্ছে ---")
    documents = load_documents_from_directory(DOCS_DIR)

    # ১. ফাইল চেক: ডকুমেন্ট না থাকলে স্ক্রিপ্ট বন্ধ হবে, ক্র্যাশ করবে না
    if not documents:
        print(f"\n[সতর্কবার্তা] '{DOCS_DIR}' ফোল্ডারে কোনো সমর্থিত ফাইল পাওয়া যায়নি!")
        print("দয়া করে ফোল্ডারটিতে অন্তত একটি .pdf, .txt, .docx, বা .md ফাইল রাখুন এবং পুনরায় রান করুন।")
        return

    print(f"\nমোট সংগৃহীত পেজ/ডকুমেন্ট: {len(documents)}")

    # ২. উন্নত টেক্সট স্প্লিটার (RecursiveCharacterTextSplitter প্যারাগ্রাফের অর্থ বজায় রাখে)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = text_splitter.split_documents(documents)
    print(f"তৈরি হওয়া মোট চাঙ্ক: {len(chunks)}")

    if not chunks:
        print("ফাইলগুলোতে পর্যাপ্ত টেক্সট পাওয়া যায়নি।")
        return

    # ৩. জেমিনির এম্বেডিং মডেল
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")

    # ৪. ChromaDB-তে ডাটা সংরক্ষণ
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=DB_DIR
    )

    print(f"\nসফলভাবে ইনজেশন সম্পন্ন হয়েছে! ডাটাবেজ সংরক্ষিত হয়েছে: '{DB_DIR}' ফোল্ডারে।")


if __name__ == "__main__":
    main()

    