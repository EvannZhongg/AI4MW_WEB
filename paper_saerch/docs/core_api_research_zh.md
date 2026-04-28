# CORE API 调研笔记

更新日期：2026-03-29

这份文档基于 CORE 当前官方文档、官方 OpenAPI/Swagger 定义，以及对公开 v3 端点的最小实测整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- CORE 当前官方检索接口是什么
- 支持哪些检索方式和查询语法
- 是否支持 SQL / NLP 自然语言 / 语义检索
- 能检索哪些字段，能返回哪些字段
- 是否需要 API Key
- 并发 / 速率限制 / 配额是什么
- 能否下载 PDF、能否拿到正文或摘要
- 适不适合做在线检索，什么时候应该改用 Dataset

## 结论先看

截至 2026-03-29，CORE 当前推荐的新接口是 `API v3`：

```text
https://api.core.ac.uk/docs/v3
```

它的核心特点是：

- 接口风格是 REST API，不是 SQL
- 论文相关的主检索实体是 `works` 和 `outputs`
- 支持字段检索、布尔组合、短语搜索、范围查询、存在性查询、聚合统计、滚动查询
- 支持“无字段前缀”的自由文本检索，但官方没有把它定义为 NLP 语义搜索
- 官方没有提供“自然语言问句理解”或“向量语义检索”接口说明
- 基础访问当前可匿名调用，不强制 API Key
- 但注册 API Key 后有更高配额，并且官方明确说明匿名用户拿不到 full-text
- 对大结果集，API 单次结果集上限是 `10,000`
- 对更大规模数据，官方明确建议改用 `CORE Dataset`

如果你的目标是做“论文检索 agent”，我建议：

- 候选召回优先用 `works`
- 需要具体来源、license、OAI、原始记录、下载链接时再查 `outputs`
- 需要大批量离线分析或全文挖掘时直接评估 `Dataset`

## 1. 官方文档入口与版本现状

CORE 当前和开发最相关的官方入口主要有 4 个：

- API 服务页：`https://core.ac.uk/services/api`
- API v3 文档：`https://api.core.ac.uk/docs/v3`
- API v3 Swagger：`https://api.core.ac.uk/swagger/v3.json`
- Dataset 文档：`https://core.ac.uk/documentation/dataset`

同时，CORE 主站上还保留了一份较旧的 API 文档页：

- 旧文档页：`https://core.ac.uk/documentation/api`

这份旧页仍然会提到：

- `API v2`
- `/articles/search`、`/journals/search`、`/repositories/search`
- “请注册以获取 API key”

而当前 v3 文档明确写的是：

- 基础访问免费且“requires no authentication”
- 新主实体是 `works`、`outputs`、`data-providers`、`journals`

因此，做新项目时建议把：

- `v3` 视为当前主接口
- `v2` 只作为历史兼容信息参考

## 2. 当前支持哪些检索方式

### 2.1 主检索实体

当前 v3 搜索端点支持的实体类型主要是：

- `works`
- `outputs`
- `data-providers`
- `journals`

做论文检索时最关键的是前两个：

- `works`：去重后的“作品”层，一个 work 可以关联多个 output
- `outputs`：具体来源中的某一份实际记录，例如某仓储或某期刊中的具体条目

### 2.2 GET 检索

通用格式：

```text
GET /v3/search/{entityType}?q=...&limit=...&offset=...
```

例如：

```text
GET https://api.core.ac.uk/v3/search/works?q=title:"machine learning"&limit=10
GET https://api.core.ac.uk/v3/search/outputs?q=documentType:"research" AND _exists_:license&limit=25
```

### 2.3 POST 检索

通用格式：

```text
POST /v3/search/{entityType}
Content-Type: application/json
```

请求体示例：

```json
{
  "q": "title:\"machine learning\" AND yearPublished>=2020",
  "limit": 10,
  "offset": 0,
  "scroll": false,
  "stats": false
}
```

POST 和 GET 在功能上等价，但更适合：

- 长查询语句
- 前端 UI 构建复杂过滤器
- 自动化系统拼装结构化请求

### 2.4 聚合检索

通用格式：

```text
POST /v3/search/{entityType}/aggregate
```

示例：

```json
{
  "q": "title:\"climate change\"",
  "aggregations": ["yearPublished", "authors"]
}
```

聚合返回的是汇总计数，不是具体论文记录，适合：

- facet
- 年份分桶
- 作者 / publisher / language 分布

