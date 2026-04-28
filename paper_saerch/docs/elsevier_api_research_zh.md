# Elsevier API 调研笔记

更新日期：2026-03-30

这份文档基于 Elsevier 当前官方开发者文档、官方 WADL 接口规范、官方鉴权说明、官方 API Key 配额页面，以及官方 FAQ/support 页面整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- Elsevier 当前公开了哪些和论文检索相关的官方 API
- 哪些 API 适合做“主搜索”，哪些更适合做“详情补齐”或“全文获取”
- 是否支持 SQL / 自然语言问句 / 语义搜索
- 查询语法、分页、视图、字段裁剪怎么用
- 是否需要 API Key，鉴权有哪些模式
- 限流、周配额、结果集上限分别是什么
- 针对当前项目，应该怎样设计 Elsevier connector

## 结论先看

如果你的目标是给当前项目接入一个“Elsevier 来源”，最推荐的官方组合是：

- 主搜索：`Scopus Search API`
- 详情补齐：`Abstract Retrieval API`

原因很直接：

- `Scopus Search API` 适合做跨出版商的论文元数据检索，覆盖面明显比只查 Elsevier 自家内容更广。
- `Abstract Retrieval API` 适合在你已经拿到 DOI、EID、Scopus ID、PII 之后补齐摘要、作者、学科、关键词等 richer metadata。
- `ScienceDirect Search API` 更适合做 “Elsevier / ScienceDirect 托管内容内检索”，不是最适合作为通用论文搜索主入口。
- `Article Retrieval API` 更偏全文/文章对象/PDF 获取，权限和 entitlement 约束更强，不适合直接作为 `quick_search` 主接口。

关于你关心的 “SQL / NLP / 语义搜索”：

- `SQL`：官方没有提供托管 SQL 查询接口。
- `自然语言问句检索`：官方没有提供“把一句自然语言需求直接理解为结构化条件”的独立接口。
- `语义搜索`：当前公开文档里没有类似 embedding / semantic search 的公开检索 API。
- 官方公开的是典型的 REST + 字段化布尔检索模式，尤其 Scopus 的查询语法是 fielded query language，不是 SQL，也不是 LLM 风格问句接口。

## 1. 官方文档入口与产品边界

当前和接入最相关的 Elsevier 官方入口主要有这些：

| 文档 | 地址 | 用途 |
| --- | --- | --- |
| Scopus APIs 总览 | `https://dev.elsevier.com/sc_apis.html` | 看 Scopus 产品线和入口 |
| Scopus Search API | `https://dev.elsevier.com/documentation/SCOPUSSearchAPI.wadl` | 搜索接口规范 |
| Scopus Search Tips | `https://dev.elsevier.com/sc_search_tips.html` | 查询语法与字段代码 |
| Scopus Search Views | `https://dev.elsevier.com/sc_search_views.html` | 搜索结果字段说明 |
| Abstract Retrieval API | `https://dev.elsevier.com/documentation/AbstractRetrievalAPI.wadl` | 详情/摘要拉取规范 |
| Abstract Retrieval Views | `https://dev.elsevier.com/sc_abstract_retrieval_views.html` | 详情字段说明 |
| ScienceDirect Search API | `https://dev.elsevier.com/documentation/ScienceDirectSearchAPI.wadl` | ScienceDirect 搜索规范 |
| ScienceDirect Search Views | `https://dev.elsevier.com/sd_search_views.html` | ScienceDirect 搜索字段说明 |
| Article Retrieval API | `https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl` | 全文/文章对象/PDF 获取 |
| Authentication Guide | `https://dev.elsevier.com/tecdoc_api_authentication.html` | 鉴权方式 |
| Default API Key Settings | `https://dev.elsevier.com/api_key_settings.html` | 周配额与速率限制 |
| Support / FAQ | `https://dev.elsevier.com/support.html` | 产品边界与常见问题 |

官方 FAQ 里对产品边界的描述很重要：

- `Scopus` 更像跨出版商的文献元数据、摘要、引用、参考文献与 profile 数据库。
- `ScienceDirect` 更像全文内容平台，主要是 Elsevier 自家和部分托管内容。
- ScienceDirect 和 Scopus 是分开的产品线，Scopus 里的标识如 `Scopus ID`、`AF-ID` 不能直接拿去当 ScienceDirect 搜索条件。

对当前项目来说，这意味着：

- 如果你想做“通用论文搜索源”，优先接 `Scopus Search`
- 如果你想做“Elsevier 自家内容补充源”，再考虑 `ScienceDirect Search`

## 2. 当前公开可用的核心 API

### 2.1 Scopus Search API

主 endpoint：

