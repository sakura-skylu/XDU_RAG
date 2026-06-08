# 西电官网数据 RAG 智能检索系统 UML 图例

本文档整理项目报告可直接引用的 UML/流程图例。图例使用 Mermaid 编写，便于后续在 Markdown、Mermaid Live Editor、draw.io 或 VS Code 插件中导出为 PNG/SVG 后插入 Word/PDF。

## SVG 图文件

以下 SVG 已按 16:9 幻灯片比例制作，可直接插入 PPT：

| 图例 | SVG 文件 | Mermaid 源文件 |
| --- | --- | --- |
| 用例图 | `docs/diagrams/use_case.svg` | `docs/diagrams/use_case.mmd` |
| 学生问答顺序图 | `docs/diagrams/ask_sequence.svg` | `docs/diagrams/ask_sequence.mmd` |
| 知识库构建顺序图 | `docs/diagrams/index_sequence.svg` | `docs/diagrams/index_sequence.mmd` |
| 核心类图 | `docs/diagrams/class_diagram.svg` | `docs/diagrams/class_diagram.mmd` |
| 系统组件图 | `docs/diagrams/component_diagram.svg` | `docs/diagrams/component_diagram.mmd` |

## 1. 用例图

```mermaid
flowchart LR
    student["学生用户"]
    admin["系统管理员/项目成员"]

    subgraph system["西电官网数据 RAG 智能检索系统"]
        ask(("自然语言问答"))
        filter(("按资料分类筛选"))
        citations(("查看官方来源引用"))
        refusal(("无依据时拒答"))
        stats(("查看知识库统计"))
        crawl(("采集官方公开页面"))
        ingest(("导入本地 HTML 原文"))
        index(("构建/更新向量索引"))
        config(("维护官网白名单与分类词"))
    end

    student --- ask
    student --- filter
    student --- citations
    student --- refusal
    student --- stats

    admin --- crawl
    admin --- ingest
    admin --- index
    admin --- config
    admin --- stats

    filter -. "<<extend>>" .-> ask
    citations -. "<<include>>" .-> ask
    refusal -. "<<extend>>" .-> ask
    crawl -. "<<include>>" .-> config
    ingest -. "<<alternative>>" .-> crawl
    index -. "<<include>>" .-> ingest
```

## 2. 学生问答顺序图

```mermaid
sequenceDiagram
    actor Student as 学生用户
    participant UI as Streamlit 前端
    participant API as FastAPI /ask
    participant Service as RagService
    participant Store as VectorStore
    participant Embed as EmbeddingProvider
    participant Chat as OpenAICompatibleChatClient

    Student->>UI: 输入问题、选择分类和来源数
    UI->>API: POST /ask(question, category, top_k)
    API->>Service: build_rag_service().ask()
    Service->>Store: search(question, provider, top_k, category)
    Store->>Embed: embed([question])
    Embed-->>Store: query_vector
    Store-->>Service: SearchHit 列表
    Service->>Service: 过滤低可信/噪声命中并生成 Citation

    alt 命中可靠证据且启用 API Chat
        Service->>Chat: complete(question, evidence_hits)
        Chat-->>Service: 带引用编号的生成式回答
        Service-->>API: Answer(mode="api")
    else 命中可靠证据但未启用 API Chat
        Service->>Service: _extractive_answer()
        Service-->>API: Answer(mode="extractive")
    else 未命中可靠证据
        Service-->>API: Answer(mode="refusal", has_evidence=false)
    end

    API-->>UI: answer + citations + mode
    UI-->>Student: 展示回答、来源链接和片段
```

## 3. 知识库构建顺序图

```mermaid
sequenceDiagram
    actor Maintainer as 系统管理员/项目成员
    participant CLI as xidian-rag CLI
    participant Settings as settings/load_sources
    participant Crawler as WebCrawler
    participant Parser as HTML 解析与正文抽取
    participant Disk as data/*.jsonl / raw pages
    participant Chunking as chunking.make_chunks
    participant Embed as EmbeddingProvider
    participant Store as LocalVectorStore / ChromaVectorStore

    Maintainer->>CLI: xidian-rag crawl --max-pages N
    CLI->>Settings: load_settings(), load_sources()
    Settings-->>CLI: 白名单、种子 URL、分类关键词
    CLI->>Crawler: crawl(max_pages, max_depth)
    loop 白名单内页面
        Crawler->>Parser: fetch_page() / parse_html_page()
        Parser-->>Crawler: title, content, links
        Crawler->>Disk: 保存原始 HTML 快照
        Crawler->>Crawler: 生成 Document、去重、分类
    end
    Crawler-->>CLI: Document 列表
    CLI->>Disk: 写入 data/documents.jsonl

    Maintainer->>CLI: xidian-rag index
    CLI->>Disk: 读取 data/documents.jsonl
    CLI->>Chunking: make_chunks(documents)
    Chunking-->>CLI: Chunk 列表
    CLI->>Disk: 写入 data/chunks.jsonl
    CLI->>Embed: 为 Chunk 文本生成向量
    Embed-->>CLI: vectors
    CLI->>Store: build(chunks, provider)
    Store->>Disk: 持久化本地索引或 Chroma 集合
```

