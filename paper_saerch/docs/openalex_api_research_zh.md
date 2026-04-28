# OpenAlex API 调研笔记

更新日期：2026-03-28

这份文档基于 OpenAlex 当前官方开发文档整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- OpenAlex 现在支持哪些检索方式
- 是否支持 SQL / NLP / 语义搜索
- 能检索哪些字段，哪些字段可以过滤
- 是否需要 API Key
- 分页、限流、费用、返回字段限制分别是什么
- 后续做 agent 时推荐怎样接入

## 结论先看

OpenAlex 当前对外主接口是 REST API，不提供托管 SQL 查询接口。

它支持的检索能力主要包括：

- 单条实体查询：按 OpenAlex ID 或部分外部 ID 获取单条记录
- 列表查询 + 结构化过滤：`filter=...`
- 关键词检索：`search=...`
- 非词干精确检索：`search.exact=...`
- 布尔检索：`AND` / `OR` / `NOT`
- 短语检索、邻近检索、通配符、模糊检索
- 语义检索：`search.semantic=...`，当前是 beta
- 自动补全：`/autocomplete/...`
- 聚合统计：`group_by=...`
- 随机采样：`sample=...`
- 大规模离线获取：Snapshot、CLI、内容下载

关于你问的“SQL / NLP”：

- `SQL`：官方没有提供在线 SQL endpoint。这是基于当前官方只公开 REST API、Snapshot、CLI、内容下载等访问方式做出的结论。如果你要 SQL，通常需要下载 snapshot 后自行导入 PostgreSQL / ClickHouse / Elasticsearch 等系统。
- `NLP`：支持两类能力。
  - 一类是文本检索增强：关键词、布尔、短语、模糊、语义检索。
  - 另一类是 `/text` aboutness 接口，用你的标题/摘要打 topics / keywords / concepts 标签。但当前官方新文档已把 `/text` 标为 deprecated，不建议把它作为生产主路径。

## 文档入口现状

OpenAlex 目前存在两套官方文档入口：

- 新主文档：`https://developers.openalex.org`
- 旧文档入口：`https://docs.openalex.org`

多数页面已经跳转到新站，但 `/text` 等个别说明仍能在旧站看到旧表述。因此开发时建议优先以 `developers.openalex.org` 为准。

## 1. 当前支持的访问与检索方式

### 1.1 单条实体查询

适合：

- 已知论文 ID、DOI、ORCID、ISSN 等唯一标识
- 做“详情页”或补齐 metadata

示例：

```text
GET /works/W2741809807
GET /works/doi:10.1038/nature12373
GET /authors/orcid:0000-0002-1825-0097
GET /sources/issn:2041-1723
```

特点：

- 单条查询成本最低，当前官方定价页写的是 free
- 很适合 agent 在重排后对候选论文做补充拉取

### 1.2 列表查询 + 结构化过滤

适合：

- 做标准论文检索
- 做 faceted search
- 做作者、机构、期刊、主题约束

核心参数：

```text
GET /works?filter=publication_year:2024,is_oa:true
```

官方支持：

- AND：逗号分隔
- OR：同一字段内用 `|`
- NOT：值前加 `!`
- 比较：`>`, `<`
- 区间：部分字段可直接写范围，或用 `from_...` / `to_...`

示例：

```text
/works?filter=publication_year:2024,is_oa:true
/works?filter=type:article|book
/works?filter=country_code:!us
/works?filter=cited_by_count:>100
/works?filter=from_publication_date:2024-01-01,to_publication_date:2024-12-31
```

### 1.3 关键词检索 `search`

适合：

- 用户输入自然关键词
- 标题 / 摘要 / 全文匹配

示例：

```text
/works?search=graph neural networks for drug discovery
```

当前官方说明：

- `search` 是全文检索主入口
- 搜索结果默认按 `relevance_score` 排序
- 搜索会做 stemming 和 stop-word removal

### 1.4 非词干精确检索 `search.exact`

适合：

- 你不想让单词词形被归并
- 例如区分 `surgery` 和 `surgeries`

示例：

```text
/works?search.exact=surgery
```

说明：

- 同一次请求里只能使用一个搜索参数：`search`、`search.exact` 或 `search.semantic`

### 1.5 布尔检索

适合：

- 高级检索
- 用户自定义组合条件

示例：

```text
/works?search=(elmo AND "sesame street") NOT (cookie OR monster)
```

