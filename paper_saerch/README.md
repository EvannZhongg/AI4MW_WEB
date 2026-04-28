# Agentic-Scholar

一个面向论文检索场景的独立后端服务原型。当前仓库已经跑通多源论文召回、`quick` / `deep` 两条检索链路、基础 API、Provider 运行时控制、Redis 缓存/限流、调试脚本，以及一个独立前端调试页。

当前项目更适合定位为：

- 一个可运行的论文检索后端 MVP
- 一个后续可被 Django、前端页面或 agent skill 调用的统一检索核心

## 当前进度

更新日期：2026-04-03

已经落地的核心能力：

- FastAPI 服务已可启动
- 已提供 `GET /v1/health`、`GET /v1/providers`、`GET /v1/providers/status`
- 已提供 `POST /v1/search/quick`、`POST /v1/search/deep`
- Quick Search 已实现 `intent planning -> 多源召回 -> 去重 -> hybrid rerank`
- Deep Search 已实现 `criteria-aware planning -> query bundle -> 多源召回 -> heuristic prefilter -> 可选 LLM judge -> hard prune`
- 已接入 OpenAlex、Semantic Scholar、CORE、Crossref、IEEE Xplore、Unpaywall、arXiv 七个 connector
- 已落地 `provider runtime/policy`，支持按 provider 配置缓存、批处理、串行化和限流
- 已接入 Redis 作为共享缓存与分布式请求控制后端，并支持本地退化
- 已提供独立前端调试页，可直接调用后端 API 或导入历史 JSON 结果

当前尚未落地的主要能力：

- `POST /v1/search/plan`
- `POST /v1/search/retrieve`
- `POST /v1/search/judge`
- `POST /v1/resolve/fulltext`
- 自动化测试
- 正式产品前端和 Django 集成层

## 仓库结构

```text
app/
  api/          FastAPI 路由
  connectors/   各数据源接入
  domain/       Pydantic schema
  llm/          LLM / Embedding 适配
  services/     quick/deep、planner、去重、provider runtime
config/
  config.yaml   主配置
docs/           数据源调研与流程文档
frontend/       独立前端调试页
scripts/        probe 与本地检索脚本
```

几个关键文件：

- [app/main.py](app/main.py)
- [app/api/routes.py](app/api/routes.py)
- [app/services/quick_channel.py](app/services/quick_channel.py)
- [app/services/deep_channel.py](app/services/deep_channel.py)
- [app/services/search_common.py](app/services/search_common.py)
- [app/services/provider_runtime.py](app/services/provider_runtime.py)
- [config/config.yaml](config/config.yaml)

## 环境要求

- Python `3.10+`
- 可访问外部论文源 API
- 可选 Redis
  默认配置会尝试连接 `127.0.0.1:6379`；如果 Redis 不可用，部分 provider 会退化为单进程本地请求控制

安装依赖：

```bash
pip install -r requirements.txt
```

## 配置

1. 复制环境变量模板：

```bash
copy .env.example .env
```

2. 按你实际拥有的凭证填写 `.env`：

- `OPENALEX_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `CORE_API_KEY`
- `CROSSREF_MAILTO`
- `CROSSREF_PLUS_API_TOKEN`
- `UNPAYWALL_EMAIL`
- `IEEE_XPLORE_API_KEY`
- `LLM_API_KEY`
- `EMBED_API_KEY`
- `REDIS_USERNAME`
- `REDIS_PASSWORD`

3. 根据需要检查 [config/config.yaml](config/config.yaml)：

- `sources.<provider>.enabled`
- `sources.<provider>.public_enabled`
- `sources.<provider>.supports_quick`
- `sources.<provider>.supports_deep`
- `sources.<provider>.runtime.*`
- `retrieval.quick.*`
- `retrieval.deep.*`
- `llm.*`
- `embedding.*`

说明：

- 非敏感配置放在 `config/config.yaml`
- 敏感信息通过 `.env` 注入
- LLM 和 Embedding 当前通过 OpenAI 兼容 HTTP 接口调用，不依赖专门 SDK

## 启动后端

```bash
uvicorn app.main:app --reload
```

启动后可访问：

- `http://127.0.0.1:8000/v1/health`
- `http://127.0.0.1:8000/v1/providers`
- `http://127.0.0.1:8000/v1/providers/status`

