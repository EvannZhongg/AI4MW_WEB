# AI4MW Web

AI4MW Web 是一个面向电磁与器件研究场景的 Web 项目，当前采用前后端分离结构：

- 后端使用 Django，负责 GitHub OAuth、登录态、会话管理、LLM 对话接口和曲线提取代理。
- 前端使用 Next.js，当前已落地聊天页、聊天搜索页、曲线提取页，以及带历史会话管理的工作台侧栏。
- 仓库中还保留了 `datesheet_rag` 数据手册解析与知识图谱管线代码，但这部分目前仍是“仓库内存在、主应用未接入”的状态。

本 README 以 **2026-03-25 对当前仓库代码的核验结果** 为准，尽量区分：

- 已经接到当前主应用运行链路中的能力
- 仅在仓库中存在、但尚未接入主应用的代码
- 已通过本地命令实际核验的状态

## 1. 进度核验快照

### 1.1 已接入当前主应用的能力

- Django 主项目 `AI4MW_web`
- 聊天应用 `llm_agent`
- GitHub OAuth 登录 `django-allauth`
- Next.js 前端 `frontend`
- 根目录统一配置机制：`config.yaml + .env + 系统环境变量`
- 曲线提取接入层
  - 前端页面：`/curve-extraction`
  - Django 代理接口：`/api/line-charts/health`、`/api/line-charts/extract`
  - 聊天 agent 内的 `line_build` skill，可直接调用独立算法服务

### 1.2 当前代码已经落地、并非只停留在规划中的功能

- 登录态接口：`/api/session`
- 退出接口：`/api/logout`
- 基于数据库会话的聊天历史管理
  - 会话列表
  - 会话详情
  - 会话重命名
  - 会话删除
- 聊天搜索：`/api/chat-search`
- 基于 Server-Sent Events 的流式聊天：`/api/chat`
- 图片附件上传、存储与回放
  - 当前仅支持图片附件
  - 附件存储在 `storage/llm_agent_uploads/`
- LLM 客户端统一封装
  - 兼容 `chat/completions` 与 `responses`
  - 自动接口回退
  - 连接池
  - 超时控制
  - 指数退避重试
  - tool/function calling
- 聊天 agent tool / skill 机制
  - 内置只读工作区工具：`grep`、`glob`、`list_dir`、`read_file`
  - 内置 subagent 分发工具：`spawn_subagent`
  - 当前仓库内已注册的 skill bundle：`line_build`
- 会话标题生成
  - 通过单独的 `SUMMARY_LLM_CONFIG` 调用摘要模型生成标题
- 前端已落地页面
  - `/`：聊天主页
  - `/chat-search`：聊天搜索页
  - `/curve-extraction`：曲线提取页
- 前端已落地交互
  - 侧栏会话历史
  - 会话重命名 / 删除
  - 登录 / 退出
  - 深浅主题切换
  - 侧栏展开/折叠状态持久化
  - Markdown / GFM / 数学公式渲染
  - 曲线提取结果的 SVG 可视化与数据表预览

### 1.3 仓库里已经有代码，但还没有真正接进主应用的部分

- `datesheet_rag/`
  - 已经不是空目录或简单占位，而是带有实际模型、DRF ViewSet、Celery 任务编排、图谱模型和多阶段处理逻辑的独立原型
  - 但当前 **没有加入** `INSTALLED_APPS`
  - 当前 **没有加入** 主路由
  - 当前 `requirements.txt` **没有补齐** 它需要的依赖
  - 当前 Django settings **没有补齐** 它依赖的大量 `DEFAULT_*` 与 `PDF_PARSER_*` 配置项
  - 当前代码还引用了仓库中不存在的 `api.models.Device`
- 前端“研究平台化”目录
  - `pluginRegistry`
  - `workflowCatalog`
  - `promptCatalog`
  - `FeatureCard` / `WorkflowCard`
  - 这些结构和组件文件已经存在，但当前页面没有消费它们，仍属于 UI 架构预留


