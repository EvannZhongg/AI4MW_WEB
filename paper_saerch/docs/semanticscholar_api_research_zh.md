# Semantic Scholar API 调研笔记

更新日期：2026-03-29

这份文档基于 2026-03-29 查阅的 Semantic Scholar 官方产品页、官方 API 文档、官方 OpenAPI swagger、官方 License 页面，以及官方 Datasets API 的实时返回整理，目标是回答你在做“论文检索 agent”时最关心的问题：

- 当前支持哪些检索方式
- 是否支持 SQL / NLP / 自然语言 / 布尔查询
- 能检索哪些字段、能返回哪些字段
- 是否需要 API Key
- 并发 / 速率 / 分页 / 批量限制
- 能否拿到摘要、正文、PDF、snippet、embedding、TLDR
- 下载全量数据需要什么条件

## 结论先看

Semantic Scholar 当前公开的是一组 REST API，而不是 SQL 服务。

对“论文检索 agent”最有用的官方能力主要有：

- `GET /graph/v1/paper/search`
  - 相关性排序的论文检索
  - 接受 plain-text query
  - 不支持特殊查询语法
- `GET /graph/v1/paper/search/bulk`
  - 大规模批量检索
  - 支持布尔/短语/前缀/模糊/邻近语法
  - 适合深翻页和批量拉取
- `GET /graph/v1/paper/search/match`
  - 单篇标题匹配
- `GET /graph/v1/paper/autocomplete`
  - 搜索框联想
- `GET /graph/v1/author/search`
  - 作者检索
- `GET /graph/v1/snippet/search`
  - 从标题、摘要、正文片段里检索并返回约 500 词的 snippet
- `POST /recommendations/v1/papers/` 和 `GET /recommendations/v1/papers/forpaper/{paper_id}`
  - 基于种子论文做推荐，不是 query 搜索
- `GET /datasets/v1/...`
  - 列出 release、数据集元信息、增量 diff、下载链接

关于你问的“SQL / NLP / 自然语言检索”：

- `SQL`
  - 官方没有提供托管 SQL / GraphQL / 向量检索查询接口。
  - 这是基于当前官方只公开 Graph API、Recommendations API、Datasets API 三类接口做出的结论。
  - 如果你需要 SQL，官方路线是下载数据集后本地自建数据库或索引。
- `自然语言检索`
  - 支持“plain-text query”，也就是把自然语言或关键词直接放进 `query=`。
  - 但它不是“LLM 指令式检索”，不会直接理解类似“找近五年高引综述，优先开放获取”的一句话约束组合。你需要自己把这类意图拆成 `query + filters`。
- `布尔 / 高级文本语法`
  - 只在 `paper/search/bulk` 上官方明确支持。
  - `paper/search`、`paper/search/match`、`author/search`、`snippet/search` 都是 plain-text，官方明确写了“不支持特殊查询语法”。
- `语义搜索`
  - 当前公开 API 里没有类似 `semantic search` 的独立 endpoint。
  - 如果你想做语义检索，官方给你的主要 building blocks 是：
    - `Recommendations API`
    - `embedding` 字段
    - `embeddings-specter_v1/v2` 数据集
    - 你自己构建向量索引

## 1. 官方 API 体系总览

Semantic Scholar 当前公开三组 API：

- Academic Graph API
  - `https://api.semanticscholar.org/graph/v1`
  - 论文、作者、引用、参考文献、snippet 等
- Recommendations API
  - `https://api.semanticscholar.org/recommendations/v1`
  - 基于论文种子做推荐
- Datasets API
  - `https://api.semanticscholar.org/datasets/v1`
  - 下载全量数据、增量更新

这意味着对论文 agent 来说，通常会形成三层架构：

1. 在线检索层：Graph API
2. 相关推荐扩展层：Recommendations API
3. 大规模离线索引 / 本地 SQL / 向量库层：Datasets API + 自建索引

## 2. 当前支持哪些检索方式

### 2.1 论文相关性搜索 `paper/search`

接口：

```text
GET /graph/v1/paper/search
```

特点：

- 适合普通搜索框
- 返回 relevance-ranked 结果
- `query` 是 plain-text
- 官方明确写明：
  - 不支持特殊查询语法
  - 连字符词可能匹配不到，建议改为空格