### 2.5 DOI 到全文链接发现

CORE 还有一个不是“论文搜索”但很有用的端点：

```text
POST /v3/discover
```

用途：

- 基于 DOI、标题等信息发现 full text link

示例：

```json
{
  "doi": "10.1038/nature23474"
}
```

更适合：

- 已知 DOI 后回填全文入口
- 兜底查找 PDF / full-text link

它不是 SQL，也不是语义检索，而是“全文链接发现”服务。

## 3. 支持哪些查询语法

CORE v3 官方文档当前明确给出的查询语言能力包括：

- 字段查找：`field:value`
- `AND`
- `OR`
- `+`
- 空格作为 AND
- 括号分组：`(...)`
- 范围查询：`> < >= <=`
- 存在性查询：`_exists_:fieldName`
- 无字段前缀的自由文本检索
- 短语检索：双引号

### 3.1 字段检索

示例：

```text
q=title:"Machine Learning"
q=doi:10.1038/nature23474
q=authors:"Jane Doe"
```

### 3.2 布尔检索

官方当前文档明确列出了：

- `AND`
- `OR`
- `+`
- 空格作为 AND

示例：

```text
q=authors:"Jane Doe" AND authors:"John Smith"
q=title:"AI" OR fullText:"Deep Learning"
q=title:graph neural networks
```

关于 `NOT`：

- 当前 v3 查询语言说明页没有把 `NOT` 列为官方语法之一
- 因此生产实现里不要假定它是官方支持能力

### 3.3 分组

示例：

```text
q=(title:"Artificial Intelligence" OR title:"Machine Learning") AND yearPublished>"2020"
```

### 3.4 范围查询

示例：

```text
q=yearPublished>2018
q=yearPublished>="2015" AND yearPublished<="2024"
q=publishedDate:"2009-10-18T00:00:00"
```

### 3.5 存在性查询

示例：

```text
q=_exists_:fullText
q=_exists_:license
```

### 3.6 关键词检索与短语检索

官方专门区分了两类：

- 未加引号：关键词检索
- 加双引号：短语精确匹配

示例：

```text
q=title:Attention is all you need
q=title:"Attention is all you need"
```

### 3.7 不指定字段的自由文本检索

示例：

```text
q=scientometrics
```

官方说明是：

- 如果不写字段前缀，系统会在“所有 searchable fields”里搜索

这意味着它是“跨可检索字段的自由文本检索”，但官方没有把它描述成：

- SQL
- 自然语言问答
- 语义向量检索

## 4. 是否支持 SQL / NLP / 语义检索

### 4.1 SQL

不支持官方在线 SQL 查询接口。

当前官方公开的是：

- REST API
- Dataset
- DOI/full-text discovery

如果你想用 SQL，合理做法是：

- 下载 Dataset
- 自行导入 PostgreSQL / ClickHouse / Elasticsearch / OpenSearch

### 4.2 NLP / 自然语言问句检索

官方没有提供“自然语言问句检索”接口说明。

可以做的只有：

- 自由文本关键词检索
- 字段检索
- 布尔 / 范围 / exists 组合

因此如果用户输入自然语言问题，例如：

```text
找 2020 年以后关于 retrieval-augmented generation 的开放获取论文
```

你需要在 agent 侧把它改写成 CORE 查询语言，而不是把整句原样交给一个官方“NLU 搜索”端点。

### 4.3 语义搜索 / embedding 搜索

官方文档没有提供：

- semantic search
- embedding similarity search
- vector search

因此当前不能把 CORE 当作自带语义召回的论文搜索引擎来接入。

## 5. 论文检索最相关的实体：Works 与 Outputs

### 5.1 Works 是什么

官方定义里，`works` 是“去重且 harmonised 的作品级实体”。

适合：

- 检索候选论文
- 避免同一论文在多个仓储 / 期刊来源里重复出现
- 先做召回，再按需展开到 outputs

### 5.2 Outputs 是什么

`outputs` 是某个具体来源中的具体表现形式。

适合：

- 看具体数据提供方
- 看 OAI / repository / raw XML / license / provider-specific download
- 做来源级追踪

### 5.3 Agent 开发建议

对于论文检索 agent，建议默认流程：

1. 先搜 `works`
2. 对候选 `work` 拉详情
3. 如果需要具体来源或下载策略，再查 `/v3/works/{id}/outputs`
4. 再对具体 `output` 取详情、license、raw XML、downloadUrl

