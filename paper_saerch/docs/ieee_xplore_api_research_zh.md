# IEEE Xplore API 调研笔记

更新日期：2026-03-28

这份文档基于 IEEE Xplore 当前公开的官方开发文档整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- 现在有哪些官方 API 可以用
- 支持哪些检索方式
- 是否支持 SQL / 自然语言 / 语义检索
- 能按哪些字段检索、过滤、排序
- 返回哪些字段
- 是否需要 API Key
- 速率限制和并发限制怎么理解
- 做 agent 时有哪些实现与合规注意点

## 结论先看

IEEE Xplore 当前公开的主接口是 REST API，不提供公开的 SQL 查询接口。

官方文档明确支持的检索能力主要是：

- 元数据检索：`/api/v1/search/articles`
- DOI 批量精确查询：`/api/v1/articles/doi/{DOI_Values}`
- 基于 `article_number` 的全文获取：`/api/v1/search/document/{id}/fulltext`
- 简单关键词检索
- Boolean 检索：`AND` / `OR` / `NOT`
- 字段检索：按标题、作者、摘要、机构、关键词、期刊/会议名、ISSN、ISBN、年份等字段查询
- 过滤、分页、排序、Facet 精炼
- 按插入日期做增量同步

关于你特别关心的 “SQL / NLP / 自然语言”：

- `SQL`：官方公开文档没有提供 SQL endpoint，也没有托管 SQL 查询服务。
- `自然语言/NLP 检索`：官方文档没有把 IEEE Xplore API 描述为自然语言问句检索或语义检索接口。
- `语义检索`：当前公开文档只明确写了 simple search 和 Boolean search，没有公开说明 embedding / semantic / RAG 风格检索能力。

上面后两条是基于当前官方文档范围做出的判断：截至 2026-03-28，我没有在 IEEE Xplore 官方公开 API 文档里看到“自然语言问句检索”或“语义检索”接口说明。

## 1. 当前公开可用的 API

官方 “Currently Available APIs” 页面列出了 4 类能力：

| API | 官方说明 | 主要用途 |
| --- | --- | --- |
| Metadata Search API | 检索并返回 600 多万篇 IEEE Xplore 文献的 metadata 和 abstract | 论文检索、结果列表、元数据同步 |
| IEEE Open Access API | 获取 Open Access 文献全文，也可返回可收费全文 | 已知文献后取全文 |
| IEEE Full-Text Access API | 获取收费全文 | 商业/订阅全文接入 |
| DOI API | 一次最多查询 25 个 DOI 并返回 metadata + abstract | DOI 精确补数、批量补齐 |

公开文档里能直接看到的 endpoint 主要有：

| 能力 | Endpoint | 说明 |
| --- | --- | --- |
| Metadata 搜索 | `GET https://ieeexploreapi.ieee.org/api/v1/search/articles` | 按查询参数检索论文元数据 |
| DOI 查询 | `GET https://ieeexploreapi.ieee.org/api/v1/articles/doi/{DOI_Values}` | 支持单个 DOI 或逗号分隔 DOI 列表，最多 25 个 |
| Open Access / Fulltext | `GET https://ieeexploreapi.ieee.org/api/v1/search/document/{id}/fulltext` | 通过 `article_number` / id 获取全文 |

补充说明：

- IEEE 首页还写了 “Full-text Article Access is now available via the API. Please contact your sales representative for details.”，说明收费全文能力存在，但具体商务开通细节不在公开文档里。
- Metadata API 和 DOI API 是你做检索 agent 时最核心的两个接口。

## 2. 查询基本规则

官方 Query Basics 页面给出的基本形式是：

```text
https://ieeexploreapi.ieee.org/api/v1/search/articles?parameter&apikey=
```

已公开的规则包括：

- 每个请求都必须带 `apikey`
- 参数值需要 URL encode
- 参数顺序无关
- 默认返回 `JSON`
- 也支持 `XML`
- 文档里还提到 JSON 可以追加 `callback=${somevalue}`，这是偏旧式 JSONP 用法，实际是否仍推荐生产使用，官方没有进一步说明
- 所有全文获取都需要 `article_number`

## 3. 支持哪些“检索方式”

### 3.1 简单关键词检索

核心参数：

- `querytext`
- `meta_data`

官方描述：

- `querytext`：对“所有配置好的 metadata 字段 + abstract text”做 free-text search，并支持复杂查询与 Boolean 运算
- `meta_data`：对“所有配置好的 metadata 字段 + abstract”做 free-text search，并支持复杂查询与 Boolean 运算