支持的主要过滤参数：

- `publicationTypes`
- `openAccessPdf`
- `minCitationCount`
- `publicationDateOrYear`
- `year`
- `venue`
- `fieldsOfStudy`
- `offset`
- `limit`，最大 `100`

重要限制：

- 最多只返回 `1,000` 条 relevance-ranked 结果
- 单次响应最多 `10 MB`

适用场景：

- 用户直接输入关键词
- 第一阶段召回
- 交互式搜索

### 2.2 论文批量搜索 `paper/search/bulk`

接口：

```text
GET /graph/v1/paper/search/bulk
```

这是 Semantic Scholar 里最适合“高级检索”和“深翻页”的文本检索接口。

特点：

- 行为类似 `paper/search`
- 但不强调 relevance 排序，更偏批量抓取
- 文本 query 可选
- 每次最多返回 `1,000` 篇
- 通过 `token` 连续翻页
- 官方写明最多可通过此方法抓取 `10,000,000` 篇
- 如果还不够，官方明确建议使用 Datasets API

官方明确支持的查询语法：

- `+`：AND
- `|`：OR
- `-`：NOT
- `"`：短语
- `*`：前缀匹配
- `(` `)`：优先级
- `~N`：模糊匹配 / 邻近匹配

官方教程明确说明：

- `paper/search/bulk` 的 query 会匹配论文的 `title` 和 `abstract`
- 所有关键词都会与标题和摘要中的词匹配
- 英文会做 stemming

示例：

```text
((cloud computing) | virtualization) +security -privacy
"red blood cell" + artificial intelligence
fish*
bugs~3
"blue lake"~3
```

支持的主要过滤参数：

- `query`
- `token`
- `fields`
- `sort`
  - `paperId`
  - `publicationDate`
  - `citationCount`
- `publicationTypes`
- `openAccessPdf`
- `minCitationCount`
- `publicationDateOrYear`
- `year`
- `venue`
- `fieldsOfStudy`

重要限制：

- 不支持返回 nested paper data，如 `citations`、`references`
- 适合“批量找 paperId + 基础 metadata”，不适合一次把深层嵌套信息全拉回来

### 2.3 标题匹配搜索 `paper/search/match`

接口：

```text
GET /graph/v1/paper/search/match
```

特点：

- 根据标题 query 找“最接近的一篇论文”
- 只返回单条最高匹配结果
- 适合“标题归一化 / 论文去重 / 用户粘贴论文题目找 canonical paper”
- `query` 同样是 plain-text，不支持特殊语法

### 2.4 自动补全 `paper/autocomplete`

接口：

```text
GET /graph/v1/paper/autocomplete
```

特点：

- 输入部分 query，返回轻量联想结果
- `query` 最多只取前 `100` 个字符
- 返回字段非常轻：
  - `id`
  - `title`
  - `authorsYear`

适用场景：

- 搜索框联想
- 论文标题输入提示

### 2.5 作者搜索 `author/search`

接口：

```text
GET /graph/v1/author/search
```

特点：

- 按作者名搜索
- `query` 是 plain-text
- 不支持特殊查询语法
- 连字符词同样建议改为空格
- `limit` 最大 `1000`

适用场景：

- 作者实体解析
- 将“作者名”转为 `authorId`
- 后续再用作者详情 / 作者论文接口查论文

### 2.6 正文片段搜索 `snippet/search`

接口：

```text
GET /graph/v1/snippet/search
```

这是 Graph API 里最接近“正文检索”的公开能力，但它返回的是 snippet，不是整篇 full text。

官方说明：

- snippet 大约 `500` 词
- 来源于论文的 `title`、`abstract`、`body text`
- 不包含 figure captions 和 bibliography
- 返回最相关 snippet 优先

主要过滤参数：

- `query`
- `fields`
- `paperIds`
- `authors`
  - 模糊作者名匹配
  - 多作者之间是 AND 关系
  - 默认最多 10 个作者过滤
- `minCitationCount`
- `insertedBefore`
- `publicationDateOrYear`
- `year`
- `venue`
- `fieldsOfStudy`
- `limit`，最大 `1000`

