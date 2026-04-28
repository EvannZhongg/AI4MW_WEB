# AI4MW Web 架构分析（代码核验版）

> 本文基于当前仓库代码（`2026-04-28`）整理，重点区分“已接入主链路”和“仓库内存在但未接入主链路”的模块。

## 1. 当前项目结论（先看这个）

- 主运行链路是 `Next.js 前端 -> Django API -> PostgreSQL + 文件存储 + 外部服务`。
- 聊天能力由 `llm_agent` 承担，Agent 支持统一工具调用：内置只读工作区工具（`grep` / `glob` / `list_dir` / `read_file`）、subagent 分发工具（`spawn_subagent`）与 `line_build` skill 通过同一 registry 执行。
- 曲线提取有两条入口：
  - 前端工作台页面 `/curve-extraction` 走 Django `line_build` 代理接口。
  - 聊天 Agent 在需要时直接调用 `line_build` 独立服务。
- `datesheet_rag` 在仓库内有完整原型代码（DRF + Celery + KG），但当前未加入 Django 主应用启动链路。

## 2. 总体架构图（Current Runtime + Dormant Prototype）

```mermaid
flowchart LR
    U[User Browser]

    subgraph FE[Next.js Frontend]
      FE1["/ (Chat)"]
      FE2["/chat-search"]
      FE3["/curve-extraction"]
      FE4["Workspace Sidebar\n(session/history/login)"]
    end

    subgraph BE[Django Backend]
      URL["AI4MW_web/urls.py\nAPI Routing"]
      CORE["AI4MW_web/views.py\nsession/logout/root_redirect"]
      AGENT["llm_agent/views.py\nSSE chat + conversation APIs"]
      LINE["line_build/views.py\nhealth/extract proxy APIs"]
      AUTH["django-allauth\nGitHub OAuth"]
    end

    subgraph DATA[State & Storage]
      DB[(PostgreSQL)]
      FS[(storage/llm_agent_uploads)]
    end

    subgraph EXT[External Services]
      LLM[(OpenAI-compatible LLM API)]
      LB[(line_build standalone service :8004)]
      GH[(GitHub OAuth)]
    end

    subgraph DORMANT[Not Wired To Main Runtime]
      RAG["datesheet_rag\nDRF + Celery + KG pipeline"]
      RB[(Redis/Celery Broker)]
      VDB[(pgvector / graph-related storage)]
    end

    U --> FE
    FE -->|"GET/POST /api/*"| URL
    FE -->|"/accounts/github/login/"| URL

    URL --> CORE
    URL --> AGENT
    URL --> LINE
    URL --> AUTH

    CORE --> DB
    AGENT --> DB
    AGENT --> FS
    AGENT --> LLM
    AGENT -->|"tool call: line_build skill"| LB
    LINE -->|"proxy /health /extract"| LB
    AUTH --> GH

    RAG -. "code exists, not in INSTALLED_APPS/urls" .- URL
    RAG -. "prototype dependencies" .-> RB
    RAG -. "prototype dependencies" .-> VDB
```

## 3. Agent 架构图（llm_agent Runtime）

```mermaid
flowchart TD
    A["POST /api/chat\nmultipart(JSON+attachments)"]
    B["chat_stream\nauth + payload parse"]
    C["Conversation/Message\ncreate or load"]
    D["attachment_service\nsave_uploaded_attachments"]
    E["AgentContextBuilder + chat_service\nagent/*.md prompt + runtime context + history + images"]
    F["AgentRuntime.run"]
    G["tools.registry\nbuiltins + subagent + skill adapters"]
    H["LLMClient.create_raw\ninterface=auto, tool_choice=auto"]
    I{"Tool calls returned?"}
    J["ToolRegistry.execute\nschema validation + dispatch"]
    K1["builtin read-only tools\ngrep/glob/list_dir/read_file"]
    K3["spawn_subagent\nfocused internal agent"]
    S1["Subagent AgentRuntime\nsubagent_system.md + no spawn tool"]
    K2["line_build skill\nhealth/extract/extract_by_path"]
    L["line_build service\n/api/v1/..."]
    M["append tool outputs\nand continue next round"]
    N["final assistant text"]
    O["SSE stream\ndelta/status/tool_calls"]
    P["persist assistant message\nclear response_pending_since"]
    Q["fallback: tools unsupported\ncreate_text()"]
    R["error path:\ndiscard_user_message"]

    DB[(PostgreSQL)]
    FS[(Local file storage)]

    A --> B --> C --> DB
    B --> D --> FS
    C --> E
    D --> E
    E --> F
    F --> G --> H
    H --> I
    H --> Q --> N
    I -- "No" --> N
    I -- "Yes" --> J
    J --> K1 --> J
    J --> K3 --> S1 --> J
    J --> K2 --> L --> J
    J --> M --> H
    N --> O
    N --> P --> DB
    H -. "LLMClientError" .-> R --> DB
```

## 4. 关键模块职责（主链路）

| 模块 | 职责 | 说明 |
|---|---|---|
| `AI4MW_web` | Django 主配置与主路由 | 承接 `/api/*`、`/accounts/*`、根路径跳转 |
| `llm_agent` | 会话/消息模型、SSE 聊天、Agent 运行时、附件管理 | 聊天主业务核心 |
| `llm_agent/services/context_builder.py` | 上下文编排 | 从 `llm_agent/prompts/agent/*.md` 组装系统提示、运行时上下文、subagent prompt |
| `llm_agent/tools` | 统一工具注册、参数校验、只读工作区工具、subagent 分发、skill adapter | 内置 `grep` / `glob` / `list_dir` / `read_file` / `spawn_subagent` |
| `llm_agent/skills/line_build` | Skill 形式封装曲线提取能力 | 通过 `llm_agent/tools` adapter 接入 agent |
| `line_build` | Django 到独立算法服务的代理层 | 前端工作台用它访问提取服务 |
| `frontend` | Next.js UI 与 API 调用层 | 已落地聊天、搜索、曲线提取页面 |
| `storage/llm_agent_uploads` | 聊天图片附件存储目录 | 保存并回放消息附件 |

## 5. `datesheet_rag` 的准确定位

- 有真实代码：任务模型、图谱模型、DRF ViewSet、Celery 多阶段流水线。
- 但当前不是主应用可用能力：
  - 未接入 `INSTALLED_APPS`。
  - 未接入 Django 主路由。
  - 依赖项（如 DRF/Celery/OpenAI/pgvector/docling）不在当前 `requirements.txt`。
  - 部分代码引用 `api.models.Device`，当前仓库无该模块。

## 6. 配置与运行时要点

- 后端与前端都采用“系统环境变量 > `.env` > `config.yaml`”的覆盖逻辑。
- `config.yaml` 在当前实现中按扁平 `KEY: value` 解析，不支持复杂 YAML 嵌套结构。
- 主数据库默认是 PostgreSQL，仓库中的 `db.sqlite3` 并非主路径默认值。
