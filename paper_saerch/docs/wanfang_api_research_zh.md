# 万方论文检索 API 调研笔记

更新日期：2026-03-29

这份文档基于万方当前可公开访问的官方开放平台文档，以及官方文档里直接引用的接口仓库整理，目标是回答你做“论文检索 agent”时最关心的这些问题：

- 万方当前支持哪些检索方式
- 是否支持 SQL / 自然语言 / 向量或语义类检索
- 可以检索哪些字段、返回哪些字段
- 是否需要 `API Key` / `AppKey`
- 是否需要授权、是否有并发或速率要求
- 是否可以下载全文、读取摘要、读取正文
- 做 agent 时推荐怎样接入

## 结论先看

万方当前更适合做“通用论文检索 agent”的官方接口主线，不是 SQL，而是：

- 检索服务 `/query`
- 聚类服务 `/facet`
- 单条详情 `/get`
- 自然语言转检索语句 `/text2Solr`
- 全文资源上的向量/句子检索 `vectorParameter`
- 全文下载接口

关于你问的几个关键点：

- `SQL`：当前官方公开文档里没有看到对外 SQL 查询接口。主检索方式是 Solr/PQ 表达式，而不是 SQL。
- `自然语言检索`：支持。官方有 `/text2Solr`，会把自然语言问题转换成可执行的 Solr 查询语法。
- `语义/向量类检索`：支持一部分。官方在检索服务文档中给出了“全文句子检索”示例，使用 `vectorParameter`、`SentenceVec` 和全文 collection。
- `API Key / 鉴权`：需要。你需要先成为开放平台开发者，创建应用后拿到 `AppKey`、`AppSecret`、`AppCode`。
- `授权`：需要。仅有应用还不够，你的 `App` 还需要被 API 提供方按 `AppID` 授权。
- `限流/并发`：官方公开文档没有给出固定的公开 QPS 数字，但明确存在网关限流；超限时会返回 `isv.api-limiting` 或 `isv.api-app-limiting`。
- `摘要`：可以读到。检索服务中的 `Abstract` 是可检索、可取值字段。
- `正文`：检索接口本身不等于“直接返回正文文本”。官方提供的是全文下载接口，成功后返回 base64 编码的 PDF/HTML 文件。也就是说，正文通常要通过下载后再解析。

## 官方文档入口

### 1. 开放平台与网关文档

- 开发者身份说明：<https://open.wf.pub/docs/%E5%B9%B3%E5%8F%B0%E8%A7%92%E8%89%B2%E8%AE%A4%E8%AF%81>
- API 网关快速调用：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F1.%E5%BF%AB%E9%80%9F%E5%BC%80%E5%8F%91%2F%E5%BF%AB%E9%80%9F%E8%B0%83%E7%94%A8api.md>
- API 网关调用方式：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.5%20%E8%AE%A4%E8%AF%81%E6%A8%A1%E5%BC%8F%2FAPI%E7%BD%91%E5%85%B3%E7%9A%84%E8%B0%83%E7%94%A8%E6%96%B9%E5%BC%8F.md>
- API 网关两种认证方式：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.5%20%E8%AE%A4%E8%AF%81%E6%A8%A1%E5%BC%8F%2FAPI%E7%BD%91%E5%85%B3%E7%9A%84%E4%B8%A4%E7%A7%8D%E8%AE%A4%E8%AF%81%E6%96%B9%E5%BC%8F.md>
- 签名算法概述：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.6%20%E7%AD%BE%E5%90%8D%E7%AE%97%E6%B3%95%2F1.%E6%A6%82%E8%BF%B0.md>
- AppCode 简单认证：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.6%20%E7%AD%BE%E5%90%8D%E7%AE%97%E6%B3%95%2F4.%E4%BD%BF%E7%94%A8%E2%80%9C%E7%AE%80%E5%8D%95%E8%AE%A4%E8%AF%81%EF%BC%88AppCode%EF%BC%89%E2%80%9D%E6%96%B9%E5%BC%8F%E8%B0%83%E7%94%A8API.md>
- 错误码说明：<https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F3.%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%2F3.2%20%E9%94%99%E8%AF%AF%E7%A0%81%E8%AF%B4%E6%98%8E.md>