注意：

- `query` 仍然是 plain-text，不支持特殊语法
- 但它确实能从正文片段中返回证据文本

### 2.7 推荐检索 `Recommendations API`

接口：

```text
POST /recommendations/v1/papers/
GET  /recommendations/v1/papers/forpaper/{paper_id}
```

特点：

- 不是 query 搜索
- 是“给定正样本 / 负样本论文 ID”做相关推荐
- 或对单篇论文做推荐
- 单次最多 `500` 条推荐

适用场景：

- 检索后二跳扩展
- related work 扩展
- 用户点进一篇论文后扩展相似论文

### 2.8 批量详情获取

接口：

```text
POST /graph/v1/paper/batch
POST /graph/v1/author/batch
```

这类接口不是搜索，但对 agent 很重要，因为很适合做：

- 候选集重排后的详情回填
- 批量 enrichment
- 降低请求次数

限制：

- `paper/batch`
  - 最多 `500` 个 paper id
  - 最多 `10 MB`
  - 最多 `9999` 条 citations
- `author/batch`
  - 最多 `1000` 个 author id
  - 最多 `10 MB`

## 3. 查询语法到底支持到什么程度

### 3.1 明确支持 plain-text 的接口

以下接口官方都明确写了 `No special query syntax is supported`：

- `paper/search`
- `paper/search/match`
- `author/search`
- `snippet/search`

这意味着：

- 支持普通关键词
- 支持把自然语言问题直接塞进 `query`
- 但不支持 SQL
- 不支持 Lucene 风格高级表达式
- 不支持“把一整句用户要求自动拆成年份/开放获取/高引/作者”等约束

所以如果用户输入：

```text
找 2021 年以后关于 graph RAG 的高引开放获取综述
```

你最好在 agent 里转换为：

```text
query=graph rag
publicationTypes=Review
year=2021-
openAccessPdf
minCitationCount=...
```

### 3.2 明确支持高级布尔语法的接口

只有 `paper/search/bulk` 官方明确写了高级匹配语法，并且教程明确举了复杂查询示例。

所以如果你要做：

- 高级检索页
- title/abstract 布尔检索
- 深分页批量抓取
- 规则稳定、可复现的查询

优先用 `paper/search/bulk`。

### 3.3 是否支持 NLP / 语义检索

可以分成三层理解：

- `NLP 风格自由文本输入`
  - 支持，作为 plain-text query
- `公开语义搜索 endpoint`
  - 当前没有独立公开 endpoint
- `自己做语义检索`
  - 可行，官方提供：
    - `embedding` 字段
    - `embeddings-specter_v1`
    - `embeddings-specter_v2`
    - Recommendations API

## 4. 论文能检索哪些字段、能返回哪些字段

### 4.1 搜索过滤字段

`paper/search` 和 `paper/search/bulk` 公开支持的过滤字段主要是：

- `publicationTypes`
- `openAccessPdf`
- `minCitationCount`
- `publicationDateOrYear`
- `year`
- `venue`
- `fieldsOfStudy`

额外能力：

- `paper/search`
  - `offset`
  - `limit<=100`
- `paper/search/bulk`
  - `token`
  - `sort=paperId|publicationDate|citationCount`

`snippet/search` 在上面基础上还多了：

- `paperIds`
- `authors`
- `insertedBefore`

### 4.2 论文详情可返回字段

Graph API 的完整论文对象 `FullPaper` 当前可返回的 root-level 字段包括：

- 标识与外部 ID
  - `paperId`
  - `corpusId`
  - `externalIds`
  - `url`
- 基础元数据
  - `title`
  - `abstract`
  - `venue`
  - `publicationVenue`
  - `year`
  - `publicationDate`
  - `journal`
  - `citationStyles`
- 引用统计
  - `referenceCount`
  - `citationCount`
  - `influentialCitationCount`
- 开放获取 / 文本可得性
  - `isOpenAccess`
  - `openAccessPdf`
  - `textAvailability`
- 学科与类型
  - `fieldsOfStudy`
  - `s2FieldsOfStudy`
  - `publicationTypes`
- 关联对象
  - `authors`
  - `citations`
  - `references`
