# AI4MW 配置文档（单一来源）

> 所有可配置项必须在此文档登记；代码只读取配置，不硬编码。  
> 涉及密钥/密码一律使用环境变量或独立密钥文件，不在代码/日志中明文输出。  
> `.env` 放在项目根目录（与 `manage.py` 同级），作为密钥与运行时配置的来源之一。  
> `config.yaml` 也在根目录，作为**可读/可共享**的机器配置文件（不存密钥）。  
> 读取优先级：**系统环境变量 > `.env` > `config.yaml`**。  
> 前端 Next.js 会读取根目录 `.env` 与 `config.yaml`（`frontend/next.config.mjs` 解析），用于本地/公网切换。
> `.env` 仅保存密钥（如 `*_API_KEY`、`DB_PASSWORD` 等）；其余非密钥配置统一放 `config.yaml`。

## 1. 全局环境
```
ENV=dev|staging|prod
DEBUG=true|false
ALLOWED_HOSTS=comma,separated,hosts
TIME_ZONE=UTC
LANGUAGE_CODE=zh-hans
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
```

## 2. 数据库（PostgreSQL + pgvector）
```
DB_ENGINE=django.db.backends.postgresql
DB_NAME=AI4MW_WEB
DB_USER=postgres
DB_PASSWORD=${AI4MW_DB_PASSWORD}
DB_HOST=localhost
DB_PORT=5433
```
说明：
- `AI4MW_DB_PASSWORD` 从系统环境变量注入。
- `DB_NAME` 目前尚未创建，需初始化迁移后创建。

## 3. 对象存储
```
OBJECT_STORE_PROVIDER=minio|s3|local
OBJECT_STORE_ENDPOINT=http://localhost:9000
OBJECT_STORE_ACCESS_KEY=${AI4MW_OBJ_ACCESS_KEY}
OBJECT_STORE_SECRET_KEY=${AI4MW_OBJ_SECRET_KEY}
OBJECT_STORE_BUCKET=ai4mw-artifacts
```

## 4. 解析服务（MinerU）
```
PARSER_PROVIDER=mineru
PARSER_BASE_URL=http://localhost:8002
PARSER_TIMEOUT_SEC=120
PARSER_MAX_FILE_MB=100
```
说明：不使用 docling；MinerU 服务端口固定 8002。

## 4.1 曲线提取服务（Line Build）
```
LINE_BUILD_BASE_URL=http://localhost:8004
LINE_BUILD_TIMEOUT_SEC=120
```
说明：
- 用于前端“曲线提取”页面对应的后端算法服务。
- Django 当前通过代理接口转发到该服务，而不是让前端直接请求 8004。
- 推荐在 Linux 公网部署时也保持该服务仅内网可访问。

## 5. LLM / Embedding / VLM
```
LLM_PROVIDER=openai|local|azure|other
LLM_MODEL=gpt-4.1
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=${AI4MW_LLM_API_KEY}
LLM_API_INTERFACE=chat_completions|responses|auto
LLM_API_INTERFACE_PREFERENCE=chat_completions|responses
LLM_TEMPERATURE=0.2
LLM_CONNECT_TIMEOUT_SEC=10
LLM_READ_TIMEOUT_SEC=60
LLM_STREAM_READ_TIMEOUT_SEC=300
LLM_MAX_RETRIES=2
LLM_INITIAL_RETRY_DELAY_SEC=1
LLM_MAX_RETRY_DELAY_SEC=8
LLM_POOL_MAXSIZE=10
LLM_EXTRA_HEADERS_JSON={}

LLM_AGENT_TOOL_WORKSPACE=.
LLM_AGENT_ENABLED_BUILTIN_TOOLS=glob,grep,list_dir,read_file
LLM_AGENT_ENABLE_SUBAGENTS=true
LLM_AGENT_MAX_TOOL_ROUNDS=4
LLM_AGENT_MAX_SUBAGENT_TOOL_ROUNDS=4
LLM_AGENT_MAX_TOOL_RESULT_CHARS=120000

SUMMARY_LLM_MODEL=deepseek-chat
SUMMARY_LLM_API_BASE=https://api.deepseek.com/v1
SUMMARY_LLM_API_KEY=${SUMMARY_LLM_API_KEY}
SUMMARY_LLM_PROVIDER=openai|local|azure|other
SUMMARY_LLM_API_INTERFACE=chat_completions|responses|auto
SUMMARY_LLM_TEMPERATURE=0.2

EMBED_PROVIDER=openai|local
EMBED_MODEL=text-embedding-3-large
EMBED_API_BASE=https://api.openai.com/v1
EMBED_DIM=3072
EMBED_API_KEY=${AI4MW_EMBED_API_KEY}
EMBED_BATCH_SIZE=64

VLM_PROVIDER=openai|local
VLM_MODEL=gpt-4o-mini
VLM_API_BASE=https://api.openai.com/v1
VLM_API_KEY=${AI4MW_VLM_API_KEY}
```
说明：
- LLM 架构、skill 规范、消息拼装和公网部署建议，见 `docs/LLM_GUIDELINES.md`
- `LLM_API_INTERFACE`
  - `chat_completions`：适用于 DeepSeek、DashScope compatible-mode、常见 OpenAI 兼容网关。
  - `responses`：适用于直接走 OpenAI Responses API 的场景。
  - `auto`：先按 `LLM_API_INTERFACE_PREFERENCE` 尝试，遇到典型接口不兼容错误时自动回退到另一种接口。
