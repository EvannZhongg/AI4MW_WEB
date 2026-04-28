# Crossref API 调研笔记

更新日期：2026-03-31

这份文档基于 Crossref 当前官方文档、官方 Swagger 和少量 live API 验证整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- Crossref 现在支持哪些接口和检索方式
- 是否支持 SQL / NLP / 语义搜索 / 全文搜索
- 能检索哪些字段，哪些字段可以过滤
- 是否需要 API Key
- 分页、限流、版本、返回字段裁剪分别是什么
- 做论文检索 agent 时，Crossref 最适合放在哪个环节

## 结论先看

Crossref 最适合被理解为：

- 一个覆盖面很广的 DOI / 学术元数据检索与回表 API
- 一个非常适合做 DOI lookup、元数据补齐、funding / relation / license / full-text-link 信号补充的基础设施
- 但不是一个“现成的语义论文搜索引擎”

如果你的目标是做“论文检索 agent”，Crossref 的价值主要在：

- 超大规模 DOI 元数据覆盖
- 强结构化过滤
- DOI、ISSN、member、funder、prefix、type 等实体维度检索
- funding、license、relation、reference、full-text link 等补充信号
- `works/{doi}/agency` 这类 DOI 归属校验能力

它不擅长单独承担的是：

- 向量语义检索
- 自然语言问句理解型检索
- 摘要 / 全文质量稳定的主召回
- 托管 SQL 查询
- 直接返回全文正文

一句话总结：

- `Crossref 很适合做“高覆盖学术元数据底座 + DOI/关系/资助信息增强”`
- `不适合单独当作语义搜索或全文搜索引擎`

## 1. 官方文档入口现状

Crossref 当前和 REST API 最相关的官方入口有这些：

- Metadata Retrieval 总览：
  - `https://www.crossref.org/documentation/retrieve-metadata/`
- REST API 总览：
  - `https://www.crossref.org/documentation/retrieve-metadata/rest-api/`
- REST API Filters：
  - `https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/`
- Access and Authentication：
  - `https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/`
- Tips and tricks：
  - `https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/`
- API Versioning：
  - `https://www.crossref.org/documentation/retrieve-metadata/api-versioning/`
- Swagger：
  - `https://api.crossref.org/swagger-ui/index.html`
  - `https://api.crossref.org/swagger-docs`

开发建议：

- 概念和使用建议以 `crossref.org/documentation/...` 为准
- 具体参数、字段查询、endpoint 列表以 `swagger-docs` 为准
- 实际接入时建议显式使用版本化路径 `https://api.crossref.org/v1/...`

## 2. 当前支持哪些接口

根据当前官方 Swagger，REST API 主体 endpoint 包括：

- `/works`
- `/works/{doi}`
- `/works/{doi}/agency`
- `/journals`
- `/journals/{issn}`
- `/journals/{issn}/works`
- `/funders`
- `/funders/{id}`
- `/funders/{id}/works`
- `/members`
- `/members/{id}`
- `/members/{id}/works`
- `/prefixes/{prefix}`
- `/prefixes/{prefix}/works`
- `/types`
- `/types/{id}`
- `/types/{id}/works`
- `/licenses`

对论文检索 agent 最关键的通常是：

- `/works`
  - 主搜索入口
- `/works/{doi}`
  - DOI 精确回表
- `/works/{doi}/agency`
  - 校验某个 DOI 是否属于 Crossref
- `/journals/{issn}/works`
  - 按期刊维度抓取 works
- `/funders/{id}/works`
  - 按资助机构抓取 works
- `/members/{id}/works`
  - 按 depositing member 抓取 works
- `/prefixes/{prefix}/works`
  - 按 DOI prefix 抓取 works
- `/types/{id}/works`
  - 按 work type 抓取 works

### 2.1 `/works`

这是最核心的接口。

Swagger 当前定义：

- 默认每页 `20`
- 单次 `rows` 最大 `1000`
- 支持：
  - `query`
  - 一组 `query.*` 字段查询
  - `filter`
  - `sort`
  - `order`
  - `facet`
  - `select`
  - `sample`
  - `offset`
  - `cursor`
  - `mailto`

它返回的对象不只包括 journal article，还包括：

- conference proceedings
- books / chapters
- components
- datasets
- grants
- peer reviews
- posted content / preprints
- reports
- standards

所以如果你做“论文检索”，通常需要配合 `filter=type:...` 做类型收敛。

