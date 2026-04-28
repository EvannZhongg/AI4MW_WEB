# Unpaywall API 调研笔记

更新日期：2026-03-29

这份文档基于 Unpaywall 当前可获取的官方文档整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- Unpaywall 现在支持哪些查询方式
- 是否支持 SQL / NLP / 自然语言 / 语义搜索
- 能检索哪些字段、能返回哪些字段
- 是否需要 API Key
- 速率限制、并发要求、批量下载方式分别是什么
- 能否直接拿到摘要或正文
- 做 agent 时最适合把 Unpaywall 放在哪个环节

## 结论先看

Unpaywall 不是一个通用“论文检索搜索引擎 API”，它更准确地说是一个：

- 基于 DOI 的 Open Access 状态与全文链接解析服务
- 附带一个非常基础的标题检索接口
- 以及一个适合批量本地处理的 OA 元数据数据库

如果你的目标是做“论文检索 agent”，Unpaywall 最适合承担的是：

- 已知 DOI 后，判断论文是否 OA
- 找最佳 OA 全文入口
- 拿 PDF 链接或落地页链接
- 提供 OA 颜色状态（gold / hybrid / bronze / green / closed）
- 作为全文抓取前的合法 OA resolver

它不适合承担的是：

- 主检索引擎
- 多字段高级检索引擎
- 摘要/作者/机构/期刊的结构化搜索
- 自然语言问句检索
- 语义向量检索
- SQL 查询服务

一句话总结：

- `Unpaywall 更像“DOI -> OA/fulltext location resolver”`
- `不是 OpenAlex / Semantic Scholar / Elasticsearch 那类综合文献检索 API`

## 1. 官方文档入口现状

当前 Unpaywall 的官方信息分散在几处：

- 主产品页：`https://unpaywall.org/products/api`
- 数据格式页：`https://unpaywall.org/data-format`
- 官方支持站：`https://support.unpaywall.org`
- 官方博客：`https://blog.ourresearch.org` / `https://blog.openalex.org`

需要注意的是：

- 当前主产品页和 data-format 页是 JS 渲染页面，纯文本抓取不友好。
- 但官方支持站仍保留了可直接阅读的 FAQ，包含标题搜索、字段、OA 状态、host_type、oa_date 等关键说明。
- 2025-07-29 官方博客再次确认：`API & data feed URLs` 没变，`All keys stay the same`，只有 `oa_locations.evidence` 和 `oa_locations.updated` 被标记为 deprecated。

所以对开发来说，可以把下面这几类信息当成“当前仍有效”：

- `GET /v2/:doi`
- `GET /v2/search?...`
- `email` 参数要求
- `100,000 calls/day` 速率建议
- 绝大多数字段名
- OA 颜色、host_type、best_oa_location 等语义

## 2. 当前支持哪些访问 / 检索方式

### 2.1 DOI 精准查询：`GET /v2/:doi`

这是 Unpaywall 的主接口。

示例：

```text
GET https://api.unpaywall.org/v2/10.1038/nature12373?email=YOUR_EMAIL
```

官方描述：

- 输入一个有效 DOI
- 返回一个 `DOI Object`
- 内容是该 DOI 的 OA 状态、书目信息和 OA location 信息

适合：

- 已知 DOI，补齐元数据
- 判断是否开放获取
- 获取最佳 OA PDF/落地页
- 在检索召回后做“是否能读全文”的解析

### 2.2 标题检索：`GET /v2/search`

示例：

```text
GET https://api.unpaywall.org/v2/search?query=cell%20thermometry&is_oa=true&email=YOUR_EMAIL
```

这是 Unpaywall 唯一公开说明的“搜索”接口，但能力非常有限。

核心特点：

- 只搜索标题
- 不搜索作者、机构、期刊、摘要、全文正文
- 每次返回 50 条
- 只支持 `is_oa` 这一个属性过滤
- 只支持按相关性排序
- 用 `page` 翻页

适合：

- 以题名关键词粗召回
- 只关心“有无 OA 全文”的标题级搜索

不适合：

- 学术搜索主引擎
- 高级字段检索
- 检索质量要求高的 agent 第一召回

