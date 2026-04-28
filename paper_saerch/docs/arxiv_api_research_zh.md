# arXiv API 调研笔记

更新日期：2026-03-28

这份文档基于 arXiv 当前官方文档整理，目标是回答你在做“论文检索 agent”时最关心的几个问题：

- arXiv 当前官方检索接口是什么
- 支持哪些检索方式和查询语法
- 能检索哪些字段，能返回哪些字段
- 是否支持 SQL / 自然语言 / 语义检索
- 是否需要 API Key
- 分页、排序、限流、并发要求分别是什么
- 做 agent 时有哪些实现建议和坑点

## 结论先看

截至 2026-03-28，arXiv 官方公开的论文检索接口主要是 `legacy arXiv API`，入口是：

```text
http://export.arxiv.org/api/query
```

它的核心特点是：

- 接口风格是基于 HTTP 的查询接口，不是 SQL
- 查询主要通过 `search_query`、`id_list`、`start`、`max_results`、`sortBy`、`sortOrder` 完成
- `search_query` 支持字段前缀检索、布尔运算、短语检索、括号分组、日期区间过滤
- 返回格式是 `Atom 1.0 XML`，不是 JSON
- 官方文档没有提供 NLP 自然语言检索或语义检索接口说明
- 官方文档没有要求使用 API Key；基于官方示例和文档表述，可以推断这个查询接口当前无需 API Key
- 速率限制非常严格：`每 3 秒最多 1 次请求`，并且`同一时间只允许单连接`

如果你的目标是做“标准论文检索 agent”，这个接口可以满足：

- 标题、作者、摘要、分类、期刊引用等字段检索
- 基于关键词和布尔表达式的候选召回
- 分页拉取结果
- 通过 arXiv ID 精准取回论文元数据

但它不适合：

- 直接做自然语言问句检索
- 直接做语义向量检索
- 高吞吐实时抓取
- 一次性大规模全量 metadata 同步

对于大规模元数据抓取，官方明确建议优先考虑 `OAI-PMH`，而不是这个搜索 API。

## 1. 官方文档入口

本次整理主要基于以下 arXiv 官方页面：

- API Access: `https://info.arxiv.org/help/api/index.html`
- API Basics: `https://info.arxiv.org/help/api/basics.html`
- API User's Manual: `https://info.arxiv.org/help/api/user-manual.html`
- Terms of Use for arXiv APIs: `https://info.arxiv.org/help/api/tou.html`

其中和开发最相关的是：

- `User's Manual`：查询参数、语法、返回字段、错误格式
- `Terms of Use`：限流、并发、使用边界

## 2. 当前支持的查询方式

### 2.1 按查询语句检索：`search_query`

这是最核心的检索方式。

示例：

```text
http://export.arxiv.org/api/query?search_query=all:electron
```

`search_query` 是一个结构化查询字符串，不是 SQL，也不是自然语言问句。

它本质上更接近：

- 字段前缀 + 关键词检索
- Lucene 风格的相关性排序
- 布尔表达式检索

### 2.2 按 arXiv ID 精准查询：`id_list`

适合：

- 已经拿到了候选论文 ID，回表获取详情
- 精确补齐 metadata

示例：

```text
http://export.arxiv.org/api/query?id_list=2401.01234,2401.01235
```

官方说明里特别提到：

- 虽然存在 `id:` 字段前缀
- 但更推荐使用 `id_list`
- 因为 `id_list` 对论文版本处理更合适

### 2.3 `search_query` + `id_list` 联合过滤

如果两个参数同时提供，则返回：

- `id_list` 中
- 同时满足 `search_query` 的论文

这可以拿来做：

- 候选集合二次过滤
- 已知论文池的规则筛选

### 2.4 分页：`start` + `max_results`

用于分批获取结果。

- `start`：起始偏移，`0` 基
- `max_results`：返回条数

示例：

```text
http://export.arxiv.org/api/query?search_query=all:electron&start=0&max_results=10
```

### 2.5 排序：`sortBy` + `sortOrder`

支持的排序字段：

- `relevance`
- `lastUpdatedDate`
- `submittedDate`

支持的排序方向：

- `ascending`
- `descending`

示例：

```text
http://export.arxiv.org/api/query?search_query=ti:"electron thermal conductivity"&sortBy=lastUpdatedDate&sortOrder=ascending
```

### 2.6 HTTP 调用方式

官方文档说明可以使用：

- HTTP `GET`
- HTTP `POST`