### 2. 检索与全文服务文档

- 万方检索服务：<https://gitee.com/wfrd/apidoc/raw/master/search/%E6%A3%80%E7%B4%A2%E6%8E%A5%E5%8F%A3.md>
- 万方全文服务：<https://gitee.com/wfrd/apidoc/raw/master/fulltext/%E5%85%A8%E6%96%87%E4%B8%8B%E8%BD%BD.md>

### 3. 补充产品型 API

- 万方选题 API：<https://open.wf.pub/api.html>

## 1. 当前官方公开的接口体系

从官方文档组合看，万方现在至少有两类和“论文检索 agent”相关的能力：

### 1.1 通用检索与全文服务

这是更适合你做通用论文 agent 的一条主线：

- `/query`：多条检索
- `/facet`：聚类/统计
- `/get`：单条详情
- `/text2Solr`：自然语言转可执行检索语句
- 全文 collection 上的向量句子检索
- 全文下载接口

这套能力来自“万方检索服务 + 万方全文服务 + API 网关”。

### 1.2 选题 API

这是一个产品型 API 集合，偏“文献精读 / 选题发现 / 定题评测 / 灵感池”：

- `POST /reader/papers`
- `POST /reader/scholars`
- `POST /finder/...`
- `POST /assessor/...`
- `GET /pools/...`

它也能查论文，但参数设计偏业务场景化，没有通用检索服务那么灵活。对于“自由检索、字段控制、检索式生成、全文过滤”这类 agent 场景，优先级通常低于通用检索服务。

## 2. 当前支持哪些检索方式

## 2.1 结构化检索：`/query`

官方说明里，`/query` 是核心主检索接口，使用 POST JSON。

它支持：

- 指定资源库 `collections`
- 传入 `query` 检索表达式
- 传入 `filters`
- 指定 `returned_fields`
- 排序 `sort`
- 高亮 `highlight_query`
- 翻页 `start / rows / cursor_mark`
- 最少匹配规则 `mm`
- 检索词扩展 `expand_options`
- 全文向量检索 `vectorParameter`

官方示例：

```json
{
  "collections": ["OpenPeriodical"],
  "query": "(信息 AND 图书馆) AND PublishYear:[1983 TO *]",
  "filters": [{ "field": "SourceDB", "value": "NSTL" }],
  "returned_fields": ["Title", "Id", "PublishYear"],
  "sort": {
    "sort_name": "OfflineScore"
  }
}
```

这说明它支持的不是 SQL，而是 Solr/PQ 风格表达式。

### 你可以直接认为它支持这些“检索语句能力”

- 布尔检索：`AND`、`OR`
- 范围检索：如 `PublishYear:[1983 TO *]`
- 指定字段检索：如 `标题:机械 AND 摘要:加工`
- 过滤条件：`filters`
- 排序：按 `score`、`PublishYear` 等字段
- 返回字段裁剪：`returned_fields`
- 深度翻页：`cursor_mark`

### 重要开发细节

- `rows` 默认 `20`，最大 `100`
- `start` 默认 `0`，不能超过 `5000`
- 想要超过 `5000` 的深翻页，需要改用 `cursor_mark`
- `returned_fields` 为空时，表示返回所有字段
- `returned_fields` 和 `query` 中都可以使用字段别名

## 2.2 自然语言检索：`/text2Solr`

这是官方明确公开的“自然语言 -> 可执行检索式”能力。

请求示例：

```json
{
  "question": "帮我找一下近五年自然语言检索相关的论文",
  "collection": ["OpenPeriodical"]
}
```