### 2.3 Redirect service

官方还提供重定向服务：

```text
https://unpaywall.org/<DOI>
https://oadoi.org/<DOI>
```

作用：

- 如果有最佳 OA 位置，直接跳过去
- 如果没有，就跳到 publisher page

这不是元数据 API，但很适合：

- 浏览器插件
- “一键打开可读全文”
- 最终用户跳转链路

### 2.4 批量 / 离线访问

官方长期明确提供几种替代方式：

- `Simple Query Tool`：适合你已经有 DOI 列表时做批量查询
- `Database Snapshot`：完整数据库快照，适合本地部署
- `Data Feed`：面向订阅用户的高吞吐增量更新渠道

其中：

- 快照是免费的
- Data Feed 是付费产品
- 官方博客和历史官方说明都提到 Data Feed 提供 weekly updates

如果你要做大规模 agent、离线索引或高吞吐服务，官方建议优先走 snapshot / data feed，而不是高频打免费 API。

## 3. 当前支持哪些查询语法

### 3.1 `GET /v2/:doi` 不是搜索语法，而是 ID lookup

这个接口不支持布尔表达式或字段过滤，本质上就是：

- 传入一个 DOI
- 拿回该 DOI 的记录

### 3.2 `GET /v2/search` 的查询语法

官方文档对 `query` 的说明如下：

- 词项之间默认是 `AND`
- 支持双引号短语检索
- 支持大写 `OR`
- 支持前缀 `-` 做排除

#### 3.2.1 默认 AND

```text
query=cell thermometry
```

含义：

- 标题必须同时包含 `cell` 和 `thermometry`

#### 3.2.2 短语检索

```text
query="wave particle duality"
```

含义：

- 标题中必须出现这个完整短语

#### 3.2.3 OR

```text
query=wave OR particle
```

含义：

- 标题中匹配任一词即可

注意：

- 官方示例和文案都写的是大写 `OR`
- 没看到官方说明支持更复杂的布尔括号表达式

#### 3.2.4 排除

```text
query=wave -ocean
```

含义：

- 标题包含 `wave`
- 但不包含 `ocean`

## 4. 支持哪些“检索方式”

这是你开发前最需要澄清的一点。

### 4.1 支持的方式

- DOI 精确查询
- 标题关键词检索
- 标题短语检索
- 标题 OR 检索
- 标题排除词检索
- `is_oa` 布尔过滤

### 4.2 不支持的方式

基于当前官方文档，可以确认以下能力没有公开提供：

- SQL 查询
- GraphQL
- 向量检索 / embedding 检索
- 语义搜索
- 自然语言问句搜索
- 作者检索
- 机构检索
- 期刊字段检索
- 摘要检索
- 正文全文检索
- 多字段过滤 DSL

因此，如果你原本想把 Unpaywall 当作“自然语言论文搜索引擎”，结论是：

- `不合适`

更合理的架构是：

- 用 OpenAlex / Semantic Scholar / Crossref / Elasticsearch 做检索
- 用 Unpaywall 做 DOI 级 OA 与全文可得性解析

## 5. 能检索哪些字段

### 5.1 搜索端点可检索字段

`/v2/search` 当前只检索：

- `title`

官方 FAQ 明确写了：

- 不搜索 authors
- 不搜索 affiliations
- 不搜索 journal names
- 不搜索 abstracts
- 不搜索 anything else

### 5.2 搜索端点可过滤字段

当前官方只公开了一个过滤参数：

- `is_oa`

可选值：

- `true`
- `false`
- 不传

除此以外，没有看到官方公开更多筛选字段。

## 6. 能返回哪些字段

官方当前可直接确认的是：API 响应和 snapshot / data feed 共享同一套 schema。

官方支持页列出的字段包括：

- `best_oa_location`
- `data_standard`
- `doi`
- `doi_url`
- `first_oa_location`
- `genre`
- `has_repository_copy`
- `is_oa`
- `is_paratext`
- `journal_is_in_doaj`
- `journal_is_oa`
- `journal_issn_l`
- `journal_issns`
- `journal_name`
- `oa_locations`
- `oa_locations_embargoed`
- `oa_status`
- `published_date`
- `publisher`
- `title`
- `year`
- `z_authors`

