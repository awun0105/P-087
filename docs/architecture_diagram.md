# Architecture Diagram

> **Ghi chú Real2Sim (2026-09-29):** các sơ đồ phía dưới là mẫu của ban tổ chức
> (chat agent LangGraph), giữ nguyên theo quy tắc additive-only. Kiến trúc thật của
> Real2Sim nằm ở [`ARCHITECTURE.md`](../ARCHITECTURE.md) và mục "Real2Sim Studio" cuối file.


## System Overview

```mermaid
graph TB
    User([User]) --> UI[Frontend<br/>React/Next.js]
    UI -->|REST API| API[FastAPI Backend]
    API --> Agent[LangGraph Agent]
    Agent --> LLM[LLM Service<br/>GPT-4o / Gemini]
    Agent --> Tools[Agent Tools]
    Tools --> DB[(Database)]
    Agent --> VS[Vector Store<br/>ChromaDB]
```

## Agent Flow

```mermaid
graph LR
    START((Start)) --> Input[Parse Input]
    Input --> Analyze[Analyze Query]
    Analyze --> Decide{Need Tool?}
    Decide -->|Yes| CallTool[Call Tool]
    CallTool --> Analyze
    Decide -->|No| Generate[Generate Response]
    Generate --> END((End))
```

## Component Details

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Frontend | React/Next.js | User interface |
| Backend | FastAPI | API server |
| Agent | LangGraph | AI agent orchestration |
| LLM | OpenAI/Gemini | Language model |
| Database | PostgreSQL/SQLite | Data persistence |
| Vector Store | ChromaDB | RAG / embeddings |

## Real2Sim Studio — triển khai đã chốt (ADR 0003)

```mermaid
graph LR
    U([Người dùng / trình duyệt]) --> UI[Web UI<br/>Next.js trên Vercel]
    UI -->|REST| API[Server điều khiển<br/>FastAPI + PostgreSQL trên Railway]
    U -->|presigned upload/download| R2[(Cloudflare R2<br/>video, frame, 3DGS, export)]
    API -->|bật/tắt, giao job| GPU[GPU worker RunPod<br/>COLMAP, Brush, SOG, LOD]
    GPU -->|đọc input, ghi artifact| R2
    GPU -->|tiến trình, kết quả| API
    API -->|cấp link có hạn| R2
```

Hiện trạng chạy thật vẫn là một máy (`scripts/gpu/run_stack.sh`); sơ đồ trên là
đích triển khai theo [plan Cloud Studio](plans/active/2026-09-29-cloud-studio.md).