### 2.2 `/works/{doi}`

适合：

- 已知 DOI 时做精确 lookup
- 检索召回后补齐详情
- 去重后回表拉完整 metadata

示例：

```text
GET /v1/works/10.1128/mbio.01735-25
```

实测说明：

- 2026-03-31 我本地实际验证时，`/v1/works/{doi}` 可以正常返回 `200`
- 同时 `/v1/works/doi/{doi}` 当前也能返回 `200`
- 但 Swagger 的规范路径是 `/works/{doi}`，工程上建议优先按 Swagger 路径接入

### 2.3 `/works/{doi}/agency`

适合：

- 在你拿到一个 DOI 后，先判断它是不是 Crossref DOI
- 为多 DOI agency 体系做分流

示例响应语义：

- 返回 `agency.id`
- Crossref DOI 会显示 `crossref`

这对接 Unpaywall 或其他 DOI 源时很有用，因为不少下游服务会有“只覆盖 Crossref DOI”的边界。

## 3. 支持哪些检索方式

### 3.1 通用元数据查询：`query`

Crossref 支持通用 `query` 参数。

适合：

- 自由文本召回
- 宽松的元数据搜索

示例：

```text
/works?query=graph neural networks for retrieval
```

需要注意：

- 官方文档没有把它描述成 Lucene 风格高级布尔 DSL
- 更推荐的工程实践通常是：`query.*` + `filter`

### 3.2 字段级查询：`query.*`

这是 Crossref 对论文检索很有价值的一层。

根据当前 Swagger，`/works` 支持以下字段查询：

- `query.affiliation`
- `query.author`
- `query.bibliographic`
- `query.chair`
- `query.container-title`
- `query.contributor`
- `query.degree`
- `query.description`
- `query.editor`
- `query.event-acronym`
- `query.event-location`
- `query.event-name`
- `query.event-sponsor`
- `query.event-theme`
- `query.funder-name`
- `query.publisher-location`
- `query.publisher-name`
- `query.standards-body-acronym`
- `query.standards-body-name`
- `query.title`
- `query.translator`

其中最实用的通常是：

- `query.title`
- `query.author`
- `query.container-title`
- `query.bibliographic`

特别是：

- `query.bibliographic`
  - 官方说明它适合 citation lookup
  - 会综合 title、author、ISSN、publication year 等引用相关字段

如果你要做：

- 参考文献解析
- 引文字符串补 DOI
- “已知部分书目信息，尽可能找回 DOI”

那么 `query.bibliographic` 往往比只用 `query.title` 更合适。

### 3.3 结构化过滤：`filter`

这是 Crossref 最强的部分之一。

官方 filters 文档把 works 过滤器分成三大类：

- 按日期过滤
- 判断某字段是否存在
- 按具体值精确过滤

#### 3.3.1 日期过滤

高频过滤器包括：

- `from-created-date` / `until-created-date`
- `from-update-date` / `until-update-date`
- `from-deposit-date` / `until-deposit-date`
- `from-index-date` / `until-index-date`
- `from-pub-date` / `until-pub-date`
- `from-print-pub-date` / `until-print-pub-date`
- `from-online-pub-date` / `until-online-pub-date`
- `from-accepted-date` / `until-accepted-date`
- `from-issued-date` / `until-issued-date`

几个最重要的差异：

- `created-date`
  - 第一次 deposited 的时间
- `update-date` / `deposit-date`
  - member 重新 deposit 后也会变化
- `index-date`
  - API 重新索引时间
  - 不只包含 member 的更新，也包含 Crossref 或外部来源引起的更新
- `pub-date`
  - 发表时间

如果你要做“本地增量同步”，官方 tips 的建议很明确：

- 要拿最完整的增量变化，优先考虑 `from-index-date`
- 不推荐把 `published date` 当同步边界

#### 3.3.2 存在性过滤

这一类很适合做信号筛选。

高频过滤器包括：

- `has-abstract`
- `has-orcid`
- `has-authenticated-orcid`
- `has-ror-id`
- `has-funder`
- `has-funder-doi`
- `has-references`
- `has-full-text`
- `has-license`
- `has-affiliation`
- `has-award`
- `has-relation`
- `has-update`
- `is-update`
- `has-archive`

这类过滤器的价值很高，因为可以快速表达：

- 只要有摘要的记录
- 只要作者里带 ORCID 的记录
- 只要带 funding metadata 的记录
- 只要带 full-text link 的记录
- 只要带 reference list 的记录