以及 OA location 子对象字段：

- `endpoint_id`
- `evidence`
- `host_type`
- `is_best`
- `license`
- `oa_date`
- `pmh_id`
- `repository_institution`
- `updated`
- `url`
- `url_for_landing_page`
- `url_for_pdf`
- `version`

### 6.1 建议你重点使用的顶层字段

| 字段 | 用途 | 说明 |
| --- | --- | --- |
| `doi` | 主键 | DOI，建议统一转小写保存 |
| `doi_url` | 跳转 | DOI 对应 URL |
| `title` | 展示 / 粗匹配 | 标题 |
| `year` | 过滤 / 排序 | 年份 |
| `published_date` | 更精确时间过滤 | 发布日期 |
| `genre` | 类型识别 | Crossref 内容类型，常见如 `journal-article` |
| `publisher` | 展示 / 分析 | 出版商 |
| `journal_name` | 展示 / 去重辅助 | 期刊名 |
| `journal_issns` | 期刊识别 | ISSN 列表 |
| `journal_issn_l` | 期刊聚合 | Linking ISSN |
| `z_authors` | 作者展示 | 作者列表 |
| `is_oa` | 是否开放获取 | 最常用布尔字段 |
| `oa_status` | OA 分类 | `closed / green / gold / hybrid / bronze` |
| `has_repository_copy` | 是否有仓储副本 | 对抓全文很有用 |
| `best_oa_location` | 最佳全文入口 | 生产里最该优先取的 location |
| `oa_locations` | 所有 OA 位置 | 兜底与比对 |
| `oa_locations_embargoed` | 将来可能开放的位置 | 可用于 embargo 感知 |
| `first_oa_location` | 最早开放位置 | 适合做 OA 时间线分析 |
| `journal_is_oa` | 期刊是否 fully OA | 用于 gold 判断 |
| `journal_is_in_doaj` | 是否在 DOAJ | 更保守的“OA 期刊可信标记” |
| `is_paratext` | 是否为非正文型期刊附属内容 | 过滤封面、目录等很有用 |

### 6.2 OA location 子对象字段怎么理解

| 字段 | 作用 | 开发建议 |
| --- | --- | --- |
| `url` | 当前 OA 位置主 URL | 有 PDF 时通常就是 PDF URL，否则通常是落地页 |
| `url_for_pdf` | PDF 直链 | 全文抓取优先用它 |
| `url_for_landing_page` | 落地页 | 没 PDF 时回退到它 |
| `host_type` | `publisher` 或 `repository` | 用来区分 publisher copy 和 repository copy |
| `version` | `publishedVersion` / `acceptedVersion` / `submittedVersion` | 可用来做版本优先级 |
| `license` | 开放许可 | 判断可复用性 |
| `oa_date` | 该位置第一次可 OA 的日期 | 做 embargo / OA 时间线时有用 |
| `is_best` | 是否最佳位置 | 一般和 `best_oa_location` 对齐 |
| `repository_institution` | 仓储机构名 | 展示和质量分析有用 |
| `endpoint_id` | 仓储端点标识 | 做仓储统计时有用 |
| `pmh_id` | OAI-PMH 标识 | 仓储回溯时有用 |
| `evidence` | 该位置如何被识别 / 归类 | 2025 起被标记 deprecated |
| `updated` | 该位置记录更新时间 | 2025 起被标记 deprecated |

## 7. 一些关键字段的官方语义

### 7.1 `oa_status`

官方定义 5 种值：

- `closed`
- `green`
- `gold`
- `hybrid`
- `bronze`

判定逻辑可以简化为：

1. `is_oa = false` -> `closed`
2. `is_oa = true` 且 `best_oa_location.host_type = repository` -> `green`
3. `is_oa = true` 且 `host_type = publisher` 且 `journal_is_oa = true` -> `gold`
4. `is_oa = true` 且 publisher 位置有开放许可 -> `hybrid`
5. `is_oa = true` 且 publisher 位置无开放许可 -> `bronze`

### 7.2 `host_type`