```text
GET https://api.elsevier.com/content/search/scopus
```

适合场景：

- 用户输入关键词后做首轮候选召回
- 按标题/摘要/关键词/DOI/主题等字段检索
- 做跨出版商论文元数据搜索

核心参数：

- `query`
- `start`
- `count`
- `view`
- `field`

返回格式：

- `application/json`
- `application/atom+xml`
- `application/xml`

视图：

- `STANDARD`
- `COMPLETE`
- `COMPONENT`

工程建议：

- 首版 connector 直接从 `view=STANDARD` 起步
- 如果列表结果里摘要不稳定或字段不够，再对 top N 做 `Abstract Retrieval` 补齐

### 2.2 Abstract Retrieval API

主 endpoint 家族：

```text
GET https://api.elsevier.com/content/abstract/scopus_id/{scopus_id}
GET https://api.elsevier.com/content/abstract/eid/{eid}
GET https://api.elsevier.com/content/abstract/doi/{doi}
GET https://api.elsevier.com/content/abstract/pii/{pii}
GET https://api.elsevier.com/content/abstract/pubmed_id/{pubmed_id}
GET https://api.elsevier.com/content/abstract/pui/{pui}
```

适合场景：

- 已知某篇论文的 DOI / EID / Scopus ID 后补齐详情
- 拉摘要、作者、学科、关键词、机构等 richer metadata

支持格式：

- `text/xml`
- `application/xml`
- `application/json`
- `application/rdf+xml`

视图：

- `META`
- `META_ABS`
- `FULL`
- `REF`
- `ENTITLED`

工程建议：

- 对当前项目最实用的是 `META_ABS`
- `FULL` 只在你确实有 entitlement 且需要更重 payload 时再用

### 2.3 ScienceDirect Search API

主 endpoint：

```text
GET https://api.elsevier.com/content/search/sciencedirect
```

适合场景：

- 单独做 Elsevier / ScienceDirect 托管内容检索
- 想拿到 `scidir` 落地页、`pii`、open access 标记等 ScienceDirect 侧字段

核心参数：

- `query`
- `start`
- `count`
- `sort`
- `date`
- `field`

WADL 里明确写到：

- `start` 允许 `0-6000`
- `count` 允许 `10, 25, 50, 100`
- `sort` 可用 `coverDate`、`relevance`
- `date` 支持形如 `2002-2007`

注意：

- 官方 `API Key Settings` 页面又把 ScienceDirect Search v2 写成了 `STANDARD view / Max 200 results / 6000 item total results limit / 2 requests per second`
- 这和 WADL 中 `count` 的枚举值存在轻微不一致
- 因此联调时建议以“真实账号返回 + 当前账号配置”为准，不要只按单页文档写死

### 2.4 Article Retrieval API

主 endpoint 家族：

```text
GET https://api.elsevier.com/content/article/doi/{doi}
GET https://api.elsevier.com/content/article/pii/{pii}
GET https://api.elsevier.com/content/article/eid/{eid}
GET https://api.elsevier.com/content/article/scopus_id/{scopus_id}
GET https://api.elsevier.com/content/article/pubmed_id/{pubmed_id}
```

适合场景：

- 已知文章标识后取文章对象或全文
- 获取 PDF 或图片化页面

支持格式：

- `text/xml`
- `application/json`
- `application/pdf`
- `image/png`
- `text/plain`
- `application/rdf+xml`

视图：

- `META`
- `META_ABS`
- `META_ABS_REF`
- `FULL`
- `ENTITLED`

重定向行为：

- PDF 获取可能返回 `303`
- 也可能返回 `307`
- 实际下载 URL 会放在 HTTP `Location` 头里

工程判断：

- 这是一个“文章对象/全文获取接口”
- 不建议把它当搜索接口来接 `quick_search`

## 3. 检索方式与查询语法

### 3.1 Scopus Search 的查询模式

Scopus Search 不是 SQL，也不是自由问句语义接口，它更像“字段代码 + 布尔表达式”的高级搜索 DSL。

官方搜索提示页明确展示了大量 field code，其中和当前项目最相关的有：

- `TITLE(...)`
- `TITLE-ABS-KEY(...)`
- `TITLE-ABS-KEY-AUTH(...)`
- `DOI(...)`
- `SUBJAREA(...)`
- `PUBYEAR`

官方示例包括：

```text
TITLE("neuropsychological evidence")
TITLE-ABS-KEY("heart attack")
TITLE-ABS-KEY(prion disease)
DOI(10.1007/s00202-004-0261-3)
SUBJAREA(CHEM)
```

因此，如果我们要给当前项目做 `quick_search`，最稳妥的首版策略是：