#### 3.3.3 精确值过滤

高频过滤器包括：

- 标识类：
  - `doi`
  - `orcid`
  - `ror-id`
  - `isbn`
  - `issn`
  - `member`
  - `prefix`
  - `alternative-id`
- 类型与元数据：
  - `type`
  - `type-name`
  - `container-title`
  - `article-number`
  - `license.url`
  - `license.version`
  - `license.delay`
- funding：
  - `award.funder`
  - `award.number`
  - `gte-award-amount`
  - `lte-award-amount`
  - `funder`
  - `funder-doi-asserted-by`
- 关系与全文链接：
  - `full-text.type`
  - `full-text.application`
  - `full-text.version`
  - `relation.type`
  - `relation.object-type`
  - `relation.object`
  - `update-type`
  - `updates`

这意味着 Crossref 很适合做：

- 按 ISSN、prefix、member、type 的结构化学术检索
- 按 funder / award 的项目检索
- 按 preprint / correction / retraction 等关系信号做检索或过滤
- 按 full-text link 类型筛出可做 TDM 或 PDF 解析的候选

### 3.4 排序：`sort` + `order`

`/works` 当前支持的排序字段包括：

- `created`
- `deposited`
- `indexed`
- `is-referenced-by-count`
- `issued`
- `published`
- `published-online`
- `published-print`
- `references-count`
- `relevance`
- `score`
- `updated`

这对 agent 很实用，因为你可以直接做：

- 最新优先：`sort=published&order=desc`
- 旧文回溯：`sort=published&order=asc`
- 高引用优先：`sort=is-referenced-by-count&order=desc`

### 3.5 聚合：`facet`

`/works` 支持 faceting。

高频 facet 包括：

- `type-name`
- `container-title`
- `publisher-name`
- `published`
- `issn`
- `funder-name`
- `funder-doi`
- `orcid`
- `ror-id`
- `relation-type`
- `source`
- `license`

适合：

- 检索结果概览
- 分面统计
- source / type / year / publisher 分布分析

需要注意：

- 官方明确说明 facet count 是 approximate
- 某些关系如果出现多次，会被重复计数

### 3.6 返回字段裁剪：`select`

`select` 只对 works endpoints 很关键。

当前 Swagger 允许选择的返回字段包括：

- `DOI`
- `ISBN`
- `ISSN`
- `URL`
- `abstract`
- `author`
- `container-title`
- `created`
- `deposited`
- `funder`
- `indexed`
- `is-referenced-by-count`
- `issued`
- `license`
- `link`
- `member`
- `page`
- `prefix`
- `published`
- `published-online`
- `published-print`
- `publisher`
- `reference`
- `references-count`
- `relation`
- `resource`
- `score`
- `subject`
- `title`
- `type`
- `update-to`
- `updated-by`
- `volume`

官方 tips 特别提醒：

- 如果你只需要 `2-3` 个字段，`select` 很有用
- 但如果你要的字段已经超过 `3-4` 个，`select` 反而可能让查询变慢
- 这时更建议直接取整条记录，再在本地丢弃不用的字段

### 3.7 抽样：`sample`

Swagger 明确支持：

- `sample=N`

适合：

- 调试
- 随机样本分析
- 快速检查 schema 覆盖

我在 2026-03-31 实测：

- `/v1/works?sample=2&select=DOI,title,type`
  - 可以正常返回随机 2 条 works

## 4. 分页、结果规模与同步策略

### 4.1 `rows`

当前官方 tips 明确说明：

- 默认 `rows=20`
- 最大 `rows=1000`
- 如果只想要总数，可以直接用 `rows=0`

我在 2026-03-31 实测：

- `/v1/works?rows=0&filter=from-pub-date:2025-01-01,until-pub-date:2025-12-31`
  - 返回 `items=[]`
  - 但会保留 `total-results`

这很适合：

- 先估算结果量
- 先做统计、再决定是否分页抓取

### 4.2 `cursor`

Crossref 官方建议大结果集优先用 cursor，而不是深 offset。

使用方式：

1. 首次请求加 `cursor=*`
2. 同时给 `rows>0`
3. 读取响应中的 `next-cursor`
4. 用 `cursor=[next-cursor]` 请求下一页
5. 当返回条数小于请求的 `rows` 时停止

需要注意：