返回结构里会给出：

- `query`
- `sort_fields`
- `returned_fields`
- `collection`
- `facet_fields`

也就是说，`/text2Solr` 更像一个“检索式生成器”或“查询规划器”，非常适合接在 agent 的自然语言理解层前面。

## 2.3 全文句子检索 / 向量检索：`vectorParameter`

官方在 `/query` 文档里给了“全文句子检索”示例：

```json
{
  "collections": ["OpenPeriodicalFulltext"],
  "vectorParameter": {
    "vector_field": "SentenceVec",
    "vector_value": "自然语言检索"
  }
}
```

这个能力的含义是：

- 检索目标是全文 collection，而不是普通元数据 collection
- 查询可以是一整句
- 使用的是向量字段 `SentenceVec`

从开发视角看，这属于“语义/向量类检索”能力，但官方文档的表述是“全文句子检索”或“向量检索”，而不是通用聊天式问答接口。

## 2.4 聚类检索：`/facet`

官方检索服务还提供 `/facet`：

- 字段聚类
- 范围聚类
- 子聚类
- 指标计算，如 `SUM / AVG / MIN / MAX`

这很适合 agent 做筛选面板、年份分布、来源库分布、学科分布、期刊分布。

## 2.5 单条详情：`/get`

`/get` 用于按 `collection + id` 获取单条文献详情。

请求示例：

```json
{
  "collection": "OpenPeriodical",
  "id": "dbch202004054"
}
```

适合 agent 在首轮召回后，对候选结果做详情补齐。

## 2.6 是否支持 SQL

当前官方公开文档没有看到对外 SQL endpoint。

更准确的说法是：

- 官方明确公开的是 Solr/PQ 表达式式检索
- 自然语言入口是 `/text2Solr`
- 还有向量全文检索
- 没有公开文档显示“在线 SQL 查询接口”

这是基于当前官方文档入口做出的结论。

## 3. 可检索资源库与论文类型

官方检索文档中，与你做论文 agent 直接相关的 collection 包括：

- `OpenPeriodical`：期刊论文
- `OpenPeriodicalChi`：中文期刊论文
- `OpenPeriodicalEng`：英文期刊论文
- `OpenThesis`：学位论文
- `OpenConference`：会议论文

如果你要做更广义学术检索，还可以纳入：

- `OpenPatent`：专利
- `OpenStandard`：标准
- `OpenNstr`：科技报告
- `OpenCstad`：成果

如果你要做全文向量检索，官方 TOC 中列出的全文 collection 包括：

- `OpenPeriodicalFulltext`
- `OpenThesisFulltext`
- `OpenConferenceFulltext`
- `OpenPatentFulltext`
- `OpenClawFulltext`
- `OpenStandardFulltext`
- `OpenLocalchronicleFulltext`

## 4. 能检索哪些字段

万方这套检索服务的字段体系比较大。官方文档会为每种资源标注字段是否：

- `可检索`
- `可聚类`
- `可取值`
- `多值`

下面只整理对“论文 agent”最重要的一批字段。

## 4.1 跨论文类型的高频通用字段

以下字段在期刊、学位、会议这三类论文资源中都非常常见：

- `Id`
  - 唯一 ID，可检索、可取值
- `Title`
  - 别名很多，如 `标题`、`题名`、`题目`、`篇名`、`t`
- `Creator`
  - 作者
- `CreatorForSearch`
  - 作者检索专用字段，别名如 `author`、`authors`、`作者`、`著者`
- `OrganizationNorm`
  - 规范机构名
- `OrganizationForSearch`
  - 机构检索专用字段，别名如 `org`、`机构`、`作者单位`
- `ClassCodeForSearch`
  - 分类号/学科分类检索字段
- `ContentSearch`
  - 多字段内容检索，别名 `全部`
- `Keywords`
  - 关键词