注意：

- `Search Parameters` 页面写的是 `querytext` 搜 metadata + abstract text
- `Interactive Documentation` 页面写的是 `querytext` 搜 metadata fields, abstract and document text

这两页存在轻微表述不一致。更稳妥的工程理解是：

- `metadata + abstract` 是官方文档一致能确认的能力
- `document text` 虽然在交互文档中出现，但最好在你拿到 key 后做一次真实联调再决定是否把它当作“已保证能力”

### 3.2 Boolean 检索

官方明确支持 3 个 Boolean 运算符：

- `AND`
- `OR`
- `NOT`

官方示例：

```text
querytext=(rfid AND "internet of things")
querytext=(rfid OR "internet of things")
querytext=(rfid NOT "internet of things")
```

因此，如果你要做 agent 的高级查询改写，可以比较放心地把用户问题转成：

- 关键词组合
- 短语检索
- 带括号的布尔表达式

### 3.3 字段化检索

官方没有公开 SQL，也没有公开自然语言问句 DSL；它主要是“参数化字段检索 + free-text/Boolean”模式。

可直接用于检索的核心参数如下：

| 参数 | 作用 |
| --- | --- |
| `abstract` | 按摘要文本检索 |
| `affiliation` | 按机构/单位名称检索 |
| `article_number` | 按 IEEE 文献唯一编号精确查 |
| `article_title` | 按文章标题检索 |
| `author` | 按作者名检索 |
| `doi` | 按 DOI 精确查；出现时基本会忽略其他参数 |
| `index_terms` | 按综合关键词检索，覆盖 Author Keywords、IEEE Terms、Mesh Terms |
| `isbn` | 按 ISBN |
| `issn` | 按 ISSN |
| `is_number` | 按期号内部标识 |
| `meta_data` | 所有配置好的元数据字段 + abstract 的 free-text |
| `publication_id` | 按 publication id |
| `publication_title` | 按刊名/会议名/标准名 |
| `publication_year` | 按出版年份 |
| `querytext` | 所有配置好的元数据字段 + abstract 的 free-text |
| `thesaurus_terms` | 按 IEEE controlled vocabulary 关键词检索 |
| `start_date` | 按插入日期起始值做增量同步 |
| `end_date` | 按插入日期结束值做增量同步 |

### 3.4 Facet / 精炼检索

官方还支持一些“精炼维度”参数：

| 参数 | 作用 |
| --- | --- |
| `facet` | 指定 facet 维度 |
| `d-au` | 作者 facet |
| `d-publisher` | 出版商 facet |
| `d-pubtype` | 内容类型 facet |
| `d-year` | 年份 facet |

这类参数更像“结果集精炼”和“二次导航”能力，而不是第一层全文检索能力。

### 3.5 DOI / Article Number 精确检索

这两类是做 agent 时很重要的“精确补数”路径：

- `doi`
- `article_number`
- DOI 独立 endpoint：`/api/v1/articles/doi/{DOI_Values}`

文档明确说明：

- `article_number` 只能单独使用；如果和其他参数一起传，其他参数会被忽略
- `doi` 出现时，其他参数会被忽略；但如果同时有 `article_number`，则 `article_number` 仍优先
- DOI endpoint 最多一次 25 个 DOI

### 3.6 过滤检索

官方单独给出了 Filtering Parameters：

| 参数 | 作用 |
| --- | --- |
| `content_type` | 限制内容类型 |
| `start_year` | 起始年份 |
| `end_year` | 结束年份 |
| `open_access` | `True` / `False` |
| `publication_number` | 限制到具体 publication |
| `publisher` | 限制出版商 |

`content_type` 官方可选值：

- `Books`
- `Conferences`
- `Courses`
- `Early Access`
- `Journals`
- `Journals,Magazines`
- `Magazines`
- `Standards`

`publisher` 官方列出的可选值：

- `Alcatel-Lucent`
- `AGU`
- `BIAI`
- `CSEE`
- `IBM`
- `IEEE`
- `IET`
- `MITP`
- `Morgan & Claypool`
- `SMPTE`
- `TUP`
- `VDE`

### 3.7 分页与排序

官方给出的排序/分页参数：

| 参数 | 说明 |
| --- | --- |
| `max_records` | 返回条数，默认 `25`，最大 `200` |
| `start_record` | 结果起始序号，默认 `1` |
| `sort_field` | 可选 `article_number` / `article_title` / `publication_title` |
| `sort_order` | `asc` 或 `desc` |