规则：

- 操作符必须大写：`AND`、`OR`、`NOT`
- 不写操作符时，词之间默认按 `AND` 处理
- 可以配合括号和引号

### 1.6 短语 / 邻近 / 通配符 / 模糊检索

示例：

```text
/works?search="fierce creatures"
/works?search="climate change"~5
/works?search=machin*
/works?search=machin~1
```

说明：

- 双引号：短语匹配
- `"..."~N`：邻近检索
- `*`、`?`：通配符
- `~1`、`~2`：模糊检索

### 1.7 语义检索 `search.semantic`

适合：

- 用户给出一句自然语言需求
- 需要找“语义相关”而不是“关键词完全重合”的论文

示例：

```text
/works?search.semantic=machine learning in healthcare
```

当前官方说明：

- 这是 beta 能力
- 基于 embedding 做相似度检索
- 当前文档写明：1 request/sec
- 每次最多返回 50 条结果

适用建议：

- 适合召回首轮候选集
- 后续再叠加结构化过滤、rerank、详情拉取

### 1.8 自动补全 `/autocomplete`

适合：

- 搜索框 typeahead
- 用户输入作者 / 机构 / 期刊 / topic 名称时做快速候选提示

格式：

```text
/autocomplete/<entity_type>?q=<query>
```

支持的 `entity_type`：

- `works`
- `authors`
- `sources`
- `institutions`
- `concepts`
- `publishers`
- `funders`

示例：

```text
/autocomplete/institutions?q=flori
```

特点：

- 官方文档写明一般约 200ms
- 返回字段较轻：`id`、`display_name`、`hint`、`external_id` 等
- 还可以叠加 `filter` 和 `search`

### 1.9 聚合统计 `group_by`

适合：

- 分面统计
- 年份分布、类型分布、topic 分布
- 检索结果统计概览

示例：

```text
/works?filter=publication_year:2024&group_by=topics.id
```

### 1.10 随机采样 `sample`

适合：

- 调试
- 构建样本集
- 小规模探索

示例：

```text
/works?sample=100&seed=42
```

### 1.11 Aboutness `/text`

这是你提到 NLP 时最容易想到的接口，但需要特别注意它的状态。

当前官方文档状态并不完全一致：

- 新开发文档里，`Tag Aboutness` 页面将 `/text/topics` 标为 deprecated，并建议使用 `/text/keywords`
- 同时 LLM Quick Reference 进一步把 `/text` 总体标成 “DEPRECATED, do not use”
- 旧文档里还保留“experimental endpoint”的表述

因此我的建议是：

- 可以把 `/text` 当作辅助实验能力看待
- 不建议把它作为生产论文检索 agent 的核心入口
- 如果要做 production，优先使用 `search`、`filter`、`search.semantic`、`autocomplete`

## 2. OpenAlex 支持哪些实体

当前主要实体包括：

- `works`
- `authors`
- `sources`
- `institutions`
- `topics`
- `keywords`
- `publishers`
- `funders`
- `awards`

另外还有：

- `domains`
- `fields`
- `subfields`
- `sdgs`
- `countries`
- `continents`
- `languages`
- `work-types`
- `source-types`
- `institution-types`
- `licenses`
- `concepts`（deprecated）

对论文检索 agent 来说，最核心的通常是：

- `works`：论文主索引
- `authors`：作者检索与 author filter
- `institutions`：机构检索与 affiliation filter
- `sources`：期刊 / 会议 / 仓储
- `topics` / `keywords`：学科主题与标签
- `funders` / `awards`：基金与项目约束

## 3. 文本检索能搜哪些字段

### 3.1 总览

根据当前官方 Search 指南：

| 实体 | `search` 默认检索字段 |
| --- | --- |
| `works` | `title`, `abstract`, `fulltext` |
| `authors` | `display_name`, `display_name_alternatives` |
| `sources` | `display_name`, `alternate_titles`, `abbreviated_title` |
| `institutions` | `display_name`, `display_name_alternatives`, `display_name_acronyms` |
| `topics` / `keywords` | `display_name`, `description` |

### 3.2 旧式字段级 `.search` 过滤器

官方新文档明确说明：

- `filter=field.search:...` 这种写法仍可用
- 但已经不推荐作为主方式
- 推荐优先使用 `search=...`

不过对 agent 来说，字段级搜索仍然很有价值，因为它可以表达“只搜标题”“只搜摘要”这样的需求。