- `KeywordForSearch`
  - 关键词检索专用字段，别名如 `关键词`、`k`、`Keyword`
- `Abstract`
  - 摘要，别名如 `摘要`、`b`、`abstracts`
- `PublishDate`
  - 出版时间
- `PublishYear`
  - 出版年
- `SourceDB`
  - 来源数据库
- `SingleSourceDB`
  - 单值来源数据库，适合聚类
- `Language`
  - 语种
- `HasFulltext`
  - 是否有全文
- `ServiceMode`
  - 全文服务模式
- `FulltextPath`
  - 全文路径，能取值但不是检索字段
- `DOI`
  - DOI
- `CitedCount`
  - 被引次数
- `DownloadCount`
  - 下载次数
- `MetadataViewCount`
  - 文摘阅读次数

## 4.2 期刊论文 `OpenPeriodical` 的重点字段

除了上面的通用字段，期刊论文还特别适合用这些字段：

- `PeriodicalTitleForSearch`
  - 刊名检索字段，别名如 `刊名`、`source`、`出处`、`期刊名称`
- `PeriodicalTitle`
  - 刊名显示字段
- `PeriodicalId`
  - 期刊 ID
- `Fund`
  - 基金
- `IsOA`
  - 是否 OA 论文
- `Issue`
  - 期
- `Volum`
  - 卷
- `Page`
  - 页码
- `PageNo`
  - 页数

如果你的 agent 需要“作者 + 刊名 + 年份 + 基金 + 是否可全文”的精确筛选，期刊库字段是够用的。

## 4.3 学位论文 `OpenThesis` 的重点字段

学位论文在 agent 中也很好用，特别是做“高校/导师/专业”检索时：

- `Degree`
  - 授予学位
- `Major`
  - 学科专业
- `MajorCode`
  - 专业代码
- `Tutor`
  - 导师
- `OriginalOrganization`
  - 授予单位
- `Region`
  - 学校所在地
- `HasCatolog`
  - 是否有目录

## 4.4 会议论文 `OpenConference` 的重点字段

会议论文字段相对更偏“会议信息”：

- `MeetingTitle`
  - 会议名称
- `MeetingTitleForFacet`
  - 会议名称聚类
- `MeetingId`
  - 会议 ID
- `MeetingArea`
  - 举办地
- `MeetingDate`
  - 会议时间
- `MeetingYear`
  - 会议年份
- `Sponsor`
  - 主办单位
- `MeetingCorpus`
  - 会议文集
- `MeetingLevel`
  - 会议级别

## 4.5 字段别名能力

这是万方检索服务一个很实用的点。

官方文档明确写到：

- `returned_fields` 可以使用字段别名
- `query` 中也可以使用别名

例如：

- `标题` / `题目` / `ttl` 都可映射到 `Title`
- `作者` / `author` / `authors` 可映射到 `CreatorForSearch`
- `关键词` / `k` / `Keyword` 可映射到 `KeywordForSearch`
- `摘要` / `b` / `abstracts` 可映射到 `Abstract`
- `刊名` / `source` / `出处` 可映射到 `PeriodicalTitleForSearch`

这对 agent 很友好，因为你可以把自然语言槽位映射到“人类可读字段名”，不必强依赖底层内部字段英文名。

## 5. 摘要、正文、全文能力分别是什么

## 5.1 摘要

摘要能力是明确有的：

- `Abstract` 字段在期刊、学位、会议资源里都是可检索字段
- 同时它也是可取值字段

这意味着：

- 你可以用摘要参与检索
- 也可以把摘要返回给 agent 做 rerank、摘要压缩或回答引用

## 5.2 正文文本

官方公开的检索文档没有把“完整正文文本”作为普通元数据字段公开给你直接返回。

更准确地说：

- 普通检索结果主要返回题录元数据、摘要、全文标识、全文路径等
- 全文层能力更多体现在
  - 全文 collection 的向量检索
  - 全文下载接口