官方只定义两类：

- `publisher`
- `repository`

其中：

- `publisher` 通常表示原始出版商提供的可访问版本
- `repository` 通常表示机构仓储、学科仓储、预印本平台等

需要注意一个历史语义：

- 自 2020-05-01 起，预印本服务器上的位置被重新归类为 `repository`
- 所以很多 preprint / postprint 的 OA 状态会是 `green`

### 7.3 `best_oa_location`

官方明确说明：

- 当一篇文章有多个 OA location 时，会选一个“最当前、最权威”的位置
- 这个位置是 `oa_locations` 中排序第一的那个

排序依据依次包括：

1. `publisher` 优于 `repository`
2. `publishedVersion` 优于 `acceptedVersion`，后者优于 `submittedVersion`
3. 有 `url_for_pdf` 优于没有
4. repository 中 DOI 匹配优于标题匹配
5. 大型仓储会有额外排序优先级

这意味着生产里通常可以直接：

- 先用 `best_oa_location.url_for_pdf`
- 再回退 `best_oa_location.url_for_landing_page`
- 再回退遍历 `oa_locations`

### 7.4 `journal_is_oa` 和 `journal_is_in_doaj`

官方说明：

- `journal_is_oa=true` 表示 Unpaywall 认为该期刊是 fully OA
- `journal_is_in_doaj=true` 表示它明确在 DOAJ 中

两者区别：

- `journal_is_oa` 更宽
- `journal_is_in_doaj` 更保守、更接近 DOAJ 白名单语义

也就是说：

- `journal_is_oa=true` 且 `journal_is_in_doaj=false` 是可能出现的

### 7.5 `is_paratext`

这个字段很适合做数据清洗。

官方说：

- Unpaywall 会索引很多“带 DOI 但不是真正论文正文”的内容
- 比如封面、目录、masthead、title page 等

所以如果你是做论文检索 agent，建议默认过滤：

- `is_paratext=true`

### 7.6 `oa_date`

官方定义：

- 该 OA 位置上，这个版本首次可自由访问的日期

但要注意：

- Bronze 的 `oa_date` 当前通常是 `null`
- repository 的 `oa_date` 可靠性受仓储时间戳质量影响
- 官方从 `2020-08-07` 起才开始系统记录更可靠的 repository 首次可用时间

## 8. 是否需要 API Key

当前官方文档的结论非常明确：

- `不需要 API key`
- `也不是 token auth`
- `但每个请求都必须带 email 参数`

示例：

```text
https://api.unpaywall.org/v2/10.1038/nature12373?email=YOUR_EMAIL
```

这更像是：

- 身份标识 / 联系方式要求

而不是：

- 访问密钥

工程建议：

- 用团队统一邮箱，例如 `research-agent@yourdomain.com`
- 不要在客户端硬编码个人邮箱
- 在服务端代理层统一注入 `email`

## 9. 速率限制和并发要求

### 9.1 官方明确写出的限制

官方产品页当前可确认的要求是：

- `Please limit use to 100,000 calls per day`

并且官方直接建议：

- 如果你需要更快访问，请下载整个 database snapshot 在本地使用

### 9.2 官方没有明确写出的部分

在当前能找到的官方公开文档里，我没有看到这些更细颗粒度规则：

- 每秒请求数硬上限
- 并发连接数硬上限
- burst 上限
- 429 返回策略说明

所以目前更稳妥的工程结论是：

- `唯一明确公开的限流要求是 100,000 次/天`
- `官方未公开更细的 QPS / 并发硬限制`
- `如果你的服务会明显超过这个量，应优先走 snapshot 或 data feed`

### 9.3 工程落地建议

建议你自己在客户端做保守限流：

- 单实例默认控制在低 QPS
- 做请求缓存，key 用 DOI
- 对 title search 做更严格缓存
- 把 Unpaywall 放在“候选结果回表 / 全文解析”阶段，而不是每次 query 大规模扫

## 10. 下载条件与全文可得性条件

这是做全文抓取时最关键的一节。

### 10.1 Unpaywall 认为什么算 OA location

官方 FAQ 说明：

