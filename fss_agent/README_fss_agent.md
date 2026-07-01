# FSS Extraction Agent

本项目用于自动处理 FSS（Frequency Selective Surface）论文数据：读取每篇论文目录中的 `structured_sections.json` 和 `imgs` 图片资源，调用大模型抽取 FSS 结构、频段、材料、性能指标等信息，然后自动写入 PostgreSQL 数据库和 NebulaGraph 知识图谱。

## 功能概览

- 自动扫描论文目录。
- 自动读取 `structured_sections.json`。
- 自动读取 `imgs/image`、`imgs/table`，并将 `imgs` 下所有图片资产路径写入数据库和图谱。
- 调用 OpenRouter 模型完成图片信息抽取和文本信息抽取。
- 为每篇论文生成：
  - `image_extraction.json`
  - `fss_extraction.json`
- 在根目录生成汇总表：
  - `extraction_report.csv`
- 自动创建并写入 PostgreSQL 数据库 `fss`。
- 自动创建并写入 NebulaGraph 图空间 `fss_kg`。

## 推荐目录结构

每篇论文建议放在一个独立目录下：

```text
test3/
  run_fss_agent.py
  requirements.txt
  fss_agent/
  Paper_A/
    structured_sections.json
    Paper_A.md
    imgs/
      image/
      table/
      chart/
      formula/
  Paper_B/
    structured_sections.json
    Paper_B.md
    imgs/
      image/
      table/
```

主流程只会处理包含 `structured_sections.json` 的子目录。

## 环境要求

- Python 3.12 推荐。
- PostgreSQL，本项目默认连接：

```text
postgresql://postgres:postgres@localhost:5432/fss
```

- NebulaGraph，本项目默认连接：

```text
host: 127.0.0.1
port: 9669
user: root
password: nebula
space: fss_kg
```

- OpenRouter API Key。可以通过环境变量设置：

```powershell
$env:OPENROUTER_API_KEY="你的 OpenRouter API Key"
```

## 安装依赖

常规安装：

```powershell
py -3.12 -m pip install -r requirements.txt
```

如果 Windows 用户目录没有写入权限，可以安装到项目本地目录：

```powershell
py -3.12 -m pip install --target .deps -r requirements.txt
```

本项目包含 `run_fss_agent.py`，会自动把 `.deps` 加入依赖搜索路径。

## 一键运行全流程

在项目根目录运行：

```powershell
py -3.12 run_fss_agent.py --root .
```

运行后会自动完成：

```text
扫描论文目录
-> 图片信息抽取
-> 文本/FSS 信息抽取
-> 写 image_extraction.json
-> 写 fss_extraction.json
-> 写 PostgreSQL
-> 写 NebulaGraph
-> 写 extraction_report.csv
```

如果只想测试抽取，不写 PostgreSQL：

```powershell
py -3.12 run_fss_agent.py --root . --skip-postgres
```

如果只想测试抽取，不写 NebulaGraph：

```powershell
py -3.12 run_fss_agent.py --root . --skip-nebula
```

降低并发，适合 API 限速或本机性能较弱时：

```powershell
py -3.12 run_fss_agent.py --root . --paper-concurrency 1
```

## 配置项

主要配置在 `fss_agent/config.py` 中，也可以用环境变量覆盖。

| 配置 | 默认值 | 用途 |
|---|---|---|
| `OPENROUTER_API_KEY` | 环境变量 | OpenRouter 调用密钥 |
| `FSS_POSTGRES_DATABASE` | `fss` | PostgreSQL 数据库名 |
| `FSS_POSTGRES_ADMIN_DSN` | `postgresql://postgres:postgres@localhost:5432/postgres` | 用来自动创建数据库 |
| `FSS_POSTGRES_DSN` | `postgresql://postgres:postgres@localhost:5432/fss` | 用来写入业务数据 |
| `FSS_NEBULA_HOST` | `127.0.0.1` | NebulaGraph graphd 地址 |
| `FSS_NEBULA_PORT` | `9669` | NebulaGraph graphd 端口 |
| `FSS_NEBULA_USER` | `root` | NebulaGraph 用户 |
| `FSS_NEBULA_PASSWORD` | `nebula` | NebulaGraph 密码 |
| `FSS_NEBULA_SPACE` | `fss_kg` | 图空间名称 |
| `FSS_PERSIST_POSTGRES` | `1` | 是否写 PostgreSQL |
| `FSS_PERSIST_NEBULA` | `1` | 是否写 NebulaGraph |

示例：

```powershell
$env:FSS_POSTGRES_DSN="postgresql://postgres:postgres@localhost:5432/fss"
$env:FSS_NEBULA_PASSWORD="nebula"
py -3.12 run_fss_agent.py --root .
```

## 数据库结构

程序会自动创建或迁移 PostgreSQL 表：

| 表名 | 内容 |
|---|---|
| `papers` | 论文基础信息：名称、目录、标题、作者 |
| `sections` | 论文分节文本 |
| `assets` | 图片、表格、图表、公式等资源路径 |
| `extraction_reports` | 图片抽取 JSON、文本抽取 JSON、token 统计 |
| `fss_structures` | 抽取到的 FSS 结构 |
| `materials` | 基板材料、导体材料 |
| `frequency_bands` | 频段、中心频率、工作频率、带宽等 |
| `performance_metrics` | 入射角、Q 值、核心性能、其他参数 |