工程上更常见的是 `GET`，因为官方示例几乎都以 URL 查询字符串形式展示。

## 3. 支持哪些查询语法

### 3.1 字段前缀检索

官方文档给出的可检索字段前缀如下：

| 前缀 | 含义 |
| --- | --- |
| `ti` | 标题 Title |
| `au` | 作者 Author |
| `abs` | 摘要 Abstract |
| `co` | 作者评论 Comment |
| `jr` | 期刊引用 Journal Reference |
| `cat` | 学科分类 Subject Category |
| `rn` | 报告编号 Report Number |
| `id` | arXiv ID，但官方建议改用 `id_list` |
| `all` | 以上字段的综合检索 |

示例：

```text
au:del_maestro
ti:checkerboard
abs:graphene
cat:cs.LG
all:transformer
```

### 3.2 布尔检索

官方文档列出的布尔运算符有：

- `AND`
- `OR`
- `ANDNOT`

注意：

- 官方写法是 `ANDNOT`
- 不是很多搜索系统里常见的 `NOT`

示例：

```text
au:del_maestro+AND+ti:checkerboard
au:del_maestro+ANDNOT+ti:checkerboard
au:del_maestro+ANDNOT+%28ti:checkerboard+OR+ti:Pyrochlore%29
```

### 3.3 括号分组

支持使用括号控制优先级，但在 URL 中需要编码：

- `(` => `%28`
- `)` => `%29`

示例：

```text
au:del_maestro+ANDNOT+%28ti:checkerboard+OR+ti:Pyrochlore%29
```

### 3.4 短语检索

支持使用双引号检索短语，但同样需要 URL 编码：

- `"` => `%22`

示例：

```text
ti:%22quantum+criticality%22
```

### 3.5 日期区间过滤

官方文档说明，API 提供一个日期过滤字段：

- `submittedDate`

格式为：

```text
[YYYYMMDDTTTT+TO+YYYYMMDDTTTT]
```

其中：

- `TTTT` 是 GMT 时区下的 24 小时制时间，精确到分钟

示例：

```text
au:del_maestro+AND+submittedDate:[202301010600+TO+202401010600]
```

这意味着你可以做：

- 某时间窗口内的新论文召回
- 增量同步
- 按提交日期约束的检索

### 3.6 URL 编码要求

官方文档特别提醒：

- URL 里的空格要编码成 `+`
- 括号和双引号都要编码

因此在工程里最好：

- 使用标准 URL 编码库自动编码
- 不要手写字符串拼接后直接发请求

## 4. 不支持什么

这是你做 agent 时非常关键的一点。

基于官方文档，当前 arXiv API 没有提供以下能力的公开说明：

- SQL 查询接口
- 自然语言问句检索接口
- 语义向量检索接口
- JSON 原生返回
- 聚合分析接口
- Facet / aggregation 统计接口

因此可以得出下面这个工程判断：

- 如果你要做“用户输入一句自然语言问题，然后直接召回论文”，需要你自己在上层做 query rewrite
- 如果你要做语义检索，需要你自己把 arXiv 元数据接到 embedding / 向量库
- 如果你要做复杂分析型查询，需要自己建库

这里有一条需要明确标注为“推断”的结论：

- 官方文档只定义了字段化检索和布尔表达式，没有定义 NLP 问句语法，因此“自然语言检索不受官方 API 直接支持”是基于官方文档范围做出的工程推断

## 5. 能检索哪些字段

严格来说，官方文档区分了“可检索字段”和“返回字段”。

可检索字段就是前面表格中的这些：

- 标题
- 作者
- 摘要
- 评论
- 期刊引用
- 分类
- 报告编号
- ID
- 全字段综合
- 提交日期 `submittedDate`

如果你要做检索 agent，通常最有用的检索维度是：

- `ti`
- `abs`
- `au`
- `cat`
- `all`
- `submittedDate`

## 6. 会返回哪些字段

arXiv API 返回的是 `Atom feed`，结构分为两层：

- feed 级元数据
- entry 级论文元数据

### 6.1 Feed 级字段

常见字段包括：

- `<title>`：当前查询的规范化表达
- `<id>`：本次查询的唯一标识
- `<link rel="self">`：可再次获取该 feed 的链接
- `<updated>`：该 feed 的更新时间
- `<opensearch:totalResults>`：总结果数
- `<opensearch:startIndex>`：当前起始位置
- `<opensearch:itemsPerPage>`：当前页大小

其中有一个实现上很重要的点：