## 6. `works` 支持检索哪些字段

下面只列和论文检索最相关、且官方文档明确说明的字段能力。

### 6.1 `works` 可用于字段检索的字段

| 字段 | 说明 |
| --- | --- |
| `abstract` | 摘要，支持 `q=abstract:"..."` |
| `arxivId` | arXiv ID |
| `authors` | 作者 |
| `contributors` | 贡献者 |
| `createdDate` | CORE 收录创建时间 |
| `dataProviders` | 数据提供方 |
| `depositedDate` | 入库 / deposit 时间 |
| `documentType` | 文献类型 |
| `doi` | DOI |
| `fullText` | 正文全文索引字段 |
| `id` | CORE work ID |
| `identifiers` | 外部标识符集合 |
| `magId` | Microsoft Academic Graph ID，官方标为 deprecated |
| `oaiIds` | OAI 标识符列表 |
| `publishedDate` | 发表日期 |
| `publisher` | 出版方 |
| `pubmedId` | PubMed ID |
| `title` | 标题 |
| `updatedDate` | CORE 更新时间 |
| `yearPublished` | 年份 |

### 6.2 `works` 支持聚合的字段

官方字段表和聚合页明确给出的可聚合字段包括：

- `acceptedDate`
- `arxivId`
- `authors`
- `citationCount`
- `contributors`
- `createdDate`
- `dataProviders`
- `depositedDate`
- `documentType`
- `doi`
- `id`
- `language`
- `magId`
- `oaiIds`
- `publishedDate`
- `publisher`
- `pubmedId`
- `updatedDate`
- `yearPublished`
- `fieldOfStudy`

### 6.3 `works` 会返回、但不适合作为主检索字段的常见字段

常见返回字段包括：

- `downloadUrl`
- `outputs`
- `journals`
- `links`
- `references`
- `sourceFulltextUrls`
- `language`
- `fieldOfStudy`

这些字段更适合：

- 展示
- 补充元数据
- 后续跳转 / 下载 / 去重

## 7. `outputs` 支持检索哪些字段

### 7.1 `outputs` 可用于字段检索的字段

官方文档明确标了可字段检索的字段包括：

| 字段 | 说明 |
| --- | --- |
| `authors` | 作者 |
| `contributors` | 贡献者 |
| `documentType` | 文献类型 |
| `doi` | DOI |
| `fullText` | 全文索引字段 |
| `id` | CORE output ID |
| `license` | license |
| `oai` | OAI 标识符 |
| `setSpecs` | OAI set / 分组标识 |
| `title` | 标题 |
| `yearPublished` | 年份 |

### 7.2 `outputs` 支持聚合的字段

官方聚合页给出的可聚合字段包括：

- `acceptedDate`
- `authors`
- `contributors`
- `depositedDate`
- `documentType`
- `language`
- `publishedDate`
- `subjects`

### 7.3 `outputs` 常见返回字段

`outputs` 常见返回字段比 `works` 更偏来源侧，常用的有：

- `abstract`
- `downloadUrl`
- `dataProvider`
- `identifiers`
- `language`
- `publisher`
- `references`
- `repositories`
- `repositoryDocument`
- `sourceFulltextUrls`
- `subjects`
- `tags`
- `urls`
- `license`
- `sdg`
- `deleted`
- `disabled`

## 8. 能返回摘要吗？能返回正文吗？

### 8.1 摘要

可以。

官方文档和实际返回都表明：

- `works` 有 `abstract`
- `outputs` 也有 `abstract`

但是否每条都有值，取决于来源是否提供。

### 8.2 正文全文

CORE 的数据模型里有 `fullText` 字段，而且官方文档明确说明：

- `fullText` 可作为检索字段使用
- `fullText` 来自对 PDF 的下载与解析

但权限上要注意：

- v3 rate limit 页明确写了：`Full-text is not available for unauthenticated API users`

这意味着：

- 匿名用户可以利用 `fullText` 作为搜索条件
- 但匿名用户不应期待 API 响应里直接拿到完整正文

### 8.3 本地最小实测结果

我在 2026-03-29 对公开 v3 端点做了最小实测：

- 匿名 `GET /v3/search/works` 可正常返回 200
- 用 `q=fullText:"neural networks"` 这样的条件也能正常搜索
- 但 `works` 返回里的 `fullText` 字段内容是：

```text
Not available for public API users.
```