- 主对话 agent 若需要多轮 + skill/tool 调用，推荐将 `LLM_API_INTERFACE=auto`、`LLM_API_INTERFACE_PREFERENCE=chat_completions`
  - 原因：部分 Responses 兼容网关虽然能返回首轮 tool call，但对 `previous_response_id` / `function_call_output` 的后续轮次支持并不稳定。
- `LLM_EXTRA_HEADERS_JSON`
  - 用于通过网关/中转服务时附带额外请求头，示例：`{"HTTP-Referer":"https://ai4mw.example.com","X-Title":"AI4MW"}`
- `LLM_CONNECT_TIMEOUT_SEC`、`LLM_READ_TIMEOUT_SEC`、`LLM_STREAM_READ_TIMEOUT_SEC`
  - 分别控制建连、普通响应、流式响应读取超时。
- `LLM_MAX_RETRIES` 与重试延迟项
  - Django 侧会对超时、连接失败、`408/409/425/429/5xx` 做指数退避重试，并优先尊重 `Retry-After`。
- `SUMMARY_LLM_*`
  - 摘要标题模型默认继承主聊天模型的网络重试配置，只需单独覆盖模型、接口类型、地址或密钥即可。
- `LLM_AGENT_TOOL_WORKSPACE`
  - 聊天 agent 的只读工作区工具根目录，支持相对项目根目录路径。
- `LLM_AGENT_ENABLED_BUILTIN_TOOLS`
  - 启用内置只读工具，默认 `glob,grep,list_dir,read_file`。
  - 公网部署下不提供 shell/write/edit 类工具；内置工具会屏蔽 `.env`、数据库、上传存储、`.git` 等敏感路径。
- `LLM_AGENT_ENABLE_SUBAGENTS`
  - 是否启用 `spawn_subagent` 分发工具。
  - 当前 Web 架构中 subagent 会在同一轮请求内同步执行并把结果回填给主 agent。
- `LLM_AGENT_MAX_TOOL_ROUNDS`
  - 单轮最多允许的模型工具回环次数。
- `LLM_AGENT_MAX_SUBAGENT_TOOL_ROUNDS`
  - 单个 subagent 最多允许的工具回环次数。
- `LLM_AGENT_MAX_TOOL_RESULT_CHARS`
  - 单次工具结果回填给模型前的最大字符数。

## 6. 向量库（pgvector）
```
VECTOR_STORE=pgvector
VECTOR_SCHEMA=public
VECTOR_TABLE=embedding_store
VECTOR_DISTANCE=cosine|l2|ip
```

## 7. 图谱存储（KG）
```
KG_PROVIDER=postgres
KG_SCHEMA=kg
KG_NAMESPACE=ai4mw
```

## 8. 任务队列与缓存
```
QUEUE_PROVIDER=celery|rq
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}
```

## 9. 统一仿真接口
```
SIM_PROVIDER=hfss|cst|comsol|custom
SIM_ADAPTER_URL=http://localhost:9005
SIM_TIMEOUT_SEC=600
SIM_MAX_PARALLEL=2
```

## 10. Prompt 仓库
```
PROMPT_REPO_PATH=./prompts
PROMPT_DEFAULT_VERSION=latest
PROMPT_ENABLE_INHERIT=true
```

## 11. 追溯与审计
```
TRACE_ENABLE=true
TRACE_STORE=postgres
TRACE_RETENTION_DAYS=365
TRACE_INCLUDE_INTERMEDIATE=false
```

## 12. 日志与监控
```
LOG_LEVEL=INFO
OTEL_ENABLE=false
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

## 13. 安全与多租户
```
AUTH_PROVIDER=django|oidc
AUTH_TOKEN_TTL=3600
TENANT_ISOLATION=project
PII_REDACTION=true
```

## 14. 前端展示
```
UI_THEME=research-saas-dark
UI_ACCENT_COLOR=blue-purple
UI_CARD_LAYOUT=true
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_PLUGIN_REGISTRY=local
GITHUB_CLIENT_ID=Ov23li5EueS9KtZ7zICD
```
说明：
- `NEXT_PUBLIC_API_BASE` 用于前端请求后端 API 的统一入口（可在公网/本地环境切换）。
- 若需要覆盖根目录 `.env`，可在 `frontend/.env.local` 设置同名变量。

## 15. GitHub OAuth
```
GITHUB_CLIENT_ID=Ov23li5EueS9KtZ7zICD
GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET}
GITHUB_CALLBACK=http://127.0.0.1:8000/accounts/github/login/callback/
```
说明：
- `GITHUB_CLIENT_SECRET` 必须放在 `.env`（密钥）。
- OAuth state 参数由 django-allauth 内置处理（用于 CSRF 防护）。