- 官方文档说明，搜索结果只有在新论文进入系统后才会变化
- 对于同一个查询，没有必要一天内重复请求很多次
- 官方明确建议缓存结果

### 6.2 Entry 级字段

每篇论文通常会返回这些字段：

| 字段 | 含义 |
| --- | --- |
| `<title>` | 论文标题 |
| `<id>` | 论文抽象页 URL，可从中提取 arXiv ID |
| `<published>` | 首次版本提交时间 |
| `<updated>` | 当前返回版本的提交/处理时间 |
| `<summary>` | 摘要 |
| `<author><name>` | 作者名 |
| `<author><arxiv:affiliation>` | 作者机构，可选 |
| `<category>` | 分类标签，可能多个 |
| `<link rel="alternate">` | 摘要页链接 |
| `<link title="pdf">` | PDF 链接 |
| `<link title="doi">` | DOI 跳转链接，可选 |
| `<arxiv:primary_category>` | 主分类 |
| `<arxiv:comment>` | 作者备注，可选 |
| `<arxiv:journal_ref>` | 期刊引用，可选 |
| `<arxiv:doi>` | DOI，可选 |

### 6.3 版本相关语义

这个点很容易影响排序和去重：

- `<published>` 是首个版本的时间
- `<updated>` 是当前返回版本的时间
- 如果拿到的是 `v2`、`v3` 等版本，那么 `<updated>` 会晚于 `<published>`

所以你做 agent 时要先决定：

- 你是按“论文首次出现时间”排序
- 还是按“最近版本更新时间”排序

## 7. 鉴权、API Key、账号要求

截至 2026-03-28，基于官方文档可以确认：

- `API Basics` 和 `User's Manual` 中的示例 URL 都是直接匿名访问
- 官方文档没有列出 API Key、Access Token、OAuth、注册获取凭证等步骤

因此可以做出下面这个带来源依据的工程结论：

- 对 `legacy arXiv API` 的查询接口来说，当前官方文档没有要求 API Key，实践上应视为公开匿名可访问接口

同时也要注意一个边界：

- `Terms of Use` 提到需要遵守“authorization mechanisms”
- 但在当前这套查询接口文档里，没有出现需要你显式提供密钥的机制说明

也就是说：

- “当前不需要 API Key”是基于官方文档和官方示例的合理结论
- 但未来规则可能调整，应定期复查官方文档

## 8. 速率限制与并发要求

这个部分必须严格遵守。

官方 `Terms of Use` 对 legacy APIs 的要求是：

- 所有你控制的机器整体合计，`最多每 3 秒 1 个请求`
- `同一时间只允许 1 个连接`
- 不要通过增加机器数来绕过限制

另外 `User's Manual` 还给出了一些工程层面的边界：

- 官方鼓励多次连续调用时显式加入 `3 秒延迟`
- 单次请求 `max_results` 最大不能超过 `30000`
- 单次切片大小最多 `2000`
- 如果 `max_results > 30000`，会返回 `HTTP 400`
- 官方建议把返回结果控制在较小范围
- 如果查询返回结果超过 `1000`，建议进一步收窄条件，或者分更小切片拉取

所以在实现里建议你直接把客户端限流写死为：

```text
全局串行队列 + 请求间隔 >= 3 秒
```

不要做：

- 并发抓取
- 多 worker 同时打 arXiv API
- 多机分片绕过速率限制

## 9. 分页与结果规模限制

官方分页逻辑如下：

- `start` 是 0 基偏移
- `max_results` 是本次返回条数

官方给出的重要限制：

- 总拉取窗口上限：`30000`
- 单页上限：`2000`

典型做法：

```text
start=0&max_results=100
start=100&max_results=100
start=200&max_results=100
```

如果你要稳定做 agent 检索，我更建议：

- 首轮召回用较小页，例如 `25`、`50`、`100`
- 不要默认把 `max_results` 拉到很大
- 用户真正需要更多时再翻页

## 10. 错误格式

arXiv API 的错误响应也不是 JSON，而是 Atom。

特点：

- 错误时返回一个带单个 `<entry>` 的 Atom feed
- 错误信息通常在 `<summary>` 中

官方示例覆盖的常见错误包括：

- `start` 不是整数
- `start < 0`
- `max_results` 不是整数
- `max_results < 0`
- `id_list` 中 ID 格式错误

因此在代码里不要只看 HTTP 状态码，还要：

- 解析返回体
- 检查是否是错误 entry
- 提取 `<summary>` 作为诊断信息