- 只要某个页面能让用户免费拿到全文
- 无论是直接 PDF
- HTML 中嵌入阅读器
- 或能在落地页进一步拿到 PDF
- 都可能被收录为 OA location

### 10.2 官方明确排除或谨慎处理的条件

官方历史 FAQ 明确提到，以下情况通常不符合他们想要的 OA location 条件：

- 需要注册登录
- CAPTCHAs
- 无法稳定机器读取

官方 2020 FAQ 中举例：

- ResearchGate 因需要登录，不纳入
- SSRN 因 CAPTCHA / 账号要求而被认为不理想

但需要注意时间变化：

- 2025-08-28 官方博客又提到，他们已经把 SSRN 视为 open repository

所以这类边界站点的策略是会演化的，开发时不要把历史例外写死在代码里，最好以当前 API 返回为准。

### 10.3 对“下载正文”意味着什么

Unpaywall 本身做的是：

- 告诉你哪里有合法 OA 副本

它不等于：

- 替你托管正文文件

也就是说：

- 你通常拿到的是 `url_for_pdf` 或 `url_for_landing_page`
- 真正下载 PDF / HTML 正文时，请求发往 publisher 或 repository 站点
- 最终仍需遵守目标站点的 license / TOS / robots 规则

## 11. 能否直接读到正文或摘要

### 11.1 正文

当前官方可确认的结论是：

- API 响应里会给你全文入口 URL
- 但不会把正文文本直接内嵌在 API JSON 里返回

也就是说：

- `能拿到全文链接`
- `不能直接从 Unpaywall API 响应里拿到正文内容`

### 11.2 摘要

当前官方字段列表和公开示例中，没有出现摘要字段。

再结合官方对 `/v2/search` 的说明：

- 不搜索 abstracts

可以做出较稳妥的工程判断：

- `Unpaywall API 不是面向摘要消费设计的`
- `当前公开文档没有把 abstract 作为标准返回字段来说明`

因此开发上应该按下面处理：

- `不要把 Unpaywall 当摘要来源`
- 摘要请优先从 OpenAlex / Crossref / Semantic Scholar / PubMed / arXiv 等来源补

### 11.3 这一点对 agent 设计的直接影响

如果你想做：

- 用户自然语言提问
- 摘要级 rerank
- 回答生成

那么 Unpaywall 只能提供：

- OA 状态
- 全文可达 URL

不能单独完成：

- 语义召回
- 摘要摘要化
- 正文直接返回

## 12. 返回结果分页、排序与覆盖范围

### 12.1 标题搜索分页

`/v2/search`：

- 每页 50 条
- `page=1` 或不传：1-50
- `page=2`：51-100

### 12.2 排序

标题搜索当前只支持：

- relevance ranking

官方没有公开：

- 时间排序
- 引用排序
- OA 优先排序
- 自定义排序字段

### 12.3 覆盖范围

官方 FAQ 明确写了：

- Unpaywall 只覆盖 `Crossref` 注册的 DOI

因此：

- 非 Crossref DOI 可能直接 404
- 即使 DOI 有效，只要不是 Crossref 体系，也可能不在 Unpaywall 中

这是个非常重要的边界条件。

## 13. 当前版本与最近的重要变化

### 13.1 版本

官方历史产品页说明：

- 当前 API 版本是 `v2`
- 也是唯一支持版本

### 13.2 2025 年的重要变化

官方 2025-07-29 博客确认：

- 2025-05-20 上线了新的 Unpaywall codebase
- API 和 data feed URL 不变
- schema key 保持不变
- 只有两个字段被标记 deprecated：
  - `oa_locations.evidence`
  - `oa_locations.updated`

这意味着你现在开发时最好：

- 可以继续读取这两个字段
- 但不要把它们作为未来强依赖

### 13.3 2026 年的更大背景

官方 2026-01-05 博客写到：

- `Unpaywall is a slice of the OpenAlex database delivered in a specific format`

从系统设计角度，这说明：

- Unpaywall 正在更深地和 OpenAlex 的底层数据体系对齐
- 如果你后续同时接 OpenAlex 和 Unpaywall，字段语义的协调会越来越容易

