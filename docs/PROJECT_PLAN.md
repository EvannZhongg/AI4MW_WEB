# AI4MW 研究平台整体规划

本规划面向“电磁与器件研究”的研究级 AI 平台，满足模块化架构、提示词驱动、多模态推理、研究可追溯、部署与安全要求。当前仅有 datasheet → 知识图谱管线（`datesheet_rag`），后续迭代遵循本文规划。

## 0. 设计原则落地
- **模块化**：每个能力是独立模块，使用明确接口（REST/gRPC/消息队列）交互；禁止跨模块读取内部实现细节。
- **提示词驱动**：任务拆解、编排由提示词模板驱动；提示词独立于代码、支持继承与版本管理。
- **统一接口层**：仿真、图像、几何解析、结果解释统一为抽象接口，后端可替换具体实现。
- **多模态推理**：文本/图像/图结构/向量统一进入任务编排层。
- **可追溯**：输入提示词、检索 chunks、仿真配置、模型版本、中间推理都可存档。
- **安全与多租户**：默认公网部署，角色与项目隔离；不在日志/响应中泄露敏感配置。

## 1. 总体架构（模块清单）
**平台核心（平台级）**
- API 网关与鉴权（Auth & RBAC）
- 项目与实验管理（Project/Workspace）
- 任务编排与工作流（Prompt-Orchestrator）
- 统一追踪与审计（Trace/Provenance）

**研究能力模块（可独立服务 / Docker 预留）**
- 文档解析服务（MinerU）：datasheet → 结构化内容（端口 8002）
- 文本理解与抽取（LLM 任务）
- 图像理解（VLM）
- 结构化图谱构建（KG Builder）
- 向量化与检索（pgvector）
- 仿真统一接口（HFSS/CST/COMSOL/自研求解器适配器）
- 知识融合与标准化（厂商规范化/术语对齐）

**数据与基础设施**
- PostgreSQL（含 pgvector，图数据与向量数据统一存储，不额外引入其他数据库）
- 对象存储（原始文档、图像、仿真输出）
- 缓存与队列（Redis + Celery/RQ）
- 监控与日志（OpenTelemetry/Prometheus/ELK）

## 2. 统一接口层（抽象接口建议）
以下接口以“抽象协议”形式定义，具体实现由各模块提供：
- `IParser`: parse(document) -> structured_blocks
- `IExtractor`: extract(structured_blocks, prompt_id) -> entities/relations
- `IVLM`: analyze(image, prompt_id) -> structured_caption/annotations
- `ISimulator`: run(config, geometry, boundary, sweep) -> results
- `IKGStore`: upsert(entities, relations), query(...)
- `IVectorStore`: upsert(embedding), search(query_embedding, topk)

接口协议与数据结构集中放在 `docs/contracts/`（后续建立）。

## 3. 提示词体系（Prompt-Centric）
- `prompts/` 目录：存放 YAML/JSON/Markdown 提示词模板
- 支持继承：`base/` → `domain/` → `task/`
- 版本控制：每个提示词带版本号与变更说明
- 运行时：工作流仅引用 `prompt_id`，不内嵌提示词文本

## 4. 数据与追溯（Traceability）
**追溯记录必须包含：**
- 输入提示词 ID 与版本
- 检索来源 chunk IDs（含文档、位置）
- 模型/温度/系统提示/工具参数
- 仿真配置（几何、材料、边界、扫频）
- 结果摘要、指标、失败原因
- 中间推理与解释（可选开关）

## 5. 关键工作流（示例）
**A. Datasheet → 知识图谱**
1) 上传 PDF → 对象存储
2) MinerU 解析（8002）→ 结构化块
3) 分块/分类 → 抽取参数、实体、关系
4) 规范化 → 合并/消歧
5) 入库 KG + pgvector
6) 生成可追溯报告

**B. 研究问答 / 设计建议**
1) 问题解析 → 检索向量与图
2) Prompt 编排 → LLM/VLM/仿真接口调用
3) 结果汇总 → 结构化输出 + 追溯链路

## 6. 安全与多租户
- 用户、团队、项目三级权限
- 项目级隔离（数据、模型、提示词版本）
- 对外接口默认脱敏日志（不输出密钥/密码）

## 7. 前端方向（Research-grade + SaaS）
- Next.js（React）为前端框架
- 模块化插件架构：插件注册表驱动 UI、每个能力是独立卡片
- Workflow/Prompt 驱动 UI：页面以工作流与提示词目录为核心视图
- 深色/冷色调（蓝、紫、灰）
- 卡片化模块（Feature Cards）
- 功能分区：项目概览 / 工作流 / 数据资产 / 实验记录
- 与后端模块一一对应（模块即卡片）

## 8. Docker 化规划（预留）
未来每个能力模块可独立打包，预留如下服务：
- `api-gateway`（Django/DRF）
- `worker`（异步任务）
- `mineru-parser`（8002）
- `kg-service`
- `vector-service`
- `simulator-adapter`
- `object-storage`
- `postgres`
- `redis`

不在本轮直接落地 Dockerfile，但保留目录与配置入口。

## 9. 实施阶段（建议里程碑）
**Phase 0：平台底座**
- 环境配置文档 + 配置加载机制
- Postgres/pgvector 接入
- Prompt 仓库结构与版本化

**Phase 1：Datasheet 管线稳定**
- MinerU 接入与替换 docling
- 解析 → 抽取 → 图谱与向量联动
- 追溯链路落库

**Phase 2：研究问答与检索增强**
- 多模态检索、图谱检索融合
- 输出结构化报告与可视化

**Phase 3：仿真接口统一化**
- HFSS/CST/COMSOL 适配器
- 统一的仿真配置 DSL

**Phase 4：生产化与多租户**
- 权限/审计/安全
- 资源隔离与配额