- AI 增强字段
  - `embedding`
  - `tldr`

默认返回规则：

- 如果不传 `fields`
  - 大多数 paper 接口默认只返回 `paperId` 和 `title`
- `authors`
  - 默认只带 `authorId` 和 `name`
- `citations` / `references`
  - 默认只带 `paperId` 和 `title`
- `embedding`
  - 默认是 SPECTER v1
  - 指定 `embedding.specter_v2` 可取 v2

### 4.3 作者详情可返回字段

作者完整对象 `AuthorWithPapers` 当前可返回：

- `authorId`
- `externalIds`
- `url`
- `name`
- `affiliations`
- `homepage`
- `paperCount`
- `citationCount`
- `hIndex`
- `papers`

如果只请求 `Author` 而不是 `AuthorWithPapers`，则不带 `papers`。

### 4.4 轻量引用对象字段

`PaperInfo` 这类轻量论文对象常用于 nested `citations` / `references`，可返回：

- `paperId`
- `corpusId`
- `url`
- `title`
- `venue`
- `publicationVenue`
- `year`
- `authors`

## 5. 摘要、正文、PDF、TLDR、Embedding 能不能拿到

### 5.1 摘要 `abstract`

可以拿到。

Graph API 公开有 `abstract` 字段。

但官方 schema 明确提醒：

- 由于法律原因，`abstract` 可能缺失
- 即使 Semantic Scholar 网站上显示了摘要，API 里也可能没有

这意味着开发时不能假设每篇论文都有摘要。

### 5.2 正文 full text

需要分成几种情况：

- Graph API 的标准论文对象里
  - 没有“直接返回整篇 full text”的字段
- `snippet/search`
  - 可以从正文里检索并返回约 500 词 snippet
- `openAccessPdf`
  - 可能返回公开 PDF URL
- `textAvailability`
  - 会告诉你当前论文文本可得性是：
    - `fulltext`
    - `abstract`
    - `none`

因此：

- 如果你的问题是“能不能直接通过 Graph API 拿整篇正文文本”
  - 结论是：不能，至少当前公开 schema 没有提供整篇正文字段
- 如果你的问题是“能不能知道它有没有全文、能不能拿到正文证据片段”
  - 可以，通过 `textAvailability`、`openAccessPdf`、`snippet/search`

### 5.3 开放获取 PDF

可以拿到公开 PDF 的链接信息，但不是所有论文都有。

`openAccessPdf` 对象包含：

- `url`
- `status`
- `license`
- `disclaimer`

并且可以在搜索时用 `openAccessPdf` 参数只筛选“有公开 PDF”的论文。

### 5.4 TLDR 摘要

可以。

Graph API 支持 `tldr` 字段，通常包含：

- `model`
- `text`

另外 Datasets API 里还有独立数据集 `tldrs`。

### 5.5 Embedding

可以。

Graph API 支持：

- `embedding`
- `embedding.specter_v2`

Datasets API 里也有：

- `embeddings-specter_v1`
- `embeddings-specter_v2`

这对你后续做：

- 向量召回
- rerank
- related paper
- 多路召回融合

都很有用。

## 6. 是否需要 API Key

### 6.1 Graph / Recommendations API

结论：

- 大多数 endpoint 可以不带 key 直接访问
- 但官方明确建议始终带 key

官方要求：

- 如果使用 API key，必须放在请求头 `x-api-key`
- 这个 header 名称大小写敏感

### 6.2 Datasets API

结论：

- 查看 release 元信息可以不一定需要 key
- 但“拿完整数据集下载链接”需要有效 API key

我在 2026-03-29 实际检查官方接口时，`/datasets/v1/release/latest/dataset/abstracts` 返回：

```json
{"error":"A valid API key is required"}
```

同时同一个 `release/latest` 接口可以返回当前最新 release 和 dataset 列表。

### 6.3 怎么申请 key

官方产品页当前说明：

- 需要在 `https://www.semanticscholar.org/product/api#api-key` 申请
- 官方优先 academic / research / nonprofit / government 机构
- key 会通过邮件发放

官方表单里还有一些运维要求：

- 初始 rate limit 是 `1 RPS` on all endpoints
- 需要承诺使用 exponential backoff 等保护策略
- 长时间不活跃的 key 可能被回收