- 普通用户 query 统一落到 `TITLE-ABS-KEY(...)`
- 如果后续要支持意图改写，再把年份、主题、DOI 等条件编译成 Scopus 的 fielded query

推荐模板：

```text
TITLE-ABS-KEY(<normalized query>)
```

如果后续要做更稳一点的高召回，也可以把：

- 必选词转成 `AND`
- 同义词转成 `OR`
- 排除词转成 `AND NOT`

### 3.2 ScienceDirect Search 的查询模式

ScienceDirect Search 同样是参数化搜索，不是语义检索。

公开规范里能明确确认的是：

- 主查询参数是 `query`
- 支持 `date` 范围
- 支持 `sort=coverDate` 或 `sort=relevance`
- 支持 `field` 做字段裁剪
- 支持 `start` / `count` 分页

更适合把它看成：

- 一个 ScienceDirect 语料范围内的关键词搜索接口
- 而不是通用学术元数据搜索总入口

## 4. 鉴权方式

官方鉴权文档里给出的主方式如下：

- `X-ELS-APIKey: <api key>`
- 或 query parameter：`apiKey=<api key>`

除此之外，官方还支持更复杂的授权模式：

- `X-ELS-Authtoken`
- `Authorization: Bearer <token>`
- `X-ELS-Insttoken`

需要注意的点：

- 默认模式常常和机构 IP 授权有关，尤其是订阅型产品
- `authtoken` 需要先通过 Authentication API 获取
- 官方文档明确写明：`authtoken` 自签发后 `2 小时` 过期
- `Authorization: Bearer <token>` 会按用户 entitlement 执行，并覆盖 `X-ELS-Authtoken`
- `Insttoken` 应只保存在服务端，并且只通过 HTTPS 发送

对当前项目的实际建议：

- server-to-server 首版优先只做 `X-ELS-APIKey`
- 不要把 API key 作为 query 参数常态化传输，优先 header
- 如果后续发现某些字段或全文能力受 entitlement 影响，再增补 institution token / bearer token 逻辑

## 5. 分页、配额与限流

官方 `Default API Key Settings` 和 `Support` 页面里对默认配额和限流有比较明确的说明。

### 5.1 默认配额与速率

| API | 默认周配额 | 默认速率 | 备注 |
| --- | --- | --- | --- |
| Scopus Search API | `20,000 / week` | `9 req/s` | 总结果深度默认上限 `5000`；视图不同单次 `count` 上限不同 |
| Abstract Retrieval API | `10,000 / week` | `9 req/s` | 适合 top N 详情补齐 |
| ScienceDirect Search API | `20,000 / week` | `2 req/s` | 官方文档对单次最大 `count` 存在轻微不一致 |
| Article Retrieval API | `50,000 / week` | `10 req/s` | Text Mining API keys 可更高或 unlimited |

### 5.2 结果集与单次返回限制

Scopus Search：

- `STANDARD` 视图单次最多 `200`
- `COMPLETE` 视图单次最多 `25`
- `COMPONENT` 视图单次最多 `25`
- 默认可翻页深度上限常见为 `5000`

ScienceDirect Search：

- 官方设置页写的是总结果深度上限 `6000`
- 设置页写 `STANDARD view / Max 200 results`
- 但 WADL 中 `count` 只列出 `10, 25, 50, 100`

这部分建议你在真实 key 到手后做一轮非常简单的 smoke test，再决定 connector 里把 `count` 固定在多少。

### 5.3 限流头

官方 FAQ 给出了常见限流响应头：

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

其中：

- `X-RateLimit-Reset` 是 Unix timestamp

工程建议：

- 在 provider runtime 或 connector 内记录这几个头
- 遇到 `429` 或配额耗尽时，把 provider 标记为降级或暂时跳过

## 6. 返回字段与 `PaperResult` 映射建议

Elsevier 官方的 search views / retrieval views 页面能确认不少对接时很关键的字段名。

常见可用字段包括：

- `dc:title`
- `dc:description`
- `prism:doi`
- `prism:coverDate`
- `authors`
- `author`
- `authkeywords`
- `subject-area` / `subject-areas`
- `openaccess`
- `openaccessFlag`
- `link ref=self`
- `link ref=scidir`
- `pii`

结合当前项目的 `PaperResult`，我建议这样映射：