## 2. 项目结构

```text
AI4MW_web/
├─ AI4MW_web/                  # Django 项目配置、主路由、登录态与基础视图
├─ llm_agent/                  # 会话模型、SSE 聊天接口、附件、LLM 客户端、skill 运行时
├─ line_build/                 # Django 对独立曲线提取服务的代理接口
├─ frontend/                   # Next.js 前端
├─ datesheet_rag/              # 未接入主应用的 datasheet / KG 管线原型
├─ docs/                       # 规划与配置文档
├─ templates/                  # Django 模板（allauth 登录页等）
├─ storage/                    # 本地上传附件目录（运行时产物，不建议提交）
├─ config.yaml                 # 非密钥配置，扁平 key-value
├─ .env.example                # 密钥示例
├─ requirements.txt            # 当前主应用后端依赖
└─ manage.py                   # Django 启动入口
```

## 3. 当前主应用实际功能边界

### 3.1 Django 后端

- 根路径 `/` 当前重定向到登录时记录的前端地址，未记录时回落到前端配置地址
- `/api/session` 返回当前登录态
- `/api/logout` 处理退出登录
- `/api/chat` 提供基于 SSE 的流式聊天
- `/api/conversations` 返回当前用户的会话列表
- `/api/conversations/<id>` 返回会话消息列表
- `/api/conversations/<id>/rename` 重命名会话
- `/api/conversations/<id>/delete` 删除会话
- `/api/chat-search` 对消息内容做数据库纯文本匹配搜索
- `/api/messages/<message_id>/attachments/<attachment_index>` 回放消息图片附件
- `/accounts/github/login/` 使用 GitHub OAuth 登录

### 3.2 `llm_agent` 当前已实现到的程度

- 数据模型
  - `Conversation`
  - `Message`
- 会话状态治理
  - `response_pending_since`
  - 清理重复消息 / 残留尾消息
- 附件能力
  - 支持 multipart 上传
  - 仅保留图片附件
  - 存盘后供聊天模型和附件回放接口复用
- 消息组装
  - 系统提示词由 `llm_agent/services/context_builder.py` 从 `llm_agent/prompts/agent/*.md` 分段编排
  - 当前轮图片会转成 base64 data URL 送入多模态请求
- LLM 运行时
  - 支持 `chat_completions`
  - 支持 `responses`
  - 支持 `auto` 自动切换
  - 支持 tool calling 与多轮 tool 回填
- 当前 tool/skill 生态
  - 已注册只读工具：
    - `grep`
    - `glob`
    - `list_dir`
    - `read_file`
  - 已注册分发工具：
    - `spawn_subagent`
  - 已注册 skill：`line_build`
  - 已注册工具：
    - `line_chart_service_health`
    - `extract_line_chart`
    - `extract_line_chart_by_path`

### 3.3 `line_build` 曲线提取能力

当前已经打通两条接入方式：

- 页面接入
  - 前端 `/curve-extraction` 页面上传图片
  - Django 代理转发到独立算法服务
- 聊天 agent 接入
  - 当前轮上传图片后，agent 可通过 skill 直接调用 `line_build` 服务

需要注意：

- 独立算法服务本体 **不在本仓库内**
- 本仓库保存的是：
  - Django 代理接口
  - skill 封装
  - 前端上传与结果展示页面
  - 接口说明文档

## 4. 前端当前实际状态

### 已落地页面

- `/`
  - 以聊天为核心
  - 支持图片粘贴 / 上传
  - 支持流式回复
  - 支持“Think...”操作轨迹展示
- `/chat-search`
  - 搜索当前用户会话中的消息内容
  - 当前不是向量检索，也不是全文检索，只是普通文本匹配
- `/curve-extraction`
  - 上传图片
  - 查看曲线提取服务健康状态
  - 可视化结构化点集
  - 查看坐标拟合信息
  - 预览逐点数据

### 已做好的工作台能力

