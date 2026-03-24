# AI4MW Web

AI4MW Web 是一个面向电磁与器件研究场景的 Web 项目，当前采用前后端分离结构：

- 后端使用 Django，负责登录态、GitHub OAuth、会话管理和 LLM 对话流式接口。
- 前端使用 Next.js，提供研究工作台式聊天界面。
- 仓库内还保留了一套 `datesheet_rag` 数据手册解析与知识图谱管线代码，但这部分目前尚未接入主应用。

本 README 以“当前代码实际状态”为准，同时补充后续部署到 Linux 服务器并转发到公网时需要注意的事项。

## 1. 当前状态

### 已接入并可继续演进的部分

- Django 主项目 `AI4MW_web`
- 聊天应用 `llm_agent`
- GitHub OAuth 登录 `django-allauth`
- Next.js 前端 `frontend`
- 根目录统一配置机制：`config.yaml + .env + 系统环境变量`

### 仓库中存在但尚未完全内聚到主应用代码仓的部分

- `datesheet_rag/`
  - 包含 DRF、Celery、pgvector、OpenAI 客户端等相关代码
  - 当前未加入 `INSTALLED_APPS`
  - 当前未加入主路由
  - 当前 `requirements.txt` 也未完整声明它所需依赖
- `line_build/`
  - 当前保存曲线提取算法服务的接口文档
  - Django 已增加对 `8004` 算法服务的代理接入
  - 算法服务本体仍是独立进程，不在本仓库内直接运行

### 部署到公网前必须意识到的现状

- Django 已支持从 `config.yaml/.env/环境变量` 读取 `DEBUG`、`ALLOWED_HOSTS`、`TIME_ZONE`、`LANGUAGE_CODE` 与 `DJANGO_SECRET_KEY`
- LLM 调用已改为统一客户端，兼容 `chat/completions` 与 `responses`，并内置连接池、超时、指数退避重试与可选额外转发头
- 当前接口自行写了简单 CORS 响应头，尚未形成严格的生产环境安全策略
- `datesheet_rag` 相关代码依赖的 Redis、Celery、DRF、pgvector、MinerU 等基础设施尚未在主项目中打通
- 前端尚未完成 ESLint 初始化；`npm run lint` 会进入交互配置

结论：当前仓库适合继续本地开发和文档梳理，但如果要正式部署到 Linux 公网环境，建议先完成一轮生产化改造。

## 2. 项目结构

```text
AI4MW_web/
├─ AI4MW_web/                  # Django 项目配置、路由、认证适配
├─ llm_agent/                  # 会话与流式聊天 API
├─ frontend/                   # Next.js 前端
├─ datesheet_rag/              # 预留的数据手册解析与知识图谱管线
├─ docs/                       # 规划与配置文档
├─ templates/                  # Django 模板（allauth 登录页等）
├─ config.yaml                 # 非密钥配置，扁平 key-value
├─ .env.example                # 密钥示例
├─ requirements.txt            # 当前后端依赖
└─ manage.py                   # Django 启动入口
```

## 3. 当前功能边界

### Django 后端

- 根路径 `/` 当前会重定向到 `FRONTEND_URL`
- `/api/session` 返回当前登录态
- `/api/logout` 处理退出登录
- `/api/chat` 提供基于 Server-Sent Events 的流式聊天
- `/api/conversations`、`/api/conversations/<id>` 负责会话历史
- `/accounts/github/login/` 使用 GitHub OAuth 登录

### Next.js 前端

- 聊天工作台 UI
- 常驻左侧功能栏与跨页面导航
- 会话历史查看、重命名、删除
- 登录入口和退出逻辑
- Markdown / GFM / 数学公式渲染
- 曲线提取页面：图片上传、结果总览、折线可视化、逐点数据预览
- 当前界面里展示了一些研究能力模块与工具卡片，但多数仍属于展示层占位

### `datesheet_rag` 模块

这部分代码更接近“待接入的后续能力”，不是当前线上主链路：

- 包含 PDF 上传、分块、参数抽取、图片关联、厂商标准化、知识图谱构建等 10 阶段任务链
- 依赖 Celery、Redis、pgvector、DRF、MinerU、OpenAI SDK 等
- 当前如果直接接入主应用，会因为配置项与依赖不完整而继续报错或缺功能

### `line_build` 曲线提取能力

当前已接入的方式是：

- 前端通过 `/curve-extraction` 页面上传图片
- Django 通过 `/api/line-charts/health` 与 `/api/line-charts/extract` 代理算法服务
- 算法服务默认地址来自 `LINE_BUILD_BASE_URL`

## 4. 技术栈

### 已实际使用

- Python / Django 5.1
- `django-allauth`
- PostgreSQL 驱动 `psycopg`
- Next.js 15
- React 19
- `react-markdown`、`remark-gfm`、`remark-math`、`rehype-katex`