#### `works` 常见字段级搜索

- `title.search`
- `abstract.search`
- `fulltext.search`
- `display_name.search`
- `title_and_abstract.search`
- `raw_affiliation_strings.search`

以及对应的部分 no-stem 版本：

- `display_name.search.no_stem`
- `title.search.no_stem`
- `abstract.search.no_stem`
- `title_and_abstract.search.no_stem`

#### `topics` 旧式字段级搜索

从 Topic Overview 可见目前仍有：

- `display_name.search`
- `description.search`
- `keywords.search`

但这些都属于 deprecated 过滤写法。

#### `keywords`

- `display_name.search`

#### `authors`

- `display_name.search`

#### `institutions`

- `display_name.search`

#### `sources`

- `display_name.search`

#### `publishers`

- `display_name.search`

#### `funders`

官方旧文档显示 funders 的搜索覆盖：

- `display_name`
- `alternate_titles`
- `description`

#### `awards`

官方旧文档显示 awards 的搜索覆盖：

- `display_name`
- `description`

## 4. 结构化过滤能用哪些字段

### 4.1 重要结论

OpenAlex 的“可检索字段”分成两层理解：

- 文本搜索字段：决定 `search` / `.search` 搜哪里
- 结构化字段：决定 `filter` / `sort` / `group_by` 能不能用

对论文 agent 而言，真正最重要的是第二层，因为最终可控检索通常依赖 `filter`。

### 4.2 `works` 常用可过滤字段

当前 `Works Overview` 表里给出的可过滤字段非常多，实际开发最常用的是这些：

基础元数据：

- `publication_year`
- `publication_date`
- `type`
- `language`
- `doi`
- `openalex`
- `openalex_id`
- `cited_by_count`

开放获取：

- `is_oa`
- `oa_status`
- `has_fulltext`
- `has_pdf_url`
- `has_oa_accepted_or_published_version`
- `has_oa_submitted_version`

作者 / 机构：

- `authorships.author.id`
- `authorships.author.orcid`
- `authorships.institutions.id`
- `authorships.institutions.ror`
- `authorships.institutions.country_code`
- `authorships.institutions.type`
- `authorships.countries`
- `corresponding_author_ids`
- `corresponding_institution_ids`

来源 / 载体：

- `primary_location.source.id`
- `best_oa_location.source.id`
- `best_oa_location.source.issn`
- `journal`
- `repository`

主题 / 概念：

- `topics.id`
- `primary_topic.id`
- `primary_topic.domain.id`
- `primary_topic.field.id`
- `primary_topic.subfield.id`
- `concepts.id`

基金：

- `awards.id`
- `awards.funder_id`
- `awards.funder_display_name`
- `awards.doi`

时间增量同步：

- `from_publication_date`
- `to_publication_date`
- `from_created_date`
- `to_created_date`
- `from_updated_date`
- `to_updated_date`

需要注意：

- 某些 created / updated 增量字段在旧文档里曾标过 Premium 限制，当前接入时建议先用你自己的 key 做一次真实请求验证
- `host_venue` 已废弃，应使用 `primary_location`

### 4.3 其他实体常用过滤字段

#### `authors`

常见高频字段：

- `display_name`
- `ids.openalex`
- `last_known_institution.id`
- `last_known_institution.country_code`
- `affiliations.institution.id`
- `affiliations.institution.country_code`
- `has_orcid`
- `works_count`
- `cited_by_count`

#### `institutions`

常见高频字段：

- `display_name`
- `ror`
- `country_code`
- `continent`
- `type`
- `lineage`
- `works_count`
- `cited_by_count`

#### `sources`

常见高频字段：

- `display_name`
- `issn`
- `host_organization`
- `host_organization_lineage`
- `is_oa`
- `is_in_doaj`
- `type`
- `country_code`
- `works_count`
- `cited_by_count`

#### `topics`

常见高频字段：

- `display_name`
- `domain.id`
- `field.id`
- `subfield.id`
- `works_count`
- `cited_by_count`

#### `keywords`

常见高频字段：

- `display_name`
- `works_count`
- `cited_by_count`

#### `publishers`

常见高频字段：

- `display_name`
- `lineage`
- `parent_publisher`
- `country_codes`
- `hierarchy_level`
- `works_count`
- `cited_by_count`

#### `funders`

常见高频字段：

