"""
Streamlit UI — শুধু backend API (http://api:8000) কে কল করে।
এখানে কোনো RAG লজিক নেই; সব লজিক backend এ। UI আর লজিক আলাদা রাখার এটাই সুবিধা:
চাইলে এই UI ফেলে দিয়ে React/মোবাইল অ্যাপ বানিয়ে একই API ব্যবহার করা যায়।
"""

import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

st.set_page_config(page_title="RAG Learning", page_icon="📚", layout="wide")


def api(method: str, path: str, **kwargs):
    r = requests.request(method, f"{API_URL}{path}", **kwargs)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"{r.status_code}: {detail}")
    return r.json()


def render_chunks(chunks: list[dict]):
    for i, c in enumerate(chunks, start=1):
        where = c["source"] + (f" · page {c['page']}" if c["page"] else "")
        st.markdown(f"**[{i}] {where}** · chunk #{c['chunk_id']} · similarity `{c['similarity']:.3f}`")
        st.code(c["content"], language=None, wrap_lines=True)


def render_message(msg: dict, show_prompt: bool):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"📎 Retrieved chunks ({len(msg['sources'])})"):
                render_chunks(msg["sources"])
        if show_prompt and msg.get("prompt"):
            with st.expander("🧾 LLM এ পাঠানো আসল prompt"):
                st.code(msg["prompt"], language=None, wrap_lines=True)


st.session_state.setdefault("messages", [])
st.session_state.setdefault("uploader_key", 0)

# ---------------------------------------------------------------------------
# Sidebar: Knowledge base (Ingestion pipeline)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("📚 Knowledge Base")

    if flash := st.session_state.pop("flash", None):
        st.success(flash)

    try:
        stats = api("GET", "/stats", timeout=10)
    except Exception as e:
        st.error(f"API তে কানেক্ট করা যাচ্ছে না।\n\n{e}")
        st.stop()

    c1, c2 = st.columns(2)
    c1.metric("Files in docs/", len(stats["files"]))
    c2.metric("Chunks in DB", stats["chunks"])
    if stats["files"]:
        with st.expander("Files"):
            st.markdown("\n".join(f"- {f}" for f in stats["files"]))
    if stats["chunks"] == 0:
        st.warning("Vector DB খালি। ফাইল আপলোড করে **Ingest** চাপো।")

    uploaded = st.file_uploader(
        "Upload documents",
        type=["pdf", "txt", "md", "docx"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
    )
    if uploaded and st.button("⬆️ Upload to docs/"):
        try:
            res = api("POST", "/upload", files=[("files", (f.name, f.getvalue())) for f in uploaded], timeout=120)
            st.session_state.flash = f"Uploaded: {', '.join(res['saved'])}. এখন Ingest চাপো।"
            st.session_state.uploader_key += 1
            st.rerun()
        except Exception as e:
            st.error(str(e))

    if st.button("🔄 Ingest (rebuild index)", type="primary", use_container_width=True):
        with st.spinner("Load → Chunk → Embed → Store ... (বড় PDF হলে কয়েক মিনিট লাগতে পারে)"):
            try:
                res = api("POST", "/ingest", timeout=1800)
                st.session_state.flash = f"Ingest সম্পন্ন: {len(res['files'])} ফাইল → {res['chunks']} chunk"
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.header("⚙️ Settings")
    k = st.slider("Top-K (কয়টা চাঙ্ক retrieve হবে)", 1, 10, 4)
    show_prompt = st.toggle("LLM prompt দেখাও", value=False)
    if st.button("🗑️ Clear chat"):
        st.session_state.messages = []
        st.rerun()

    st.caption(
        f"Chat: `{stats['chat_model']}`  \n"
        f"Embedding: `{stats['embedding_model']}`  \n"
        f"Chunk size/overlap: `{stats['chunk_size']}/{stats['chunk_overlap']}`"
    )

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("📚 RAG Learning")
tab_chat, tab_search = st.tabs(["💬 Chat (full RAG)", "🔍 Retrieval Playground"])

with tab_chat:
    st.caption("প্রশ্ন → embedding → Vector DB সার্চ → Top-K চাঙ্ক + প্রশ্ন → Gemini → উত্তর")
    history = st.container()  # মেসেজগুলো input বক্সের উপরে রাখার জন্য
    question = st.chat_input("তোমার ডকুমেন্ট নিয়ে প্রশ্ন করো...")

    with history:
        for msg in st.session_state.messages:
            render_message(msg, show_prompt)

        if question:
            user_msg = {"role": "user", "content": question}
            st.session_state.messages.append(user_msg)
            render_message(user_msg, show_prompt)

            with st.spinner("Retrieving + generating..."):
                try:
                    res = api("POST", "/ask", json={"question": question, "k": k}, timeout=300)
                    bot_msg = {
                        "role": "assistant",
                        "content": res["answer"],
                        "sources": res["sources"],
                        "prompt": res["prompt"],
                    }
                except Exception as e:
                    bot_msg = {"role": "assistant", "content": f"⚠️ Error: {e}"}
            st.session_state.messages.append(bot_msg)
            render_message(bot_msg, show_prompt)

with tab_search:
    st.caption(
        "এখানে শুধু **Retrieval** ধাপ চলে — LLM কল হয় না। দেখো প্রশ্নের সাথে কোন চাঙ্কগুলো "
        "সবচেয়ে বেশি মেলে আর তাদের similarity score কত (1 এর কাছে = বেশি মিল)।"
    )
    with st.form("search"):
        query = st.text_input("Query")
        submitted = st.form_submit_button("Search")
    if submitted and query:
        try:
            res = api("POST", "/search", json={"question": query, "k": k}, timeout=60)
            if not res["results"]:
                st.info("কিছু পাওয়া যায়নি — Vector DB খালি কিনা দেখো।")
            render_chunks(res["results"])
        except Exception as e:
            st.error(str(e))