## 7. 速率限制、并发与分页

### 7.1 无 key 的情况

官方 overview 页面当前写法是：

- 大多数 endpoint 对公众开放
- 未认证请求共享一个 `1000 requests per second` 的公共池
- 高峰期可能被进一步 throttle

这不是“你自己独享 1000 RPS”，而是所有未认证用户共享。

所以对生产系统来说，不建议依赖匿名访问。

### 7.2 有 key 的情况

官方当前写法：

- 使用独立 key 后，默认获得 `1 request per second`，作用于所有 endpoints
- 某些情况下可在 review 后获得略高配额

注意这个口径看起来和“匿名共享 1000 RPS”有点反直觉，但这正是当前官方页面的写法。

实际工程建议：

- 视为“匿名不稳定、key 稳定但基础配额低”
- 生产系统统一走 key
- 对所有 `429` 做指数退避和重试
- 高频批量任务优先用 batch / bulk / datasets

### 7.3 各接口分页限制

常用接口：

- `paper/search`
  - `offset + limit`
  - `limit <= 100`
  - relevance 结果总共最多 `1000`
- `author/search`
  - `offset + limit`
  - `limit <= 1000`
- `snippet/search`
  - `limit <= 1000`
  - 默认 `10`
- `paper/search/bulk`
  - 每次最多 `1000`
  - 用 `token` 翻页
  - 最多可拉到 `10,000,000`

## 8. 下载条件、数据集现状与正文获取边界

### 8.1 Datasets API 是怎么工作的

Datasets API 不是“直接返回大文件内容”，而是：

- 列出可用 release
- 列出某个 release 包含哪些 dataset
- 返回 dataset 元信息
- 返回预签名下载链接
- 返回增量 diff 下载链接

公开接口包括：

- `GET /datasets/v1/release/`
- `GET /datasets/v1/release/{release_id}`
- `GET /datasets/v1/release/{release_id}/dataset/{dataset_name}`
- `GET /datasets/v1/diffs/{start_release_id}/to/{end_release_id}/{dataset_name}`

### 8.2 当前最新 release

我在 2026-03-29 实时查询官方 `release/latest` 时，返回的最新 release 是：

```text
2026-03-10
```

### 8.3 当前 release 中可见的数据集

截至这次查询，官方 `release/latest` 返回的数据集包括：

- `abstracts`
  - 论文摘要文本
- `authors`
  - 作者基础属性
- `citations`
  - 引用关系与 citation context / intent / influential 等
- `embeddings-specter_v1`
- `embeddings-specter_v2`
- `paper-ids`
  - sha id 与 corpus id 映射
- `papers`
  - 论文核心 metadata
- `publication-venues`
- `s2orc`
  - 从开放获取 PDF 解析出的全文正文
- `s2orc_v2`
  - 更新版全文正文数据
- `tldrs`
  - 短自然语言摘要

### 8.4 全量下载是否需要 key

需要。

官方 `release/latest` README 当前写明：

- sample data 可直接下载
- full data access requires an API key

也就是说：

- 样例数据：可拿
- 全量正式数据下载链接：要 key

### 8.5 如果你要“正文”

最重要的开发结论是：

- 在线 Graph API：
  - 不能直接拿整篇正文
  - 但可以拿：
    - `abstract`
    - `openAccessPdf.url`
    - `textAvailability`
    - `snippet/search` 返回的正文片段
- 离线数据集：
  - `s2orc` / `s2orc_v2` 提供从开放获取 PDF 解析出的 full-body text

因此如果你的 agent 需要：

- 在线快速证据摘录
  - 用 `snippet/search`
- 批量全文处理 / RAG / 本地索引
  - 用 `s2orc_v2`

## 9. License、归因与合规要求

官方 License Agreement 当前要点：

- 使用 API 代表接受 API License Agreement
- API key 不得共享给未授权人员
- 不得绕过或规避 rate limits
- 必须遵守 S2 Data 对应 license，以及底层第三方内容 license
- 在网站或公开材料中使用 S2 数据，应包含对 “Semantic Scholar” 的 attribution
- 用 API 产出科研结果时，官方要求引用：
  - `The Semantic Scholar Open Data Platform`