- `display_name`
- `country_code`
- `is_global_south`
- `grants_count`
- `works_count`
- `cited_by_count`

#### `awards`

常见高频字段通常围绕：

- `display_name`
- `description`
- `funder`
- `award amount`
- `award date`
- `works_count`

更完整的字段建议直接看各实体 Overview 页的 Filter / Sort / Group_by 表。

## 5. 是否需要 API Key

结论：对实际开发来说，建议视为“需要”。

当前官方新文档的口径是：

- API key 免费
- 通过 `openalex.org/settings/api` 获取
- 请求时使用 `api_key=YOUR_KEY`
- `LLM Quick Reference` 还提到“无 key 只有约 `$0.01/day` 的极低额度”，因此不适合作为正式开发或生产方案

示例：

```text
https://api.openalex.org/works?api_key=YOUR_KEY
```

当前免费额度：

- 每天 `$1` 免费用量
- 按当前官方示例，大致可覆盖：
  - 单条实体：理论上无限
  - `list+filter`：约 10,000 次调用
  - `search`：约 1,000 次调用
  - 内容下载：约 100 个 PDF

当前官方价格表：

- Singleton：free
- List+Filter：`$0.10 / 1,000 calls`
- Search：`$1 / 1,000 calls`

- Content download：`$10 / 1,000 calls`
- Text/Aboutness：`$10 / 1,000 calls`

关于 `semantic search` 的价格需要特别说明：

- `Authentication & Pricing` 页面顶部价格表把它列为 `"$1 / 1,000 calls"`
- 但同页 `/rate-limit` 示例里的 `endpoint_costs_usd.semantic = 0.01`，这对应 `"$10 / 1,000 calls"`

也就是说，当前官方文档在 `semantic search` 定价上存在口径不一致。

我的建议是：

- 先按“可能高于普通 search”做成本预估
- 在你自己的 API key 下调用一次 `/rate-limit` 或做一次真实 `search.semantic` 请求，再以响应头 / `meta.cost_usd` 为准

## 6. 分页、批量、限流、返回字段限制

### 6.1 分页

基础分页：

- `page`
- `per_page`

当前限制：

- `per_page` 最大 `100`
- 普通分页最多只能访问前 `10,000` 条结果

超过 10,000 时：

- 改用 `cursor=*`
- 然后读取返回里的 `meta.next_cursor`

### 6.2 OR 批量查

同一字段最多支持 `100` 个 OR 值：

```text
/works?filter=doi:10.1/a|10.1/b|10.1/c&per_page=100
```

这对 agent 非常有用，可以做：

- 批量 DOI 回填
- 批量 OpenAlex ID 拉详情
- 批量作者 / 期刊 / 机构过滤

### 6.3 速率与限流

官方说明：

- 超过每日额度或并发限制时会返回 `429`
- 文档明确提到全局有 `100 requests / second` 级别限制
- `search.semantic` 和 `/text` 还各有更严格的 `1 request / second` 限制

建议：

- 做指数退避
- 统一请求层
- 给搜索、语义检索、内容下载分别做队列

### 6.4 `select` 返回字段裁剪

可以使用：

```text
/works?select=id,doi,display_name
```

但限制很重要：

- 只能选 root-level fields
- 不能直接选嵌套字段，如 `open_access.is_oa`
- `select` 支持单条实体和列表实体
- `group_by` 与 `autocomplete` 不支持 `select`

## 7. OpenAlex 不支持什么

根据当前官方文档，可以明确或高概率确认以下结论：

### 7.1 没有官方托管 SQL 查询服务

我没有在当前官方文档中看到类似 BigQuery / SQL endpoint / GraphQL 的在线托管查询入口。

官方给出的主要访问方式是：

- REST API
- Snapshot
- OpenAlex CLI
- Full-text content download

因此如果你要 SQL 检索，推荐路线是：

1. 下载 snapshot
2. 导入 PostgreSQL / DuckDB / ClickHouse / Elastic / Vespa 等
3. 在你自己的存储层上做 SQL 或混合检索

### 7.2 不适合直接拿 API 全量爬库

官方明确不建议用 cursor 把整个 `/works` 或 `/authors` 慢慢翻完。

原因：

- 时间太长
- 对官方服务压力大

正确方式：

- 全量数据用 snapshot
- 在线 query 用 API

## 8. 做论文检索 agent 的推荐接入方式