这意味着：

- 单次最多只能取 200 条
- 大结果集必须靠 `start_record` 逐页遍历
- 如果你要做 agent 的批量召回，必须自己做分页器

## 4. 是否支持 SQL / 自然语言 / 语义检索

### 4.1 SQL

公开文档没有 SQL 查询接口，也没有类 SQL 的查询语法说明。

更准确地说，IEEE Xplore API 的公开模式是：

- REST endpoint
- query parameter 驱动的字段查询
- free-text + Boolean
- 过滤、排序、分页

所以如果你的 agent 上层想支持“SQL 风格查询”，通常需要你自己做一层查询规划器，把：

- 用户输入
- 内部 DSL
- SQL-like 表达

转换成 IEEE 的参数组合。

### 4.2 自然语言问句检索

截至当前公开文档：

- 没看到“输入一句自然语言问题，系统自动做语义检索”的官方说明
- 没看到 embedding/vector/semantic endpoint
- 没看到专门的 NLP query endpoint

因此更安全的结论是：

- 你可以让 agent 接受自然语言问题
- 但 agent 需要自己把自然语言改写成 IEEE 可接受的字段查询、关键词查询和 Boolean 查询

### 4.3 语义检索

官方公开文档没有给出语义检索接口说明。

如果后续你想做更像“问答式”的论文检索体验，推荐架构是：

1. 让 LLM 先把用户问题改写成 IEEE 的 `querytext` / 字段参数 / filters
2. 用 IEEE API 拉回候选文献
3. 在你自己的系统里做重排序、聚类、总结、RAG

## 5. 可检索字段与约束

下面是开发时最值得直接记住的字段和约束。

| 参数 | 约束 / 备注 |
| --- | --- |
| `author` | 支持通配符 `*`，但前面至少要有 3 个字符 |
| `affiliation` | 做部分匹配时，至少 3 个字符 |
| `querytext` | 最多包含 2 个 wildcard 词；每个 wildcard 词前至少 3 个字符 |
| `meta_data` | 同上 |
| `index_terms` | 同上 |
| `thesaurus_terms` | 同上 |
| `article_number` | 必须单独使用；会覆盖其他搜索参数 |
| `doi` | 出现后几乎会覆盖其他参数；`article_number` 仍优先 |
| `publication_year` | 字段格式可能因 publication 不同而不同，官方建议先在 Xplore Web 产品里确认 |
| `start_date` / `end_date` | 格式为 `YYYYMMDD`，用于按插入日期做 delta update |

## 6. 返回哪些字段

官方说明：只返回“有值的字段”，所以不同文献的返回结构可能不同。

### 6.1 标识与访问状态

| 字段 | 说明 |
| --- | --- |
| `article_number` | IEEE 文献唯一编号 |
| `doi` | DOI |
| `accessType` | 访问状态。官方列出 `Open Access`、`Ephemera`、`Locked`、`Plagarized` |
| `rank` | IEEE 内部排序结果 |

### 6.2 标题与出版信息

| 字段 | 说明 |
| --- | --- |
| `title` | 单篇文献标题 |
| `publication_title` | 出版物标题 |
| `publication_year` | 出版年份 |
| `publication_date` | 出版日期 |
| `publication_number` | publication 的 IEEE 编号 |
| `publisher` | 出版商 |
| `content_type` | 内容类型 |
| `is_number` | 期号内部标识 |
| `issue` | 期号 |
| `volume` | 卷号 |
| `start_page` | 起始页 |
| `end_page` | 终止页 |

### 6.3 作者、机构、关键词

| 字段 | 说明 |
| --- | --- |
| `authors` | 作者列表 |
| `full_name` | 作者全名 |
| `author_order` | 作者顺序 |
| `affiliation` | 作者机构 |
| `author_terms` | 作者关键词 |
| `ieee_terms` | IEEE 词表关键词 |
| `index_terms` | Author Keywords + IEEE Terms 的合并字段 |
| `author_url` | 作者详情页链接 |

### 6.4 摘要、链接与全文入口

| 字段 | 说明 |
| --- | --- |
| `abstract` | 摘要 |
| `abstract_url` | 摘要页 URL |
| `html_url` | HTML 全文 URL |
| `pdf_url` | PDF URL |

注意：

- 官方明确说全文请求需要另起一个请求，并带 `article_number`
- 从检索 agent 的角度，metadata 检索和全文拉取应拆成两个阶段