另外，数据集 license 不是完全统一的：

- 多个核心 dataset 是 `ODC-BY`
- embedding 数据集 README 中出现 `Apache 2.0`
- 某些 open access 内容还受第三方 license 约束

所以工程上应当：

- 对每个 dataset 单独看 README
- 对 `openAccessPdf` 或 snippet 涉及的正文内容保留 license / disclaimer

## 10. 对论文检索 agent 的接入建议

### 10.1 推荐的第一版架构

1. 用户 query 先走 `paper/search`
2. 如果用户使用高级语法或需要深翻页，切换到 `paper/search/bulk`
3. 如果用户给的是完整论文题目，用 `paper/search/match`
4. 如果要作者约束，先 `author/search` 拿 `authorId`
5. 如果要证据片段，走 `snippet/search`
6. 如果要相似论文扩展，走 Recommendations API
7. 如果要高吞吐 / SQL / 向量检索 / 全文检索，下载 datasets 本地建库

### 10.2 你需要在 agent 里自己做的事情

- 把自然语言意图拆成：
  - `query`
  - `year`
  - `publicationTypes`
  - `openAccessPdf`
  - `fieldsOfStudy`
  - `venue`
  - `minCitationCount`
- 做统一重试和退避
- 做字段裁剪，避免响应过大
- 对没有摘要 / 没有 PDF / 只有 snippet 的情况做 graceful fallback

### 10.3 一个很实用的策略

如果你后面要做“检索 + 阅读 + 推荐”的 agent，推荐采用：

- 召回：
  - `paper/search`
  - `paper/search/bulk`
- 证据：
  - `snippet/search`
- 扩展：
  - Recommendations API
- 离线增强：
  - `papers`
  - `abstracts`
  - `s2orc_v2`
  - `embeddings-specter_v2`
  - `tldrs`

这样你能同时覆盖：

- metadata 检索
- 摘要检索
- 正文证据片段
- 相似论文扩展
- 本地语义检索

## 11. 一句话总结

Semantic Scholar 当前最适合拿来做：

- 论文 metadata 检索
- title/abstract 高级布尔检索
- 作者解析
- 证据 snippet 检索
- 相关推荐扩展
- 基于 datasets 的本地全文 / 向量 / SQL 检索

它当前不适合直接当作：

- 托管 SQL 数据仓库
- 公共语义搜索 SaaS
- 直接在线返回整篇正文的全文 API

## 12. 官方链接汇总

### 产品与教程

- Overview: https://www.semanticscholar.org/product/api
- Tutorial: https://www.semanticscholar.org/product/api/tutorial
- API License Agreement: https://www.semanticscholar.org/product/api/license

### Academic Graph API

- Docs: https://api.semanticscholar.org/api-docs/graph
- OpenAPI: https://api.semanticscholar.org/graph/v1/swagger.json

### Recommendations API

- Docs: https://api.semanticscholar.org/api-docs/recommendations
- OpenAPI: https://api.semanticscholar.org/recommendations/v1/swagger.json

### Datasets API

- Docs: https://api.semanticscholar.org/api-docs/datasets
- OpenAPI: https://api.semanticscholar.org/datasets/v1/swagger.json

### 这次调研里最关键的官方结论来源

- `paper/search` / `author/search` / `snippet/search` 是否支持特殊语法
- `paper/search/bulk` 支持哪些布尔语法
- `FullPaper` / `AuthorWithPapers` / `snippet` / `embedding` / `tldr` 字段
- `x-api-key` 头、key 速率限制、匿名共享流量池
- `release/latest` 当前最新 release：`2026-03-10`
- `release/latest/dataset/{dataset}` 下载链接需要 valid API key
- `s2orc` / `s2orc_v2` / `abstracts` / `tldrs` / `embeddings-specter_v2` 当前可见

如果你下一步愿意，我可以继续直接帮你把这份文档往下落实成一套 `Semantic Scholar` 检索 adapter 设计，包括：

- 参数规范
- Python/TypeScript SDK 封装
- 查询规划器
- 限流重试层
- `search -> batch -> snippet -> recommendations` 的 agent 工作流