这是我根据官方文档和论文检索 agent 常见架构整理的建议。

### 8.1 推荐采用“两阶段检索”

第一阶段：实体解析

- 用户输入作者名、机构名、期刊名、topic 名
- 先用 `search` 或 `/autocomplete` 把名称解析成 OpenAlex ID

第二阶段：作品检索

- 用 `/works?filter=...` 按 ID 做结构化检索

例如：

```text
# 先查作者
/authors?search=Geoffrey Hinton

# 再查作者论文
/works?filter=authorships.author.id:A......
```

这是当前官方非常强调的模式，因为：

- 名称不稳定
- 同名很多
- ID 才适合作为 agent 内部中间表示

### 8.2 检索策略建议

如果用户输入的是自由文本问题，可以这样分流：

- 明确关键词检索：先用 `/works?search=...`
- 需要“相关但未必同词”的论文：加 `/works?search.semantic=...`
- 有明确约束时：统一转成 `filter`
  - 年份
  - 是否 OA
  - 作者
  - 机构
  - 期刊
  - topic
  - 资助方

### 8.3 典型 agent 参数模板

```text
/works?
search=large language model reasoning
&filter=publication_year:2024,is_oa:true,type:article
&sort=cited_by_count:desc
&per_page=25
&select=id,doi,display_name,publication_year,cited_by_count,primary_location,authorships,topics,abstract_inverted_index
```

### 8.4 推荐优先级

如果你现在就开始实现，我建议：

1. 先实现 `works` + `authors` + `institutions` + `sources` + `topics`
2. 主检索先用 `search` + `filter`
3. UI 联想输入用 `/autocomplete`
4. 语义检索作为可选增强，不要一开始绑死
5. `/text` aboutness 只做实验能力，不放主链路
6. 需要全库分析时，再引入 snapshot / 自建索引

## 9. 官方链接汇总

### 核心入口

- API Overview: https://developers.openalex.org/api-reference/introduction
- Authentication & Pricing: https://developers.openalex.org/api-reference/authentication
- Key Concepts: https://developers.openalex.org/guides/key-concepts
- LLM Quick Reference: https://developers.openalex.org/guides/llm-quick-reference

### 通用能力

- Filtering: https://developers.openalex.org/guides/filtering
- Search: https://developers.openalex.org/guides/searching
- Autocomplete: https://developers.openalex.org/guides/autocomplete
- Paging: https://developers.openalex.org/guides/page-through-results
- Select Fields: https://developers.openalex.org/guides/selecting-fields
- Aboutness: https://developers.openalex.org/guides/aboutness

### 数据下载

- Download Overview: https://developers.openalex.org/download/overview
- Snapshot Format: https://developers.openalex.org/download/snapshot-format
- Download to your machine: https://developers.openalex.org/download/download-to-machine
- OpenAlex CLI: https://developers.openalex.org/download/openalex-cli
- Full-text PDFs: https://developers.openalex.org/how-to-use-the-api/get-content

### 实体总览

- Works Overview: https://developers.openalex.org/api-reference/works
- Authors Overview: https://developers.openalex.org/api-reference/authors
- Sources Overview: https://developers.openalex.org/api-reference/sources
- Institutions Overview: https://developers.openalex.org/api-reference/institutions
- Topics Overview: https://developers.openalex.org/api-reference/topics
- Keywords Overview: https://developers.openalex.org/api-reference/keywords
- Publishers Overview: https://developers.openalex.org/api-reference/publishers
- Funders Overview: https://developers.openalex.org/api-reference/funders
- Awards Overview: https://developers.openalex.org/api-reference/awards

## 10. 给你下一步开发的直接建议

如果你的目标是“论文检索 agent”，当前最稳的第一版方案是：

- 实体解析层：`authors` / `institutions` / `sources` / `topics` 的 `search` + `autocomplete`
- 主召回层：`/works?search=...`
- 约束层：`filter=publication_year/.../authorships.author.id/...`
- 结果裁剪：`select=...`
- 深翻页：`cursor`
- 高级增强：`search.semantic`
- 离线增强：snapshot + 自建索引

一句话总结：

OpenAlex 很适合做“结构化学术检索 + 轻量语义增强”的 agent，不适合直接当作 SQL 数据仓库来用；如果后面你要做复杂排序、个性化召回、混合检索，最佳路线通常是“OpenAlex API + 本地缓存/向量索引/自建库”。