| `PaperResult` 字段 | Elsevier 建议来源 |
| --- | --- |
| `source` | 固定写 `elsevier_scopus` 或未来拆成 `scopus` / `sciencedirect` |
| `source_id` | 优先 `eid` 或 `scopus_id`；若走 ScienceDirect 也可保留 `pii` |
| `title` | `dc:title` |
| `abstract` | `dc:description`；若搜索结果不稳定则用 Abstract Retrieval `META_ABS` 回填 |
| `year` | 从 `prism:coverDate` 或出版日期字段提取年份 |
| `doi` | `prism:doi` |
| `url` | 优先 `link ref=scidir`，否则 `link ref=self` 或记录页 URL |
| `pdf_url` | 只有在 Article Retrieval 或明确拿到 PDF redirect 时再填 |
| `is_oa` | `openaccess` / `openaccessFlag` |
| `authors` | `authors` / `author` 列表 |
| `raw` | 原始 payload 全量保留 |

工程上还要注意：

- `Elsevier 可访问` 不等于 `Open Access`
- `pdf_url` 不应在没有 entitlement 时强行猜测
- 如果列表接口里没有稳定摘要，宁可留空后补，也不要硬拼接错误字段

## 7. 对当前项目的接入建议

结合你现在项目里的 `BaseSourceClient`、`quick_search` 和 `PaperResult` 结构，我建议按下面的顺序接：

### 7.1 第一阶段：先接 Scopus Search

目标：

- 先把 Elsevier 接成一个“高质量元数据搜索源”

建议请求：

```text
GET https://api.elsevier.com/content/search/scopus
Headers:
  X-ELS-APIKey: <api_key>
  Accept: application/json
Params:
  query=TITLE-ABS-KEY(<normalized query>)
  view=STANDARD
  count=<limit>
  start=0
```

为什么先这样接：

- 最符合当前 `quick_search` 模式
- 成本低
- 字段足够做列表页
- 不需要一上来就处理全文 entitlement

### 7.2 第二阶段：对 top N 结果做 Abstract Retrieval 补齐

目标：

- 把摘要、作者、关键词、主题、机构等信息补全

建议请求：

```text
GET https://api.elsevier.com/content/abstract/doi/{doi}
Headers:
  X-ELS-APIKey: <api_key>
  Accept: application/json
Params:
  view=META_ABS
```

如果没有 DOI，可以回退到：

- `eid/{eid}`
- `scopus_id/{scopus_id}`
- `pii/{pii}`

### 7.3 第三阶段：把 ScienceDirect 作为独立 provider，而不是 Scopus 的替代品

如果你后面明确要“偏 Elsevier 自家内容”或“想拿 ScienceDirect 落地页 / PII / OA 标记”，建议：

- 单独做一个 `sciencedirect` provider
- 不要和 `scopus` 混成一个 endpoint

这样更清楚，也更符合 Elsevier 官方产品边界。

### 7.4 不建议的首版方案

首版不建议：

- 直接用 `Article Retrieval API` 做搜索
- 一上来就依赖 PDF 获取
- 把 `apiKey` 放在 query string 当默认做法
- 假设 Elsevier 官方支持自然语言/语义搜索

## 8. 最小可用请求示例

### 8.1 Scopus 搜索

```text
curl -H "X-ELS-APIKey: $ELSEVIER_API_KEY" ^
     -H "Accept: application/json" ^
     "https://api.elsevier.com/content/search/scopus?query=TITLE-ABS-KEY(transformer%20drug%20discovery)&view=STANDARD&count=10&start=0"
```

### 8.2 按 DOI 拉摘要详情

```text
curl -H "X-ELS-APIKey: $ELSEVIER_API_KEY" ^
     -H "Accept: application/json" ^
     "https://api.elsevier.com/content/abstract/doi/10.1016%2Fj.artmed.2024.102999?view=META_ABS"
```

### 8.3 ScienceDirect 搜索

```text
curl -H "X-ELS-APIKey: $ELSEVIER_API_KEY" ^
     -H "Accept: application/json" ^
     "https://api.elsevier.com/content/search/sciencedirect?query=large%20language%20model%20clinical&sort=relevance&count=25&start=0"
```

## 9. 最终建议

如果你现在只是想把 Elsevier 接进这个项目，而且目标是“尽快得到可用的在线论文搜索能力”，最推荐的路线是：

1. 先实现 `Scopus Search` connector
2. 查询统一编译成 `TITLE-ABS-KEY(...)`
3. 结果列表先映射 `title / year / doi / url / authors / is_oa`
4. 摘要缺失时，再对 top N 调 `Abstract Retrieval` 的 `META_ABS`
5. ScienceDirect 和 Article Retrieval 放到第二阶段

这样做的优点是：

- 跟当前项目结构最贴合
- 风险最低
- 能最快拿到一个“可搜索、可展示、可补详情”的 Elsevier 接入版本


当前申请到的Registered API keys：	52843be8eb8f852435079bbe26d52886