所以如果你想让 agent 真正“读正文”，常见路径会是：

1. 先检索元数据
2. 判断是否有全文
3. 调用全文下载接口
4. 对 PDF 或 HTML 做解析

## 5.3 是否有全文的判断方法

官方文档直接给出了判断规则：

### 期刊 / 学位 / 会议

```text
ServiceMode:1 AND HasFulltext:true
```

### 专利

```text
CountryOrganization:CN AND SourceDB:WF
```

### 标准

```text
HasFulltext:true
```

这对 agent 很重要，因为你可以在召回阶段就把“可全文获取”作为硬过滤条件。

## 6. 全文下载接口怎么工作

官方全文下载文档给出的参数非常少，但信息很关键。

## 6.1 请求参数

- `docId`
  - 文档 id，必填
- `timestamp`
  - Unix 时间戳，必填
  - 5 分钟内有效

## 6.2 `docId` 格式与返回文件类型

- 期刊：`Periodical_文章id`，返回 `PDF`
- 学位：`Thesis_文章id`，返回 `PDF`
- 会议：`Conference_文章id`，返回 `PDF`
- 专利：`Patent_文章id`，返回 `PDF`
- 标准：`Standard_文章id`，返回 `PDF`
- 法规：`Claw_文章id`，返回 `HTML`
- 地方志：`LocalChronicleItem_条目id`，返回 `PDF`

补充说明：

- 标准全文不包括质检出版社标准

## 6.3 正确输出

官方文档写的是：

- 正确返回时，接收字符串后做 base64 解码
- 再按资源类型输出对应文件格式

开发上可以直接理解为：

- 返回的不是 JSON 摘要
- 而是文件内容的 base64 编码

## 6.4 失败条件与下载条件

官方列出的错误包括：

- `parameterEmpty`
- `docIdFormatError`
- `frequentAccess`
- `paperNotFound`
- `fulltextNotFound`
- `userExpired`
- `moneyNotEnough`
- `downloadError`

这里面最值得注意的是：

- `userExpired`
  - 机构交易账号过期
- `moneyNotEnough`
  - 机构交易账号余额不足

再结合官方声明：

- “受账号资源访问权限限制，接口支持的文献类型范围与实际调用的范围不同；请先与商务确定资源访问范围”

可以明确得出：

- 全文下载不是“只要有接口就一定能下”
- 是否可下、能下哪些库、是否需要付费或机构余额，和你的商务权限、机构账号状态直接相关

## 6.5 agent 能否读正文

可以，但前提是：

- 该条文献有全文
- 你的账号/机构对该资源有访问权限
- 下载接口调用成功

成功后：

- PDF 需要做文本提取
- HTML 可以相对更直接地提正文

## 7. 是否需要 API Key、AppKey、授权

## 7.1 需要先成为开发者

官方流程是：

1. 登录万方开放平台
2. 提交开发者审核
3. 审核通过后才能正常使用开放平台

## 7.2 需要创建应用

创建应用后，你会拿到：

- `AppKey`
- `AppSecret`
- `AppCode`

官方文档明确写到，这三项是 API 调用的基础身份信息。

## 7.3 需要授权

仅创建应用还不够。

官方文档明确写到：

- 你的 `App` 需要获得 API 的授权才能调用该 API
- 当前授权方式通常是 API 提供方根据你的 `AppID` 主动授权

也就是说，开发流程一般是：

1. 申请开发者
2. 创建应用
3. 把 `AppID` 发给万方/API 提供方
4. 对方给你的应用授权
5. 你才能正式调用

## 7.4 头部鉴权怎么传

对于高安全 API，官方网关文档给出的主流方式是：

- `X-Ca-AppKey`
- `X-Ca-Signature`

如果该 API 允许 AppCode 简单认证，则还可能支持：

- `Authorization: APPCODE <AppCode>`

或者：

- Query 参数 `appCode=<AppCode>`