- cursor `5` 分钟不使用会过期
- 即使到了最后一页，API 仍会返回一个 cursor
- 终止条件不是“cursor 消失”，而是“返回结果数小于 rows”

### 4.3 `offset`

Swagger 仍然支持 `offset`，但官方整体建议优先使用 cursor。

原因：

- cursor 没有深分页页码限制问题
- 对超大结果集更稳

### 4.4 大结果集同步建议

Crossref tips 给出的工程建议非常直接：

- 如果你要拉几十万、几百万条记录，先想清楚是否应该改用 bulk downloads
- 如果必须走 API，尽量把一个超大请求切成多个较小时间片请求
- 分天 / 分周拉取往往比“一把 cursor 到几千页”更稳
- 本地要做缓存，不要反复打同一请求

## 5. 认证、限流与版本

### 5.1 是否需要 API Key

结论：

- `不强制需要`
- 但实际开发非常建议至少使用 polite 方式标识自己

Crossref 当前官方 access 文档给出的接入方式有三类：

- `Public`
  - 无认证、无身份标识
- `Polite`
  - 用 `mailto` 参数或 `agent` header 提供邮箱
- `Metadata Plus`
  - 在 header 中带 `Crossref-Plus-API-Token: Bearer [API key]`

也就是说：

- 免费开发可以直接用
- 正式服务建议至少使用 polite pool
- 更高并发和更稳的生产接入可以考虑 Metadata Plus

### 5.2 当前官方限流

这部分需要特别注意，因为 Crossref 当前官方文档已经不是旧版本里常见的“50 req/s / 500 req/s”口径了。

根据 2025-10-16 更新的官方 access 文档，当前限制是：

- Public：
  - rate limit `5`
  - concurrency limit `1`
- Polite：
  - rate limit `10`
  - concurrency limit `3`
- Plus：
  - rate limit `150`
  - concurrency limit `None`

并且官方说明：

- 这些限制会通过响应头返回：
  - `x-rate-limit-limit`
  - `x-rate-limit-interval`
  - `x-concurrency-limit`
- 超限会返回 `429`
- 被人工 block 会返回 `403`

对当前项目的直接建议：

- 如果未来接 Crossref connector，默认按 polite pool 设计
- `mailto` 必带
- 并发不要超过 `3`
- 默认请求节流按 `~10 req/s` 的上限再保守一点更稳
- 对 `429` 做退避

### 5.3 版本策略

Crossref 官方 API versioning 文档当前结论是：

- REST API 是 versioned 的
- 你应该显式在请求里写版本
- 当前支持的版本只有 `V1`

推荐：

```text
https://api.crossref.org/v1/works?rows=0
```

补充说明：

- 不写版本时，当前仍会默认落到 `v1`
- 但官方明确说“为了安全起见，应该显式指定版本”

### 5.4 `mailto` 与 `User-Agent`

官方 best practice 明确建议：

- 在请求里提供 `mailto`
- 同时设置能标识服务的 `User-Agent`

这对生产服务非常重要，因为：

- 出现问题时官方能联系到你
- 更符合 polite pool 使用方式
- 更不容易因为“匿名高频请求”触发问题

## 6. Crossref 能返回哪些关键字段

从 Swagger 和 live 响应来看，works 里最常用的字段通常包括：

- 基础标识：
  - `DOI`
  - `URL`
  - `prefix`
  - `member`
- 标题与来源：
  - `title`
  - `subtitle`
  - `container-title`
  - `short-container-title`
  - `publisher`
  - `publisher-location`
  - `type`
- 作者与机构：
  - `author`
  - `editor`
  - `translator`
  - `chair`
  - `institution`
- 时间：
  - `created`
  - `deposited`
  - `indexed`
  - `issued`
  - `published`
  - `published-online`
  - `published-print`
  - `accepted`
- 影响力与参考文献：
  - `is-referenced-by-count`
  - `references-count`
  - `reference`
- 资助与关系：
  - `funder`
  - `relation`
  - `update-to`
  - `updated-by`
- 可获取性：
  - `license`
  - `link`
  - `resource`
  - `content-domain`
- 文本：
  - `abstract`
  - `subject`
  - `description`

### 6.1 对论文检索 agent 最有价值的字段

如果只是做第一版 connector，我建议优先保留这些：

- `DOI`
- `title`
- `author`
- `container-title`
- `publisher`
- `type`
- `issued` / `published`
- `abstract`
- `subject`
- `is-referenced-by-count`
- `references-count`
- `funder`
- `license`
- `link`
- `resource`
- `relation`