- 左侧侧栏
- 聊天快速入口
- 历史会话列表
- 历史会话重命名 / 删除
- 研究模块与工具入口的静态展示
- 深浅主题切换
- 侧栏状态持久化

### 仍属于前端预留结构，而非已接入页面主链路

- `pluginRegistry`
- `workflowCatalog`
- `promptCatalog`
- `FeatureCard`
- `WorkflowCard`
- `SectionHeader`
- `apiClient`

这些文件说明前端已经开始往“研究平台化”和“插件化”组织，但当前首页还没有真正把它们渲染成完整的模块化工作台。

## 5. `datesheet_rag` 模块的真实状态

### 已经存在的代码内容

- DRF ViewSet 与路由
- `PDFParsingTask` 任务模型
- 图谱相关模型
  - `GraphChunk`
  - `GraphNode`
  - `GraphEdge`
  - `NodeSourceLink`
- Celery 10 阶段任务编排
  - 文本解析
  - VLM 图片分析
  - 文本分块
  - 型号抽取/融合
  - 参数提取
  - 参数融合/细化
  - 图片关联
  - 厂商标准化
  - 器件分类
  - 图谱构建
- 多个处理模块
  - `chunking.py`
  - `extraction.py`
  - `param_extraction.py`
  - `param_fusion.py`
  - `image_association.py`
  - `manufacturer_standardization.py`
  - `classification.py`
  - `graph_construction.py`
  - 等

### 当前不能把它视为“已可用主应用能力”的原因

- 没有接入 `INSTALLED_APPS`
- 没有接入主路由
- `requirements.txt` 只有：
  - `Django`
  - `django-allauth`
  - `psycopg`
  - `requests`
- 因此当前主应用缺少它所引用的关键依赖，例如：
  - `djangorestframework`
  - `celery`
  - `openai`
  - `pgvector`
  - `docling`
  - `Pillow`
- 当前 `AI4MW_web/settings.py` 没有定义它大量引用的配置，例如：
  - `DEFAULT_LLM_API_KEY`
  - `DEFAULT_LLM_API_URL`
  - `DEFAULT_EMBEDDING_DIMENSIONS`
  - `PDF_PARSER_*`
- `datesheet_rag/signals.py` 仍引用仓库中不存在的 `api.models.Device`
- 文档规划与代码实现存在差异：
  - 文档与配置多处写的是 MinerU 方向
  - 但当前 `datesheet_rag/utils.py` 的实际解析实现仍在导入 `docling`

### 对它最准确的描述

`datesheet_rag` 更像是一套尚未并入当前主应用的独立原型或分支代码，而不是已经能在本仓库主应用里直接启用的生产模块。

## 6. 技术栈

### 当前主应用实际使用

- Python / Django 5.1
- `django-allauth`
- PostgreSQL 驱动 `psycopg`
- Next.js 15
- React 19
- `react-markdown`
- `remark-gfm`
- `remark-math`
- `rehype-katex`
- `requests`

### 仓库中已引用，但主应用尚未补齐依赖或运行面

- Django REST Framework
- Celery
- `pgvector`
- OpenAI SDK
- `docling`
- MinerU（更多停留在配置/规划层）

## 7. 配置机制

项目当前采用三层覆盖：

1. 系统环境变量
2. 根目录 `.env`
3. 根目录 `config.yaml`

优先级为：

```text
系统环境变量 > .env > config.yaml
```

### 配置文件分工

- `config.yaml`
  - 只放非密钥配置
  - 例如：服务地址、模型名、端口、前端 API 地址
- `.env`
  - 只放密钥
  - 例如：数据库密码、API Key、GitHub Client Secret

### 当前实现上的一个重要限制

根目录 `config.yaml` 不是通过完整 YAML 解析器读取，而是通过“逐行 `KEY: value`”方式读取，因此必须遵守：

- 只使用扁平 key-value
- 不要写嵌套 YAML
- 不要写复杂列表、对象、缩进结构