需要注意：

- 不是所有 API 都支持 AppCode
- 是否支持，要看该 API 在授权详情页中的配置

## 7.5 关于“检索服务”和“全文服务”鉴权的说明

检索服务和全文服务的 raw 文档本身主要讲请求体和字段，并没有单独重写完整网关鉴权头。

但官方 API 网关文档明确要求：

- 调用开放平台 API 前要创建应用
- 通过 `AppKey / AppSecret / AppCode` 完成鉴权
- 并由 API 提供方授予权限

所以对于“检索服务”“全文服务”是否需要 `api key` 这个问题，结论是：

- 需要
- 更准确地说，是需要万方开放平台的 `AppKey / AppSecret` 体系，而不是随手匿名访问

这是基于官方网关文档与服务文档组合后的结论。

## 8. 并发、速率、分页限制

## 8.1 文档中明确写出的分页限制

检索服务 `/query` 文档明确写出：

- `rows` 默认 `20`
- `rows` 最大 `100`
- `start` 默认 `0`
- `start` 不能超过 `5000`
- 更深翻页用 `cursor_mark`

## 8.2 文档中明确写出的限流信息

官方公开文档没有给出固定的“每秒多少次”“每分钟多少次”这类公开 QPS 表。

但官方确实明确写了两类信息：

- API 网关提供“限流”功能
- 错误码中存在：
  - `isv.api-limiting`
  - `isv.api-app-limiting`

并建议：

- “降低请求并发量”

所以更稳妥的开发结论是：

- 万方存在服务端限流
- 但公开文档没有固定写死一个适用于所有客户的统一 QPS
- 实际限制很可能和 API 配置、授权范围、商务套餐或应用级别有关

## 8.3 实际接入时建议

- 默认串行或低并发起步
- 对 `40005` 系列错误做退避重试
- 为 `query/get/facet/fulltext` 设独立限流器
- 深翻页不要靠不断放大 `start`
- 批量拉取优先走 `cursor_mark`

## 9. 万方选题 API 与通用检索服务的关系

如果你只是想快速得到“论文推荐 / 选题辅助”，`万方选题 API` 也能用。

它的特点是：

- 接口更产品化
- 参数更少
- 业务语义更固定

例如：

- `POST /reader/papers`
  - 输入 `keyword + page + type`
- `POST /assessor/novelty/data`
  - 输入 `title + abstract + keyword`
- `POST /finder/...`
  - 输入 `KEYWORD / CODE + param`

而且它的返回结果里也有：

- `title`
- `keywords`
- `abstracts`
- `hasFulltext`
- `creators`
- `unitNames`
- `sourceDbs`
- `periodicalTitle`
- `citedCount`
- `downloadCount`

但如果你的目标是：

- 做通用搜索框
- 支持复杂字段检索
- 自己生成检索式
- 做 facet 筛选
- 控制返回字段
- 结合全文下载

那通用检索服务通常更合适。

## 10. 适合论文 agent 的推荐接法

如果我是按 agent 方式落地，我会优先这么接：

### 10.1 第一层：自然语言转检索规划

优先尝试：

- `/text2Solr`

用途：

- 把用户问题转成 `query`
- 自动推断 `collection`
- 自动建议 `sort`
- 自动给出可能的 `facet_fields`

### 10.2 第二层：正式检索

使用：

- `/query`

建议组合：

- `collections`: `OpenPeriodical`、`OpenThesis`、`OpenConference`
- `returned_fields`: 只取你第一屏需要的字段
- `filters`: 例如全文可得、来源库、年份、语种
- `sort`: 相关度 + 年份

### 10.3 第三层：详情补齐

使用：

- `/get`

用途：

- 对 Top-K 结果补充更多字段，避免首屏拉太重

### 10.4 第四层：全文能力

如果用户明确要“读正文”：