### 6.2 关于摘要和版权

这点很重要。

Crossref Metadata Retrieval 总览当前明确说明：

- 几乎所有 metadata 都可自由复用
- 但 `abstracts` 例外
- abstract 的版权仍归 publisher 或 author 持有

这意味着：

- 你可以在工程上使用 `abstract` 字段做检索和排序
- 但如果后续要做大规模再分发、训练语料、公开导出，就要单独评估版权边界

### 6.3 关于全文

Crossref 不会直接把论文正文文本塞进 REST API JSON 里返回。

它更像是：

- 返回 metadata
- 在部分记录里返回 license 和 full-text links

也就是说：

- `has-full-text`
  - 只是说明记录里有 full-text links
- `link` / `resource`
  - 可能给你 PDF、landing page、TDM 相关 URL
- 真正正文下载仍要请求 publisher 或内容托管方

所以 Crossref 更像：

- `metadata + fulltext-link signal`
不是：
- `full text content API`

## 7. Crossref 不支持什么

基于当前官方文档、Swagger 和我对公开能力边界的核对，可以比较稳妥地得出这些结论：

- `没有官方托管 SQL 查询接口`
- `没有公开向量/embedding 语义检索接口`
- `没有面向自然语言问句的 NLP 检索接口`
- `不是全文正文 API`

这里有两点需要明确说明：

1. `无 SQL` 是基于当前官方接口公开形态做出的结论  
   当前官方给出的主路径是 REST API、XML API、OAI-PMH、OpenURL、bulk downloads，而不是 SQL endpoint。

2. `无语义搜索` 是基于当前 REST API 文档和 Swagger 只公开 `query` / `query.*` / `filter` / `facet` / `sort` 这些能力做出的结论  
   如果后续 Crossref 发布了新的语义接口，需要再单独更新这份文档。

## 8. 对论文检索 agent 的接入建议

### 8.1 推荐角色

如果你的系统已经有：

- OpenAlex
- Semantic Scholar
- arXiv
- CORE
- Unpaywall

那么 Crossref 最推荐扮演的角色是：

- 高覆盖 DOI 元数据召回源
- 结构化过滤源
- citation lookup / DOI 补全源
- funding / license / relation / full-text-link 增强源

### 8.2 适合放在 Quick 还是 Deep

我的建议是：

- `Quick`
  - 适合
  - 尤其适合 query + filter 的宽覆盖召回
- `Deep`
  - 也适合
  - 但更适合提供结构化过滤和 metadata evidence，不适合单独承担语义相关性判断

原因：

- Crossref 覆盖广，但文本相关性能力不是它的最大强项
- 适合把它放在多源 recall 里做“补广度”
- 后续用本地 rerank / judge 去修正排序

### 8.3 推荐查询模板

#### 自由文本 + 年份 + 类型

```text
/v1/works
?query.bibliographic=graph neural retrieval
&filter=from-pub-date:2023-01-01,until-pub-date:2026-12-31,type:journal-article
&sort=relevance
&rows=20
&select=DOI,title,author,container-title,abstract,published,type,is-referenced-by-count,link,license
```

#### 按 funder 查论文

```text
/v1/funders/501100000038/works
?filter=type:journal-article,from-pub-date:2024-01-01
&rows=20
&select=DOI,title,author,published,funder
```

#### 只拉“有摘要 + 有 full-text link”的候选

```text
/v1/works
?query=large language model
&filter=has-abstract:true,has-full-text:true,type:journal-article
&rows=20
&select=DOI,title,abstract,link,license,resource
```

#### 做增量同步

```text
/v1/works
?filter=from-index-date:2026-03-01,until-index-date:2026-03-31
&rows=500
&cursor=*
```

### 8.4 和现有源的角色差异

和当前仓库里已经有的源相比，我建议这样理解：

- OpenAlex：
  - 更像“结构化学术图谱 + 检索体验更现代”的主力源
- Semantic Scholar：
  - 更像“论文搜索 + citation/reference 图谱 + snippet/推荐增强”
- Crossref：
  - 更像“最基础、覆盖极广的 DOI 元数据基础设施”
- Unpaywall：
  - 更像“DOI -> OA/fulltext resolver”

所以更合理的组合通常是：