这个限制同时存在于：

- Django `AI4MW_web/settings.py`
- Next.js `frontend/next.config.mjs`

更多配置说明见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 8. 本地启动

### 8.1 后端

以下以 Linux / macOS 命令为例：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

说明：

- 当前数据库默认指向 PostgreSQL
- 如果本地没有 PostgreSQL，需要先准备对应数据库与账号
- 仓库中的 `db.sqlite3` 不是当前默认数据库

### 8.2 前端

```bash
cd frontend
npm install
npm run dev
```

默认开发地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

前端端口配置：

- `NEXT_PUBLIC_API_BASE=http://localhost:8000`
- `FRONTEND_PORT=auto` 时，`npm run dev` 保持 Next.js 默认行为，3000 被占用时可自动切到 3001。
- 若要手动固定端口，在根目录 `config.yaml` 设置 `FRONTEND_PORT: 3001`，再重启前后端。
- 公网或反向代理部署可直接设置完整的 `FRONTEND_URL=https://your-domain.example`，它会覆盖 `FRONTEND_HOST` / `FRONTEND_PORT`。

### 8.3 GitHub OAuth

如果要启用 GitHub 登录，需要至少配置：

- `GITHUB_CLIENT_ID` 放在 `config.yaml`
- `GITHUB_CLIENT_SECRET` 放在 `.env`
- GitHub OAuth App 回调地址与实际后端地址一致

本地常见回调地址示例：

```text
http://127.0.0.1:8000/accounts/github/login/callback/
```

## 9. 推荐的 Linux 公网部署拓扑

```text
Internet
  |
  v
Nginx / Caddy
  |- /               -> Next.js
  |- /api/           -> Django
  |- /accounts/      -> Django
  |- /admin/         -> Django
  |
  +-> HTTPS / TLS

Next.js            -> 127.0.0.1:3000
Gunicorn + Django  -> 127.0.0.1:8000
PostgreSQL         -> 内网或本机
line_build         -> 127.0.0.1:8004（推荐仅内网）
Redis/Celery       -> 仅在接入 datesheet_rag 后启用
```

### 生产环境建议

- 同域部署前后端，便于 Session / Cookie 管理
- 不要直接把 Django `runserver` 暴露到公网
- 将 `line_build` 独立服务保持在内网，仅由 Django 或 agent 调用
- 真正上线前补齐 CSRF / Cookie / 反向代理安全设置

## 10. 已知限制

- 当前没有自动化测试
- 当前没有统一的后端 API 文档
- 前端 `npm run lint` 尚未初始化完成
- 当前 Windows 环境下 `npm run build` 仍报 `spawn EPERM`
- 当前 CORS 由视图层手工写响应头，尚未形成完整生产策略
- `datesheet_rag` 代码与主应用存在配置、依赖和外部服务断层
- `pluginRegistry` / `workflowCatalog` / `promptCatalog` 仍未接入真实页面主链路

## 11. 建议的下一步迭代顺序

如果项目接下来以“继续把当前主应用做稳”为目标，建议顺序如下：

1. 完成前端 ESLint 初始化与构建问题排查
2. 补齐 Django 生产配置与反向代理部署方案
3. 为聊天主链路补最小测试
4. 决定 `plugin/workflow/prompt` 架构是接入首页还是保留预留
5. 再单独梳理 `datesheet_rag` 是否要并入当前主应用

如果项目接下来以“接入 datasheet / KG 管线”为目标，建议顺序如下：

1. 补齐 `requirements.txt`
2. 补齐 `settings.py` 中的 `DEFAULT_*` / `PDF_PARSER_*`
3. 明确解析路线到底采用 MinerU 还是 Docling
4. 接入 `INSTALLED_APPS` 与主路由
5. 部署 Redis、Celery Worker、向量库与相关外部服务

## 12. 相关文档

- [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)
- [docs/FRONTEND_PLAN.md](docs/FRONTEND_PLAN.md)
- [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md)
