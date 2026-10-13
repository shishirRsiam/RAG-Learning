import os
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain

load_dotenv()

def test_rag():
    # ১. পূর্বে সংরক্ষিত ChromaDB ডাটাবেজ লোড করা
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings
    )

    # ২. রিট্রিভার সেট করা (সবচেয়ে প্রাসঙ্গিক ৩টি চাঙ্ক খুঁজে আনবে)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # ৩. জেমিনি এলএলএম মডেল কল করা
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.2)

    # ৪. প্রম্পট টেমপ্লেট
    prompt = ChatPromptTemplate.from_template("""
    নিচের কনটেক্সট থেকে তথ্য নিয়ে প্রশ্নের সঠিক উত্তর দাও। কনটেক্সটে তথ্য না থাকলে বলো যে তুমি জানো না।

    কনটেক্সট:
    {context}

    প্রশ্ন: {input}
    """)

    # ৫. RAG চেইন তৈরি
    document_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, document_chain)

    # ৬. টেস্ট প্রশ্ন পাঠানো
    user_query = "আপনার টেক্সট ফাইলের বিষয়ের ওপর একটি প্রশ্ন এখানে লিখুন"
    response = rag_chain.invoke({"input": user_query})

    print("\n--- মডেলের উত্তর ---")
    print(response["answer"])

if __name__ == "__main__":
    test_rag()
    