1. 用 OpenAlex / Semantic Scholar / Crossref 做多源召回
2. 用本地统一 schema 做去重与 rerank
3. 命中 DOI 后用 Unpaywall 做 OA / fulltext resolve

## 9. 2026-03-31 的少量 live 验证

为了避免只停留在文档概览，我额外做了几次轻量实测，结论如下：

- `/v1/works?rows=0&filter=...`
  - 正常返回 `total-results`
- `/v1/works?sample=2&select=DOI,title,type`
  - 正常返回随机 works
- `/v1/works?filter=...&facet=type-name:*&rows=0`
  - 正常返回 facet 统计
- `/v1/works?filter=from-pub-date:2025-01-01&rows=1&cursor=*`
  - 正常返回 `next-cursor`
- `/v1/works/{doi}`
  - 正常返回 `200`
- `/v1/works/doi/{doi}`
  - 当前也返回 `200`
- `/v1/works/{doi}/agency`
  - 正常返回 `agency.id = crossref`

另外，2026-03-31 对 `/v1/works?rows=1` 的 live 返回中，`message.total-results` 已经是 `180,621,416` 级别，这和 Crossref 2026-03-17 官方博客里“今年 public data file 接近 1.8 亿条记录”的口径是一致的。

## 10. 最终判断

如果你问的是：

- `Crossref 能不能作为论文检索主 API 之一？`

答案是：

- `可以，而且很值得接`

如果你问的是：

- `Crossref 能不能单独承担高质量语义论文搜索？`

答案是：

- `不建议`

如果你问的是：

- `Crossref 最适合干什么？`

答案是：

- `做高覆盖 DOI 元数据检索、结构化过滤、citation lookup、funding/license/relation/full-text-link 增强`

如果你问的是：

- `它能不能给你摘要、关系、参考文献、资助、license、full-text link？`

答案是：

- `经常可以，但覆盖取决于 member deposit 质量`

如果你问的是：

- `它能不能直接给你论文正文？`

答案是：

- `不能直接给正文，但能给一部分 full-text links`

## 11. 开发时可直接记住的 Checklist

- `主检索 endpoint 是 /v1/works`
- `DOI 详情回表是 /v1/works/{doi}`
- `DOI agency 校验是 /v1/works/{doi}/agency`
- `显式使用 /v1，不要依赖无版本默认路由`
- `rows 默认 20，最大 1000`
- `大结果集用 cursor，不要深翻 offset`
- `rows=0` 很适合先拿总数
- `select` 适合少数字段，不适合选太多字段
- `type:journal-article` 这类过滤非常重要，否则会混进大量非论文记录
- `has-abstract`、`has-full-text`、`has-orcid`、`has-funder` 很实用
- `from-index-date` 比 `from-pub-date` 更适合做增量同步
- `至少用 polite pool：mailto + User-Agent`
- `当前官方限流不是旧口径，按 Public 5 / Polite 10 / Plus 150 理解`
- `Crossref 不是语义搜索和全文正文 API`

## 12. 资料来源

本文件主要依据以下官方来源整理：

- Metadata Retrieval 总览  
  `https://www.crossref.org/documentation/retrieve-metadata/`
- REST API 总览  
  `https://www.crossref.org/documentation/retrieve-metadata/rest-api/`
- REST API Filters  
  `https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/`
- Access and authentication  
  `https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/`
- Tips and tricks  
  `https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/`
- API versioning  
  `https://www.crossref.org/documentation/retrieve-metadata/api-versioning/`
- Swagger UI  
  `https://api.crossref.org/swagger-ui/index.html`
- Swagger Docs  
  `https://api.crossref.org/swagger-docs`

## 13. 说明与保守结论

我这里有几处是明确按“保守口径”写的：

1. 关于 `SQL / semantic / NLP`
   - 我没有看到 Crossref 当前官方文档公开这些能力
   - 所以文中按“不支持公开接口”处理
   - 这是基于当前官方资料做出的工程结论

2. 关于摘要与 full-text link 的覆盖率
   - Crossref 官方明确说明 metadata 主要来自 member deposit 和少量外部 enrichments
   - 所以工程上应该默认“字段覆盖不均匀”
   - 不要把 `abstract`、`link`、`license` 当成 100% 稳定存在

3. 关于 `/works/doi/{doi}`
   - 当前 live 请求可用
   - 但 Swagger 规范路径是 `/works/{doi}`
   - 因此仍建议以 Swagger 路径为主