### 6.5 会议与标准相关字段

| 字段 | 说明 |
| --- | --- |
| `conference_dates` | 会议日期 |
| `conference_location` | 会议地点 |
| `standard_number` | 标准编号 |
| `standard_status` | 标准状态 |

### 6.6 统计、同步与 Facet

| 字段 | 说明 |
| --- | --- |
| `citing_paper_count` | 被论文引用次数 |
| `citing_patent_count` | 被专利引用次数 |
| `insert_date` | 最后更新时间，格式 `yyyymmdd` |
| `facet` | facet 维度 |
| `d-au` | 作者 facet |
| `d-publisher` | 出版商 facet |
| `d-pubtype` | 内容类型 facet |
| `d-year` | 年份 facet |
| `start-record` | 当前结果起始位置信息 |
| `totalfound` | 符合条件的总结果数 |
| `totalsearched` | 被搜索的总记录数 |

## 7. API Key、限流、并发与条款限制

### 7.1 是否需要 API Key

需要，而且是强制的。

官方文档明确说：

- 你必须先注册开发者账号
- 再提交 IEEE Xplore API 注册申请
- IEEE 审核通过后才会发 key
- 每个请求都必须带 `apikey`

公开文档里还能确认到：

- `Only one API key per application`
- `No individual user may have more than one API Key per API`
- key 必须保密，不可共享给第三方

### 7.2 审核与发放

Getting Started 页面写明：

- API key 在美国东部时间周一到周五 `8am-5pm` 业务时间发放
- 你需要说明应用用途，并提供组织网站 URL
- 某些用途审批可能更久

### 7.3 速率限制

这是一个很关键的点。

官方 Terms of Use 没有公开写死具体数字，但明确写了：

- 你的使用量受 “calls per minute, hour, day, etc.” 限制
- 这些 Rate Limits 会在注册流程中展示
- IEEE 可以随时调整限制
- 不允许绕过这些技术限制

所以当前能确认的是：

- 官方存在分钟级、小时级、天级限流
- 公开网页没有给出统一固定值
- 真实阈值需要等你账号申请通过后，在注册/账户界面确认

### 7.4 并发要求

我没有在当前官方公开文档里找到“允许多少并发连接 / 并发请求”的明确数字。

因此更稳妥的开发结论是：

- 不要假设有很高并发额度
- 先按保守并发做客户端限流
- 对 `429`、`5xx`、超时做指数退避重试
- 在拿到正式 key 后，用小流量压测验证你的账户实际限制

这条属于基于官方文档“未公开并发值”做出的工程建议，不是 IEEE 公开写出的固定规则。

### 7.5 使用条款限制

这部分很重要，尤其如果你未来想把 agent 产品化。

官方 Terms of Use 明确写到：

- 公开许可主要面向 `non-commercial educational, research, or scientific activities`
- 内容只能响应单个查询展示，不能以 bulk format 展示
- 不得用 robot / spider / retrieval application 去抓取或索引内容
- 不得以可被机器或人大规模 harvest 的形式分发内容
- TDM 仅允许非商业研究用途，并要求有效 IEEE Xplore 机构订阅

这意味着：

- 如果你要做的是内部研究型检索 agent，通常更贴近公开文档允许范围
- 如果你要做商业化 SaaS、全文批量留存、批量重分发、开放大规模索引，最好先和 IEEE 商务/法务确认

## 8. 做论文检索 agent 的接入建议

### 8.1 推荐的能力拆分

建议把 IEEE 接口分成 3 层：

1. `query planner`
   把用户自然语言问题改写成 `querytext`、字段参数、filters、sort/paging
2. `retrieval`
   调 Metadata API / DOI API 拉元数据
3. `enrichment`
   按 `article_number` 再决定是否拉全文、摘要链接、PDF 链接等

### 8.2 推荐优先支持的查询能力

第一版 agent 建议先支持：

- `querytext`
- `article_title`
- `author`
- `affiliation`
- `publication_title`
- `publication_year`
- `index_terms`
- `thesaurus_terms`
- `content_type`
- `start_year` / `end_year`
- `open_access`
- `doi`

这套组合已经足够覆盖大多数论文检索场景：

- 按主题找论文
- 按作者找论文
- 按机构找论文
- 按期刊/会议找论文
- 按年份范围筛选
- 按开放获取筛选
- 按 DOI 精确补齐

### 8.3 推荐的系统实现细节