## API 使用

### 1. 查看 provider 配置摘要

```bash
curl http://127.0.0.1:8000/v1/providers
```

### 2. 执行 Quick Search

```bash
curl -X POST http://127.0.0.1:8000/v1/search/quick ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"graph rag for scientific retrieval\",\"public_only\":true}"
```

### 3. 执行 Deep Search

```bash
curl -X POST http://127.0.0.1:8000/v1/search/deep ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"找同时结合 text retriever 和 graph retriever 的论文\",\"public_only\":true}"
```

当前 `SearchRequest` 已支持：

- `query`
- `sources`
- `limit_per_source`
- `public_only`
- `llm_top_n`
- `enable_llm`
- `enable_intent_planner`

返回结构会包含：

- `rewritten_query`
- `intent`
- `query_bundle`
- `results`
- `raw_recall_count`
- `deduped_count`
- `finalized_count`

## 脚本

### 1. 检查 provider 配置与 live probe

```bash
python scripts/run_provider_probes.py
```

### 2. 快速跑一轮 quick search

```bash
python scripts/run_quick_search.py transformer
```

### 3. 用统一脚本运行 quick 或 deep

```bash
python scripts/run_search.py "transformer" --mode quick
python scripts/run_search.py "transformer" --mode deep
```

常用参数：

- `--mode quick|deep`
- `--limit-per-source 8`
- `--sources openalex,semanticscholar,core`
- `--public-only`
- `--disable-llm`
- `--disable-intent-planner`
- `--llm-top-n 8`
- `--raw`
- `--no-save`

说明：

- 运行结果默认会保存到 `scripts/outputs/`
- `run_search.py` 会输出 `raw_recall_count / deduped_count / finalized_count`

## 独立前端调试页

当前仓库包含一个完全独立的调试页面，不挂载在 FastAPI 应用内部：

- 页面入口：[frontend/index.html](frontend/index.html)
- 本地代理：[frontend/dev_server.py](frontend/dev_server.py)

推荐启动方式：

1. 启动后端：

```bash
uvicorn app.main:app --reload
```

2. 启动前端代理：

```bash
python frontend/dev_server.py
```

3. 打开浏览器：

```text
http://127.0.0.1:8080
```

这个页面适合做三件事：

- 输入 query 直接调 `/search/quick` 或 `/search/deep`
- 观察 `intent`、`criteria`、`query_bundle`、结果解释和 trace
- 导入 `scripts/outputs/*.json` 做纯展示调试

## 当前实现边界

当前代码已经不是纯设计稿，但仍然是 MVP，使用时要注意：

- Quick 已有 hybrid rerank，但仍是轻量方案，不是成熟学习排序器
- Deep 已支持 criterion-aware judge，但硬过滤条件目前仍较少，主要依赖 `year_from`、`year_to`、`is_oa`
- 去重目前优先使用 DOI；缺 DOI 时退化到 `title + year + first_author`
- 多语言检索已补英文 rewrite、Unicode-aware normalization 和 CJK fallback tokenization，但整体仍偏英文论文源场景
- 还没有自动化测试，当前主要依赖 probe、脚本和人工 smoke test

## 相关文档

- 架构收敛文档：[Agentic_Scholar_architecture_plan_zh.md](Agentic_Scholar_architecture_plan_zh.md)
- Quick / Deep 流程说明：[docs/quick_deep_search_architecture_zh.md](docs/quick_deep_search_architecture_zh.md)
- 各数据源调研文档：`docs/*_api_research_zh.md`