## 11. 对论文检索 agent 的实现建议

如果你准备把 arXiv 作为一个检索源，我建议按下面的思路设计。

### 11.1 把 arXiv 当成“规则化召回源”

适合让 arXiv 负责：

- 关键词召回
- 作者召回
- 分类召回
- 日期窗口召回
- 已知 ID 的元数据补齐

不适合直接让 arXiv 负责：

- 自然语言理解
- query expansion
- 语义重排

### 11.2 在上层做 query rewrite

用户输入：

```text
最近两年关于多模态大模型推理压缩的论文
```

更适合先在你自己的 agent 里改写成结构化查询，例如：

```text
all:"multimodal" AND all:"reasoning" AND all:compression AND submittedDate:[202401010000 TO 202603282359]
```

然后再发给 arXiv。

### 11.3 建议做自己的统一字段模型

因为 arXiv 返回是 Atom XML，建议你落一层内部标准结构，例如：

```json
{
  "source": "arxiv",
  "source_id": "2401.01234v2",
  "canonical_id": "2401.01234",
  "title": "...",
  "abstract": "...",
  "authors": ["..."],
  "affiliations": ["..."],
  "primary_category": "cs.CL",
  "categories": ["cs.CL", "cs.AI"],
  "published_at": "...",
  "updated_at": "...",
  "comment": "...",
  "journal_ref": "...",
  "doi": "...",
  "abs_url": "...",
  "pdf_url": "..."
}
```

这样后面接 OpenAlex、Semantic Scholar、Crossref 时会轻松很多。

### 11.4 限流要放在 provider 层统一做

建议你把 arXiv provider 做成：

- 单例 client
- 内部串行
- 全局 sleep / token bucket
- 带缓存

否则后面 agent 多步骤调用时，很容易不小心超限。

### 11.5 大规模抓取不要走这个搜索接口

如果你后续需求变成：

- 全量同步某学科
- 每日增量收集大量 metadata
- 批量建立本地检索库

更合适的方向是：

- `OAI-PMH`
- 官方 bulk data 方式

而不是反复扫 `search_query`

## 12. 开发时的最小可用参数组合

### 12.1 普通关键词检索

```text
http://export.arxiv.org/api/query?search_query=all:transformer&start=0&max_results=25
```

### 12.2 标题 + 摘要联合检索

```text
http://export.arxiv.org/api/query?search_query=ti:transformer+OR+abs:transformer&start=0&max_results=25
```

### 12.3 分类 + 时间窗口

```text
http://export.arxiv.org/api/query?search_query=cat:cs.CL+AND+submittedDate:[202501010000+TO+202603282359]&sortBy=submittedDate&sortOrder=descending&start=0&max_results=50
```

### 12.4 用 ID 回表

```text
http://export.arxiv.org/api/query?id_list=2401.01234,2401.05678
```

## 13. 最终回答你的几个核心问题

### 13.1 当前支持哪些检索方式？

支持：

- 结构化字段检索
- 全字段关键词检索
- 布尔检索
- 短语检索
- 括号分组
- 提交日期区间过滤
- 按 ID 精准获取
- 分页与排序

不支持官方文档明确说明的：

- SQL
- 自然语言问句检索
- 语义检索

### 13.2 能检索哪些字段？

支持检索：

- 标题 `ti`
- 作者 `au`
- 摘要 `abs`
- 评论 `co`
- 期刊引用 `jr`
- 分类 `cat`
- 报告编号 `rn`
- ID `id`
- 全字段 `all`
- 提交日期 `submittedDate`

### 13.3 会返回哪些字段？

主要返回：

- 标题
- arXiv ID / abstract URL
- 发布时间
- 更新时间
- 摘要
- 作者
- 作者机构（可选）
- 分类
- 主分类
- abstract / pdf / doi 链接
- comment
- journal_ref
- doi

### 13.4 是否需要 API Key？

按当前官方文档和官方示例看：

- 不需要 API Key

这条结论来自官方文档未要求鉴权凭证，且所有示例均为匿名访问。

### 13.5 并发速率要求是什么？

官方要求：

- 最多每 3 秒 1 次请求
- 同时只允许 1 个连接

这是必须遵守的硬限制。

## 14. 官方来源

- API Access: https://info.arxiv.org/help/api/index.html
- API Basics: https://info.arxiv.org/help/api/basics.html
- API User's Manual: https://info.arxiv.org/help/api/user-manual.html
- Terms of Use for arXiv APIs: https://info.arxiv.org/help/api/tou.html