因此，当前更稳妥的工程判断是：

- 匿名调用：可用全文索引检索，但不能直接读全文文本
- 注册 / 更高权限调用：官方文档表述与服务页都暗示可以获得更高权限，但仍受 `Terms & Conditions`、注册身份和配额计划约束

## 9. 能下载 PDF 吗？

可以，但有明确的官方下载策略。

### 9.1 官方推荐的下载方式

优先使用记录中的原始下载链接：

- `downloadUrl`

官方把它列为首选方式。

### 9.2 API 下载端点

官方还提供：

```text
GET /v3/outputs/{identifier}/download
GET /v3/works/{identifier}/download
GET /v3/works/tei/{identifier}
```

其中：

- `outputs/{id}/download` 更偏 PDF 下载
- `works/tei/{id}` 是 TEI 下载

### 9.3 下载限制与合规要求

官方 PDF download policy 明确写了：

- 如果 `downloadUrl` 可用，优先走它
- 如果原始 `downloadUrl` 被阻断，才建议走 API 下载端点
- API 下载会消耗 token，且比普通查询更贵
- 不允许绕开 API 做系统化 PDF 批量抓取
- 例如直接扫 `files.core.ac.uk/download/{identifier}.pdf` 这类方式是官方明确禁止的

官方原文含义非常明确：如果你绕开官方策略去系统性抓 PDF，会被封禁，相关 API key 也可能被禁用。

## 10. 是否需要 API Key

### 10.1 当前 v3 的基础结论

当前 v3 文档写的是：

- `Access to the CORE API is free and requires no authentication`

因此：

- 基础调用不强制 API Key

### 10.2 但注册仍然重要

同一份官方文档和服务页又明确写了：

- 注册用户有更高配额
- 服务页仍提供 “Register for an API key”
- 服务页说明会通过邮箱发送 key 和说明
- 未认证用户拿不到 full-text

所以工程上的正确理解应该是：

- 不注册也能用一部分 v3 能力
- 但如果你要稳定开发、提高吞吐、争取 full-text 权限，应该注册 API key

### 10.3 注册入口

官方入口：

- `https://core.ac.uk/services/api`

## 11. 速率限制 / 配额 / 并发注意事项

### 11.1 当前 v3 的 token 制限

官方当前把限流描述为 token-based，而不是简单“每秒几次”。

官方说明：

- 每个用户会拿到一定 token
- 简单查询通常消耗 `1 token`
- 更复杂调用通常消耗 `3-5 tokens`
- recommender、scroll search、bulk queries 更贵

### 11.2 当前官方列出的配额

| 用户类型 | 获取方式 | 官方说明的配额 |
| --- | --- | --- |
| 未认证用户 | 无需注册 | `100 tokens/day`，`max 10/min` |
| Registered Personal users | 通过 API 表单注册 | `1,000 tokens/day`，`max 25/min` |
| Registered academic users, 非 Supporting/Sustaining 机构 | 通过 API 表单注册 | `5,000 tokens/day`，`max 10/min` |
| Supporting/Sustaining 机构关联学术用户 + 非学术组织用户 | 通过 API 表单注册 | 官方估计平均可到约 `200k tokens/day` |
| VIP | 联系官方 | 官方写的是 “Sky is the limit” |

### 11.3 怎么监控剩余额度