## 4. 核心类图

```mermaid
classDiagram
    class SourceConfig {
        +str url
        +str source_site
        +str category
        +bool may_require_vpn
    }

    class Document {
        +str doc_id
        +str title
        +str url
        +str source_site
        +str category
        +str publish_date
        +str content
        +str crawl_time
        +str checksum
        +to_dict()
        +from_dict()
    }

    class Chunk {
        +str chunk_id
        +str doc_id
        +str text
        +str title
        +str url
        +str source_site
        +str category
        +str publish_date
        +to_dict()
        +from_dict()
    }

    class SearchHit {
        +Chunk chunk
        +float score
    }

    class Citation {
        +str title
        +str url
        +str source_site
        +str category
        +str publish_date
        +str snippet
        +float score
        +to_dict()
    }

    class Answer {
        +str answer
        +list citations
        +bool has_evidence
        +str mode
        +to_dict()
    }

    class Settings {
        +str openai_base_url
        +str openai_chat_model
        +str openai_embedding_model
        +bool use_api_embeddings
        +bool use_api_chat
        +bool use_direct_api_chat
        +str vector_store
    }

    class WebCrawler {
        +list allowed_domains
        +list sources
        +dict category_keywords
        +Settings settings
        +crawl(max_pages, max_depth) list
    }

    class EmbeddingProvider {
        <<interface>>
        +embed(texts) list
    }

    class HashEmbeddingProvider {
        +int dimensions
        +embed(texts) list
    }

    class OpenAICompatibleEmbeddingProvider {
        +Settings settings
        +embed(texts) list
    }

    class LocalVectorStore {
        +Path path
        +list chunks
        +list vectors
        +build(chunks, provider)
        +save()
        +load()
        +search(query, provider, top_k, category) list
        +stats() dict
    }

    class ChromaVectorStore {
        +Path path
        +str collection_name
        +build(chunks, provider)
        +load()
        +search(query, provider, top_k, category) list
        +stats() dict
    }

    class OpenAICompatibleChatClient {
        +Settings settings
        +complete(question, hits) str
    }

    class RagService {
        +LocalVectorStore store
        +EmbeddingProvider provider
        +Settings settings
        +ask(question, top_k, category) Answer
        +_ask_direct_api(question, top_k, category) Answer
        +_extractive_answer(question, hits) str
    }

    SourceConfig --> WebCrawler
    WebCrawler --> Document : creates
    Document --> Chunk : split into
    SearchHit --> Chunk
    Answer o-- Citation
    EmbeddingProvider <|.. HashEmbeddingProvider
    EmbeddingProvider <|.. OpenAICompatibleEmbeddingProvider
    LocalVectorStore o-- Chunk
    ChromaVectorStore ..> Chunk
    LocalVectorStore ..> EmbeddingProvider
    ChromaVectorStore ..> EmbeddingProvider
    RagService --> LocalVectorStore : search
    RagService --> ChromaVectorStore : optional
    RagService --> EmbeddingProvider
    RagService --> OpenAICompatibleChatClient : optional generation
    RagService --> Answer : returns
    Settings --> RagService
    Settings --> WebCrawler
```

## 5. 系统组件图

```mermaid
flowchart LR
    subgraph client["展示与调用层"]
        streamlit["Streamlit 问答前端"]
        rest_client["API 客户端/命令行调用"]
    end

    subgraph api["接口层"]
        fastapi["FastAPI\n/health /sources /stats /ask"]
    end

    subgraph core["核心业务层"]
        pipeline["pipeline\n服务装配与索引流程"]
        rag["RagService\n检索、证据筛选、拒答、回答生成"]
        crawler["crawler\n抓取、解析、快照、去重"]
        chunking["chunking\n文本切片"]
        categorizer["categorizer\n分类与关键词得分"]
    end

    subgraph adapters["外部与存储适配层"]
        embedding["EmbeddingProvider\nHash / API"]
        chat["OpenAI-compatible Chat API"]
        vector["VectorStore\nLocal JSON / Chroma"]
        config["config/sources.json"]
        data["data/\ndocuments chunks index raw pages"]
    end

    streamlit --> rag
    rest_client --> fastapi
    fastapi --> pipeline
    fastapi --> rag
    pipeline --> crawler
    pipeline --> chunking
    pipeline --> embedding
    pipeline --> vector
    crawler --> config
    crawler --> data
    chunking --> data
    rag --> vector
    rag --> embedding
    rag --> categorizer
    rag -. 可选 .-> chat
    vector --> data
```
