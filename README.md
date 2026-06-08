# 西电官网数据 RAG 智能检索系统

面向西电学生的首版 RAG 智能检索系统。系统采集西电公开官网页面，构建本地知识库，并通过自然语言问答返回带来源引用的答案。

## 功能范围

- 官方站点白名单采集：西电主站、综合信息网、信息公开网、教务处、研究生院、学生工作部。
- 聚焦内容：学校官方政策、推免/保研政策、生活安排、比赛通知。
- 检索能力：向量检索为主，关键词分类和文本匹配辅助。
- 回答约束：只基于检索命中的官方资料作答；没有依据时拒答。
- 界面：FastAPI 后端接口 + Streamlit 问答前端。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env
```

没有 API Key 时系统会使用本地哈希向量检索和抽取式回答，适合先验证流程。配置 OpenAI-compatible API 后会启用模型生成答案；如果本地 embedding 检索效果不理想，可以开启直接 API 模式，跳过向量检索。

默认向量存储为 `VECTOR_STORE=local`，无需额外服务；需要使用 Chroma 时，执行 `pip install -r requirements-chroma.txt`，把 `.env` 改为 `VECTOR_STORE=chroma` 后重新执行 `xidian-rag index`。

## 构建知识库

先小规模抓取公开页面：

```powershell
xidian-rag crawl --max-pages 120
xidian-rag index
```

也可以手动导入原文 HTML 或 PDF：把 `.html`/`.pdf` 文件放入 `data/knowledge_base/pages/`，再执行：

```powershell
xidian-rag ingest-pages
xidian-rag index
```

`ingest-pages` 会读取目录下的 HTML 和 PDF 文件；PDF 会先通过 `pypdf` 抽取文本，再进入后续切片和索引流程。它也会在入口层跳过学校首页、新闻网首页等大段菜单/频道导航页，避免这些页面进入
`data/documents.jsonl` 并污染后续检索。需要重建当前知识库产物时，按顺序执行：

```powershell
xidian-rag ingest-pages
xidian-rag index
```

上述流程会依次重写 `data/documents.jsonl`、`data/chunks.jsonl` 和 `data/index/local_vectors.json`。如果只想本地离线重建向量索引，可在当前 PowerShell 会话临时关闭 API embedding：

```powershell
$env:USE_API_EMBEDDINGS="false"
$env:VECTOR_STORE="local"
xidian-rag index
```

也可以先不抓取，直接用 `ask` 验证空库拒答逻辑：

```powershell
xidian-rag ask "保研政策有哪些要求"
```

## 启动服务

```powershell
uvicorn xidian_rag.api:app --reload --host 127.0.0.1 --port 8000
```

接口示例：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/ask -ContentType "application/json" -Body '{"question":"近期有哪些竞赛通知？","top_k":5}'
```

启动前端：

```powershell
streamlit run app/streamlit_app.py
```

## 项目结构

```text
app/streamlit_app.py        Streamlit 前端
config/sources.json         官方数据源白名单
src/xidian_rag/             核心包
tests/                      基础单元测试
data/knowledge_base/pages/  抓取到的网页原文快照或手动放入的 HTML/PDF（未清洗、未抽取）
data/documents.jsonl        抽取后的结构化文档
data/chunks.jsonl           处理后的文本切片
data/index/                 本地向量索引
data/crawl_failures.jsonl   抓取失败日志
```

`data/knowledge_base/` 只用于保存抓取到的原文。系统会在成功请求页面后，把原始响应内容按 `doc_id.html` 写入
`data/knowledge_base/pages/`；也可以手动把 `.html` 或 `.pdf` 原文放入该目录，通过 `xidian-rag ingest-pages` 生成
`data/documents.jsonl`。后续的正文抽取结果、切片和索引仍写入 `data/` 下的处理产物文件。

## API 配置

`.env` 支持以下配置：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_CHAT_MODEL=deepseek-v4-flash
ZHIPU_API_KEY=
OPENAI_EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
OPENAI_EMBEDDING_MODEL=embedding-3
OPENAI_EMBEDDING_DIMENSIONS=2048
USE_API_EMBEDDINGS=true
USE_API_CHAT=true
USE_DIRECT_API_CHAT=false
VECTOR_STORE=local
```

`USE_API_CHAT=false` 时，系统会用检索片段生成简短抽取式答案；`USE_API_EMBEDDINGS=false` 时，系统会用本地哈希向量，避免演示环境依赖外部模型。
`USE_DIRECT_API_CHAT=true` 时，问答会跳过 embedding 检索，改用本地文本相关性筛选候选资料，再直接调用 OpenAI-compatible Chat API 根据候选资料回答并保留来源引用。
`OPENAI_EMBEDDING_BASE_URL`、`ZHIPU_API_KEY` 和 `OPENAI_EMBEDDING_DIMENSIONS` 用于单独配置智谱 embedding，不影响 Chat API。

## 数据合规

首版只采集公开、官方、可访问页面，不绕过登录、VPN 或权限限制。`notice.xidian.edu.cn` 若无法访问，会记录失败原因，不做规避。