官方要求看响应头：

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Retry-After`

我本地匿名实测时，响应头确实返回了这些字段。

### 11.4 并发建议

官方没有给出像 arXiv 那样“单连接”级别的明确并发条款，但从 token 机制和“复杂请求更贵”可以推导出：

- 不要高并发猛刷
- scroll / 批量 / 下载请求要单独限速
- 下载与检索要分开限流队列

比较稳妥的工程建议：

- 匿名访问：按 `<= 10/min` 设计
- 注册后：仍然按保守速率做客户端节流
- 把 `X-RateLimit-Remaining` 和 `X-RateLimit-Retry-After` 做成动态退避依据

## 12. 分页、大结果集与批量数据

### 12.1 普通分页

GET 搜索支持：

- `limit`
- `offset`

POST 搜索请求体也支持：

- `limit`
- `offset`

### 12.2 scroll 查询

官方支持：

- `scroll=true`
- POST body 中的 `scroll_id`

用途：

- 获取超过普通分页窗口的大结果集

但官方同时强调：

- scroll 查询性能影响更大
- 也会被更严格限制

### 12.3 API 结果集上限

官方明确写了：

- API 单个结果集最大 `10,000` 条

超过这个规模时，官方建议：

- 使用 scroll
- 或直接使用 Dataset

## 13. Dataset 下载条件与能力

如果你后续要做：

- 大规模离线索引
- 自建 SQL / 向量库
- 全文挖掘
- 大批量训练数据构建

应该认真评估 `CORE Dataset`。

### 13.1 最新数据集信息

当前 dataset 文档页显示的 latest dataset 为：

- `Dataset 2024-07-12`
- 大小约 `749 GB compressed`
- 解压后约 `2.7 TB`

官方注明内容是：

- `Full dataset (Full text & metadata)`

### 13.2 下载条件

官方文档写明，下载最新 dataset 需要：

- 一个 `dataset_index.xml` 链接
- `username`
- `password`

并且：

- 这些链接和凭证会通过邮件发送

### 13.3 数据字段能力

dataset 文档给出的样例字段明确包含：

- `title`
- `authors`
- `abstract`
- `downloadUrl`
- `fullTextIdentifier`
- `pdfHashValue`
- `publisher`
- `journals`
- `language`
- `year`
- `topics`
- `subjects`
- `fullText`

所以如果你的目标是“稳定拿到大规模摘要和正文”，Dataset 比匿名 API 更合适。

### 13.4 使用边界

dataset 页面写明：

- 许可遵循 `Terms & Conditions`
- 数据是 snapshot，不保证包含生成之后的最新数据

## 14. 其他和论文 agent 有关的端点

除了搜索本身，你后续大概率还会用到：

- `GET /v3/works/{identifier}`：取单篇 work 详情
- `GET /v3/works/{identifier}/outputs`：展开 work 对应的多个 outputs
- `GET /v3/works/{identifier}/stats`
- `GET /v3/outputs/{identifier}`：取单个 output 详情
- `GET /v3/outputs/{identifier}/stats`
- `GET /v3/outputs/{identifier}/raw`：下载 output 的原始 XML 记录

其中最有开发价值的是：

- `works/{id}/outputs`
- `outputs/{id}`
- `outputs/{id}/raw`

## 15. 对你的论文检索 agent 的接入建议

### 15.1 推荐的检索主路径

我建议默认采用：

1. `works` 作为主检索入口
2. 使用 CORE query language 进行结构化召回
3. 对命中 work 再补拉详情
4. 必要时展开 outputs 处理下载、license、原始记录

### 15.2 查询改写策略

因为 CORE 不提供真正的自然语言问句检索，所以建议 agent 层做一层 query rewriting：

- 用户自然语言
- 解析出主题词、时间、文献类型、是否要求开放获取
- 生成 `title / fullText / authors / yearPublished / documentType / _exists_` 组合查询

示例：

```text
用户意图：
找 2020 年以后关于 RAG 的研究论文，最好有全文

可改写为：
q=(title:"retrieval augmented generation" OR fullText:"retrieval augmented generation" OR title:RAG)
AND yearPublished>=2020
AND documentType:research
AND _exists_:fullText
```

### 15.3 去重与正文策略

建议：

- 候选层用 `works` 去重
- 下载层转 `outputs`
- 匿名状态下不要依赖 API 返回 `fullText`
- 如果要做稳定正文处理，优先申请 API key / full-text 权限，或者直接准备 Dataset 路线

## 16. 需要特别注意的“文档差异”

当前 CORE 官方站存在一个容易踩坑的点：

- 旧 `documentation/api` 页面仍然以 v2 口径写法为主，并强调注册 API key
- 新 `docs/v3` 页面则说明基础访问可匿名

我建议你后续开发统一按下面规则处理：

- 新功能开发：以 `v3` 文档和 `swagger/v3.json` 为准
- 配额、full-text 权限、商业使用边界：同时参考 `services/api` 和 `terms`
- 不要再按 v2 的 `/articles/search` 去设计新系统

## 官方来源

- CORE API 服务页：`https://core.ac.uk/services/api`
- CORE API v3 文档：`https://api.core.ac.uk/docs/v3`
- CORE API v3 Swagger：`https://api.core.ac.uk/swagger/v3.json`
- CORE 旧 API 文档页：`https://core.ac.uk/documentation/api`
- CORE Dataset 文档：`https://core.ac.uk/documentation/dataset`
- CORE Terms & Conditions：`https://core.ac.uk/terms`