### 规划中或局部代码已引用

- Django REST Framework
- Celery + Redis
- `pgvector`
- OpenAI 兼容接口
- MinerU 文档解析服务

## 5. 配置机制

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
  - 例如：服务地址、模型名、端口、域名、前端 API 地址
- `.env`
  - 只放密钥
  - 例如：数据库密码、API Key、GitHub Client Secret

### 当前实现上的一个重要限制

根目录 `config.yaml` 不是通过完整 YAML 解析器读取，而是通过“逐行 `KEY: value`”方式读取。因此必须遵守：

- 只使用扁平 key-value
- 不要写嵌套 YAML
- 不要写复杂列表、对象、缩进结构

如果后续要升级成真正的分层配置系统，需要先统一后端和前端的解析方式。

更多配置说明见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 6. 本地启动

### 6.1 后端

以下以 Linux / macOS 命令为例：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

然后按需修改：

- `config.yaml`
- `.env`

执行迁移并启动：

```bash
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

说明：

- 当前数据库默认指向 PostgreSQL
- 如果本地没有 PostgreSQL，需要先准备对应数据库与账号
- 仓库中的 `db.sqlite3` 目前不是默认运行数据库，可视为历史文件或本地遗留文件

### 6.2 前端

```bash
cd frontend
npm install
npm run dev
```

默认开发地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

确保以下配置相互匹配：

- `FRONTEND_URL=http://localhost:3000`
- `NEXT_PUBLIC_API_BASE=http://localhost:8000`

### 6.3 GitHub OAuth

如果要启用 GitHub 登录，需要至少配置：

- `GITHUB_CLIENT_ID` 放在 `config.yaml`
- `GITHUB_CLIENT_SECRET` 放在 `.env`
- GitHub OAuth App 回调地址需要与实际后端地址一致

本地常见回调地址示例：

```text
http://127.0.0.1:8000/accounts/github/login/callback/
```

## 7. 推荐的 Linux 公网部署拓扑

### 推荐拓扑

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
Redis              -> 仅在启用异步任务后接入
MinerU             -> 仅在启用 datasheet 管线后接入
```

### 为什么建议这样部署

- 前端和后端都只监听内网地址，不直接暴露服务端口
- 统一由 Nginx / Caddy 做 HTTPS、反向代理和公网入口
- 同域部署时，前端请求和 Django Session/Cookie 更容易管理
- 后续启用 `/api/`、`/accounts/`、`/admin/` 以外的路径也更清晰

### 生产环境建议的域名策略

优先使用同域转发，例如：

- 前端页面：`https://ai4mw.example.com/`
- Django API：`https://ai4mw.example.com/api/...`
- OAuth：`https://ai4mw.example.com/accounts/github/login/callback/`

在这种模式下，建议：

- `FRONTEND_URL=https://ai4mw.example.com`
- `NEXT_PUBLIC_API_BASE=https://ai4mw.example.com`

## 8. 上线前需要补齐的生产化工作

以下事项建议在真正转发到公网之前完成：

### 必做

- 明确 `CSRF_TRUSTED_ORIGINS`
- 将 Session / CSRF Cookie 切换到 HTTPS 安全设置
- 用 Gunicorn 或 uWSGI 托管 Django，而不是 `runserver`
- 让前端完成正式 `build` 流程验证
- 初始化 ESLint 或改用标准 ESLint CLI

### 如果要启用 `datesheet_rag`

- 将 `datesheet_rag` 正式接入 `INSTALLED_APPS`
- 接入主路由
- 在 `requirements.txt` 中补齐 DRF、Celery、Redis、pgvector、openai 等依赖
- 为 Django settings 补齐 `MEDIA_ROOT`、Celery、向量维度、解析服务等配置
- PostgreSQL 启用 `pgvector`
- 部署 Redis、Celery Worker、MinerU

## 9. 已知限制

- 当前没有自动化测试
- 当前没有统一的后端 API 文档
- 前端 `npm run lint` 尚未初始化
- 当前 Windows 环境下执行 `npm run build` 出现 `spawn EPERM`，尚未完成构建验证
- `datesheet_rag` 代码与主应用存在配置和依赖断层，不能视为已可用能力

## 10. 建议的后续迭代顺序

如果项目接下来要以 Linux 公网部署为目标推进，建议优先顺序如下：

1. 完成 Django 生产配置改造
2. 固化 Nginx + Gunicorn + Next.js 的部署方式
3. 补齐前端 lint / build 流程
4. 引入基础测试与回归校验
5. 再决定是否接入 `datesheet_rag` 整套异步管线

## 11. 相关文档

- [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)
- [docs/FRONTEND_PLAN.md](docs/FRONTEND_PLAN.md)
- [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md)