1. 先过滤 `ServiceMode:1 AND HasFulltext:true`
2. 再调用全文下载接口
3. PDF/HTML 解析后送给后续阅读链路

### 10.5 一个很实用的检索策略

- 用户原始问题 -> `/text2Solr`
- 生成结构化检索式 -> `/query`
- 召回结果后按 `CitedCount / DownloadCount / PublishYear / HasFulltext` 重排
- 对前几条做 `/get`
- 需要正文时再下载全文

## 11. 最终判断

如果你的目标是做“万方论文检索 agent”，当前官方能力里最值得优先接的是：

- 万方检索服务
- 万方全文下载服务
- API 网关鉴权/授权体系

关于你最初问题的简版答案：

- 支持 `Solr/PQ` 检索，不是 SQL
- 支持自然语言入口：`/text2Solr`
- 支持全文句子/向量检索：`vectorParameter`
- 支持字段级检索、过滤、聚类、详情拉取
- 支持读取摘要
- 不直接把原始正文当普通字段返回，正文主要走全文下载
- 需要 `AppKey/AppSecret/AppCode`
- 需要 API 提供方授权
- 有限流，但公开文档没有统一 QPS 数字
- 全文下载受权限、机构账号状态和商务范围约束

## 参考来源

- 万方开放平台：开发者角色认证  
  <https://open.wf.pub/docs/%E5%B9%B3%E5%8F%B0%E8%A7%92%E8%89%B2%E8%AE%A4%E8%AF%81>
- 万方开放平台：API 网关快速调用  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F1.%E5%BF%AB%E9%80%9F%E5%BC%80%E5%8F%91%2F%E5%BF%AB%E9%80%9F%E8%B0%83%E7%94%A8api.md>
- 万方开放平台：API 网关调用方式  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.5%20%E8%AE%A4%E8%AF%81%E6%A8%A1%E5%BC%8F%2FAPI%E7%BD%91%E5%85%B3%E7%9A%84%E8%B0%83%E7%94%A8%E6%96%B9%E5%BC%8F.md>
- 万方开放平台：API 网关两种认证方式  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.5%20%E8%AE%A4%E8%AF%81%E6%A8%A1%E5%BC%8F%2FAPI%E7%BD%91%E5%85%B3%E7%9A%84%E4%B8%A4%E7%A7%8D%E8%AE%A4%E8%AF%81%E6%96%B9%E5%BC%8F.md>
- 万方开放平台：签名算法概述  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.6%20%E7%AD%BE%E5%90%8D%E7%AE%97%E6%B3%95%2F1.%E6%A6%82%E8%BF%B0.md>
- 万方开放平台：AppCode 简单认证  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F2.%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97%2F2.6%20%E7%AD%BE%E5%90%8D%E7%AE%97%E6%B3%95%2F4.%E4%BD%BF%E7%94%A8%E2%80%9C%E7%AE%80%E5%8D%95%E8%AE%A4%E8%AF%81%EF%BC%88AppCode%EF%BC%89%E2%80%9D%E6%96%B9%E5%BC%8F%E8%B0%83%E7%94%A8API.md>
- 万方开放平台：错误码说明  
  <https://open.wf.pub/docs/API%E7%BD%91%E5%85%B3?path=API%E7%BD%91%E5%85%B3%2Fdocs%2F3.%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%2F3.2%20%E9%94%99%E8%AF%AF%E7%A0%81%E8%AF%B4%E6%98%8E.md>
- 万方检索服务官方文档  
  <https://gitee.com/wfrd/apidoc/raw/master/search/%E6%A3%80%E7%B4%A2%E6%8E%A5%E5%8F%A3.md>
- 万方全文下载官方文档  
  <https://gitee.com/wfrd/apidoc/raw/master/fulltext/%E5%85%A8%E6%96%87%E4%B8%8B%E8%BD%BD.md>
- 万方选题 API 官方页面  
  <https://open.wf.pub/api.html>
