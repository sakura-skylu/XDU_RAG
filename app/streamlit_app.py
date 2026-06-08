from __future__ import annotations

from html import escape
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import streamlit as st

from xidian_rag.pipeline import build_rag_service
from xidian_rag.settings import load_settings, load_sources
from xidian_rag.vector_store import build_vector_store


st.set_page_config(page_title="西电官网 RAG 检索", page_icon="XD", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 980px;
        padding-top: 2rem;
    }
    [data-testid="stSidebar"] .stMetric {
        background: #f6f8fb;
        border: 1px solid #e6eaf0;
        border-radius: 8px;
        padding: 0.6rem 0.7rem;
    }
    div[data-testid="stTextInput"] input {
        border-radius: 8px;
    }
    div[data-testid="stButton"] button {
        border-radius: 8px;
        font-weight: 600;
    }
    .source-card {
        border: 1px solid #e8edf3;
        border-radius: 8px;
        padding: 0.75rem 0.85rem;
        margin-bottom: 0.7rem;
        background: #ffffff;
    }
    .source-meta {
        color: #64748b;
        font-size: 0.82rem;
        margin: 0.2rem 0 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("西电官网检索")
st.caption("基于已收录官方页面回答。")

allowed_domains, _sources, category_keywords = load_sources()
categories = ["全部", *category_keywords.keys()]

with st.sidebar:
    st.header("筛选")
    category = st.selectbox("资料分类", categories, index=0)
    stats = build_vector_store(load_settings()).stats()
    top_k = st.slider("来源数", min_value=1, max_value=10, value=5)
    st.metric("索引切片", stats.get("chunks", 0))
    with st.expander("来源域名"):
        for domain in allowed_domains:
            st.caption(domain)

with st.form("ask_form", border=False):
    question = st.text_input("问题", placeholder="保研政策有哪些要求？")
    submitted = st.form_submit_button("检索", type="primary")

if submitted and question.strip():
    with st.spinner("正在检索官方资料..."):
        service = build_rag_service()
        result = service.ask(
            question.strip(),
            top_k=top_k,
            category=None if category == "全部" else category,
        )

    st.markdown("### 回答")
    if result.has_evidence:
        st.success(result.answer)
    else:
        st.warning(result.answer)

    if result.citations:
        st.markdown("### 来源")
        for index, citation in enumerate(result.citations, start=1):
            title = escape(citation.title)
            url = escape(citation.url, quote=True)
            source_site = escape(citation.source_site)
            source_category = escape(citation.category)
            publish_date = escape(citation.publish_date or "时间未知")
            snippet = escape(citation.snippet)
            score = f"{citation.score:.3f}"
            st.markdown(
                f"""
                <div class="source-card">
                    <strong>[{index}] <a href="{url}">{title}</a></strong>
                    <div class="source-meta">
                        {source_site} · {source_category} · {publish_date} · {score}
                    </div>
                    <div>{snippet}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
elif submitted:
    st.warning("请输入问题。")
elif stats.get("chunks", 0) == 0:
    st.info("知识库为空，请先完成抓取和索引。")