- 用环境变量保存 `IEEE_XPLORE_API_KEY`
- 在客户端内置速率限制器，不要等 429 才补救
- 统一做 URL encode
- 将 `article_number` 检索和普通多条件检索分开建模
- 用 `start_record + max_records` 实现分页遍历
- 用 `start_date + end_date` 做定期增量同步
- 对返回字段做“可选字段”处理，不要假设每条记录字段完整
- 把 `accessType` 作为全文可用性判定的重要信号

### 8.4 一个比较稳妥的产品策略

如果你要做“自然语言检索 agent”，比较稳妥的做法不是直接期待 IEEE 支持 NLP query，而是：

1. 用户输入自然语言问题
2. LLM 将问题解析为：
   `topic keywords`、`boolean expression`、`author`、`venue`、`year range`、`open_access` 等结构化意图
3. 系统把结构化意图映射为 IEEE 参数
4. 拉回结果后再做：
   rerank、摘要总结、去重、聚类、对比阅读

这样既兼容 IEEE 的公开 API 约束，也更容易把 IEEE 和 OpenAlex、Crossref、Semantic Scholar 等源拼起来。

## 9. 示例请求

### 9.1 关键词 + Boolean 检索

```text
GET https://ieeexploreapi.ieee.org/api/v1/search/articles?querytext=(rfid%20AND%20%22internet%20of%20things%22)&max_records=25&apikey=YOUR_KEY
```

### 9.2 按作者 + 年份范围

```text
GET https://ieeexploreapi.ieee.org/api/v1/search/articles?author=Geoffrey%20Hinton&start_year=2020&end_year=2025&apikey=YOUR_KEY
```

### 9.3 按 DOI 批量补齐

```text
GET https://ieeexploreapi.ieee.org/api/v1/articles/doi/10.1109%2F5.771073,10.1109%2FCVPR.2016.90?apikey=YOUR_KEY
```

### 9.4 按 article_number 获取全文

```text
GET https://ieeexploreapi.ieee.org/api/v1/search/document/6762843/fulltext?apikey=YOUR_KEY&format=json
```

## 10. 当前文档里值得注意的“坑”

### 10.1 `querytext` 的覆盖范围有轻微表述差异

- Search Parameters 页：metadata fields + abstract text
- Interactive Documentation 页：metadata fields + abstract + document text

建议：

- 先按 metadata + abstract 建模
- 拿到 key 后做实验验证 document text 是否真的生效

### 10.2 `publication_id` 与 `publication_number`

公开文档里：

- 搜索参数页用的是 `publication_id`
- 过滤参数页和返回字段页里更常见的是 `publication_number`

建议：

- 实装时把这两个概念分开
- 联调时重点验证它们在实际接口里的行为是否一致

### 10.3 公开文档没有给出固定限流数字

所以不要在代码里写死“官方一定允许 X QPS”这类假设。

## 11. 对你这个项目的直接建议

如果你现在就在做 IEEE 论文检索 agent，我建议你第一版能力这样设计：

- 检索层：先只做 Metadata API
- 精确补数层：加 DOI API
- 全文层：只在 `accessType` 允许时，再按 `article_number` 单独拉
- 查询规划层：把自然语言转成 IEEE 参数，不要直接把自然语言原句裸传
- 合规层：预留 rate limit、usage policy、全文授权开关

如果后面你愿意，我下一步可以直接继续帮你做两件事里的任意一个：

- 写一个 IEEE Xplore Python client 封装
- 继续把“自然语言问题 -> IEEE 查询参数”的 planner 设计出来

## 官方来源

- Currently Available APIs: <https://developer.ieee.org/docs>
- API Query Basics: <https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API>
- Search Parameters: <https://developer.ieee.org/docs/read/Metadata_API_details>
- Filtering Parameters: <https://developer.ieee.org/docs/read/metadata_api_details/Filtering_Parameters>
- Sorting and Paging Parameters: <https://developer.ieee.org/docs/read/metadata_api_details/Sorting_and_Paging_Parameters>
- Boolean Search Operators: <https://developer.ieee.org/docs/read/metadata_api_details/Leveraging_Boolean_Logic>
- Data Fields Returned: <https://developer.ieee.org/docs/read/Metadata_API_responses>
- Interactive Documentation: <https://developer.ieee.org/io-docs>
- Getting Started: <https://developer.ieee.org/getting_started>
- Currently Supported API Use Cases: <https://developer.ieee.org/Allowed_API_Uses>
- Terms of Use: <https://developer.ieee.org/apps/tos>