## 14. 对论文检索 agent 的接入建议

### 14.1 推荐架构

推荐你把 Unpaywall 放在检索链路的第 3 或第 4 步：

1. 用 OpenAlex / Semantic Scholar / Crossref / arXiv 做召回
2. 用标题、摘要、年份、作者、引用等做重排
3. 对候选论文拿 DOI
4. 用 Unpaywall 查询 OA 状态与全文入口
5. 如果 `url_for_pdf` 存在，则抓取 PDF
6. 如果只有 `url_for_landing_page`，再做页面解析

### 14.2 不推荐的架构

不建议：

1. 用户输入自然语言问题
2. 直接把问题丢给 Unpaywall `/v2/search`
3. 指望它给出高质量论文检索结果

原因很简单：

- 它只搜标题
- 没摘要
- 没作者
- 没复杂过滤
- 没语义检索

### 14.3 一个非常实用的工程策略

如果你的主搜索结果里已经有 DOI，那么 Unpaywall 的价值非常高：

- `低成本`
- `语义明确`
- `返回结构稳定`
- `特别适合做全文可得性解析`

因此最佳实践通常是：

- `Search elsewhere, resolve OA with Unpaywall`

## 15. 最终判断

如果你问的是：

- `Unpaywall 能不能作为论文检索主 API？`

答案是：

- `不建议`

如果你问的是：

- `Unpaywall 能不能作为论文全文可达性与 OA 状态解析 API？`

答案是：

- `非常适合`

如果你问的是：

- `它支不支持 SQL / NLP / 语义搜索 / 摘要检索 / 正文检索？`

答案是：

- `当前官方公开文档下都不支持`

如果你问的是：

- `它能不能给我拿到 PDF 或全文落地页？`

答案是：

- `可以，这是它最有价值的部分`

## 16. 开发时可直接记住的 Checklist

- `主接口是 /v2/:doi`
- `搜索接口只有 /v2/search，而且只搜标题`
- `不需要 API key，但必须带 email`
- `官方明确限额是 100,000 calls/day`
- `大规模使用优先 snapshot / data feed`
- `只覆盖 Crossref DOI`
- `最关键字段是 is_oa / oa_status / best_oa_location / oa_locations / url_for_pdf`
- `不能把 Unpaywall 当摘要或正文 API`
- `2025 起 oa_locations.evidence 和 oa_locations.updated 已 deprecated`

## 17. 资料来源

本文件主要依据以下官方来源整理：

- Unpaywall 官方 REST API 页面（官方产品页的归档文本版）：`https://archive.ph/rfXEp`
- Unpaywall 官方支持页：
  - `How do I use the title search API?`
  - `What do the fields in the API response and snapshot records mean?`
  - `What do the types of oa_status (green, gold, hybrid, and bronze) mean?`
  - `What do the host_type values "publisher" and "repository" mean?`
  - `What does oa_date mean and how is it determined?`
  - `How is the best OA location determined?`
  - `Which DOIs does Unpaywall cover?`
  - `What counts as an Open Access location?`
  - `How do we decide if a given journal is fully OA?`
  - `What does is_paratext mean in the API?`
  - `Unpaywall Change Notes`
- 官方博客 / OpenAlex 博客：
  - `Major Update to Unpaywall Database`（2025-07-29）
  - `Unpaywall improvements: more gold, better green`（2025-08-28）
  - `OpenAlex: 2025 in Review`（2026-01-05 / 2026-01-07）

## 18. 说明与保守结论

有两点我特意保守处理了：

1. 当前 `unpaywall.org/data-format` 页面是 JS 渲染，纯文本环境下不方便直接读到整页内容。
2. 因此，像 `data_standard`、`first_oa_location`、`oa_locations_embargoed` 这类较少用字段，我在正文里只写了足够支撑工程决策的层面，没有冒进地补写一堆无法从当前官方可读页面直接逐项核验的细节。

这不影响你做 agent 的主链路开发，因为真正高频会用到的字段和限制已经足够清楚：

- 查询入口
- 搜索边界
- 认证方式
- 限流
- OA 状态语义
- 全文链接字段
- 批量下载替代方案