图片不直接存二进制，数据库中保存绝对路径，便于后续查看原图和追溯来源。

## 知识图谱结构

NebulaGraph 会自动创建图空间 `fss_kg`。

Tag：

| Tag | 内容 |
|---|---|
| `Paper` | 论文 |
| `Section` | 章节 |
| `Asset` | 图片/表格/图表/公式资产 |
| `ExtractionReport` | 抽取结果 |
| `FSSStructure` | FSS 结构 |
| `Material` | 材料 |
| `FrequencyBand` | 频段 |
| `PerformanceMetric` | 性能指标 |

Edge：

| Edge | 含义 |
|---|---|
| `HAS_SECTION` | 论文包含章节 |
| `HAS_ASSET` | 论文包含图片资源 |
| `HAS_IMAGE` | 论文包含结构图片 |
| `HAS_TABLE` | 论文包含表格图片 |
| `HAS_REPORT` | 论文对应抽取报告 |
| `PROPOSES_STRUCTURE` | 论文提出 FSS 结构 |
| `USES_MATERIAL` | FSS 结构使用材料 |
| `OPERATES_AT` | FSS 结构工作频段 |
| `HAS_PERFORMANCE` | FSS 结构具有性能指标 |
| `MENTIONED_IN` | 预留关系，用于表示实体出现在哪个章节 |

在 NebulaGraph Studio 中可以执行：

```ngql
USE fss_kg;
MATCH (p:Paper) RETURN p LIMIT 10;
MATCH (p:Paper)-[:PROPOSES_STRUCTURE]->(s:FSSStructure) RETURN p, s LIMIT 20;
MATCH (p:Paper)-[:HAS_ASSET]->(a:Asset) RETURN p, a LIMIT 20;
```

## 代码文件说明

| 文件 | 作用 |
|---|---|
| `run_fss_agent.py` | 推荐启动入口；自动加载 `.deps` 后运行主流程 |
| `sitecustomize.py` | 尝试自动把 `.deps` 加入 Python 搜索路径 |
| `requirements.txt` | 项目依赖清单 |
| `fss_agent/agent.py` | 总调度器：扫描论文、调用抽取模块、写 JSON、写数据库和图谱 |
| `fss_agent/config.py` | 所有模型、并发、输出文件名、数据库和图谱连接配置 |
| `fss_agent/client.py` | OpenRouter API 客户端；负责 JSON 模型调用、解析和截断重试 |
| `fss_agent/image_extractor.py` | 图片抽取模块；读取 `imgs/image` 和 `imgs/table`，压缩图片后发送给视觉模型 |
| `fss_agent/text_extractor.py` | 文本抽取模块；读取 `structured_sections.json`，融合图片抽取结果，输出 FSS 信息 JSON |
| `fss_agent/report_writer.py` | 汇总所有论文结果，生成 `extraction_report.csv` |
| `fss_agent/persistence_models.py` | 将提取结果转换成统一的持久化数据结构 |
| `fss_agent/postgres_store.py` | PostgreSQL 自动建库、建表、迁移和 upsert 写入 |
| `fss_agent/nebula_store.py` | NebulaGraph 自动建图空间、建 Tag/Edge 和写入点边 |
| `parse_grobid_markdown.py` | 将 GROBID/Markdown 论文解析成结构化 JSON |
| `organize_imgs.py` | 将 `imgs` 下图片按文件名移动到 `chart/image/formula/table` 子目录 |
| `filter_structured_sections.py` | 删除摘要、关键词、引言、结论、参考文献等不需要抽取的章节 |

## 预处理脚本

### 1. 解析 Markdown

```powershell
py -3.12 parse_grobid_markdown.py "论文目录/Paper.md" -o "论文目录/structured_sections.json" --simple --pretty
```

### 2. 整理图片目录

```powershell
py -3.12 organize_imgs.py "论文目录"
```

会把图片移动到：

```text
imgs/chart
imgs/image
imgs/formula
imgs/table
```

### 3. 过滤无关章节

```powershell
py -3.12 filter_structured_sections.py "论文目录"
```

会直接修改对应的 `structured_sections.json`。

## 常见问题

### 1. `No module named pip`

当前机器的 Python 可能没有安装 pip。建议使用已安装 pip 的 Python 3.12：

```powershell
py -3.12 -m pip --version
```

### 2. `Permission denied` 或 `拒绝访问`

可以把依赖安装到项目本地：

```powershell
py -3.12 -m pip install --target .deps -r requirements.txt
py -3.12 run_fss_agent.py --root .
```

### 3. PostgreSQL 连接失败

确认 PostgreSQL 已启动，且密码正确。默认密码按本项目当前配置为 `postgres`。

可以设置：

```powershell
$env:FSS_POSTGRES_ADMIN_DSN="postgresql://postgres:postgres@localhost:5432/postgres"
$env:FSS_POSTGRES_DSN="postgresql://postgres:postgres@localhost:5432/fss"
```

### 4. NebulaGraph Studio 可以打开，但程序连接失败

Studio 是网页管理界面，程序连接的是后端 graphd 服务。请确认：

```text
127.0.0.1:9669
root / nebula
```

### 5. 模型返回 JSON 不完整

`fss_agent/client.py` 已加入 JSON 解析失败自动重试。仍然失败时，可以在 `fss_agent/config.py` 中继续增大：

```python
image_max_tokens
text_max_tokens
```
