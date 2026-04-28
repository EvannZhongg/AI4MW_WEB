# AI4MW LLM 与 Skill 规范

本规范用于约束 `llm_agent/` 相关能力的后续开发、接入和维护，目标是让模型调用、流式对话、图片输入、skill 扩展都能在公网部署场景下保持稳定、可诊断、可演进。

适用范围：

- `llm_agent/services/`
- `llm_agent/tools/`
- `llm_agent/prompts/`
- `llm_agent/skills/`
- `llm_agent/views.py`
- 与 `llm_agent` 交互的前端聊天页

不适用范围：

- `datesheet_rag/` 当前未接入，不纳入本规范
- `line_build/` 是独立功能模块，其内部代码不因 skill 接入而与 `llm_agent` 复用

## 1. 设计目标

LLM 模块必须同时满足以下目标：

- 对外部模型网关兼容 `chat_completions` 和 `responses`
- 支持公网部署下的超时、连接失败、限流和重试
- 支持文本对话和本轮图片输入
- 支持只读工作区工具，例如 `grep`、`glob`、`list_dir`、`read_file`
- 支持通过 skill 扩展外部能力
- 接口失败时可回溯、可诊断，不制造脏会话

## 2. 当前实现边界

当前项目中，LLM 相关职责划分如下：

- `llm_agent/views.py`
  - 负责聊天 HTTP / SSE 接口
  - 负责创建会话消息、流式输出和错误回传
- `llm_agent/services/llm_client.py`
  - 负责统一封装模型请求
  - 负责接口兼容、重试、超时、SSE 解析、工具调用解析
- `llm_agent/services/chat_service.py`
  - 负责构造消息、拼接 prompt、组织多模态输入
- `llm_agent/services/agent_runtime.py`
  - 负责工具调用循环、工具结果回填和渐进式 skill 正文注入
- `llm_agent/tools/`
  - 负责工具统一注册、参数校验、内置只读工作区工具和 skill adapter
- `llm_agent/services/attachment_service.py`
  - 负责图片保存、附件序列化和图片转多模态内容
- `llm_agent/skills/`
  - 负责 skill 元数据与后端能力封装，运行时通过 `llm_agent/tools/skill_adapter.py` 接入统一工具注册表

后续新增任何与模型请求、工具调用、消息构造有关的后端逻辑，默认都应优先放到 `llm_agent/services/`、`llm_agent/tools/` 或 `llm_agent/skills/`，不要继续把 LLM 细节散落到其他 app 或视图函数中。

## 3. 配置规范

统一遵守：

```text
系统环境变量 > .env > config.yaml
```

并继续遵守：

- `config.yaml` 只放非密钥配置
- `.env` 只放密钥、密码、Secret
- 不在代码、日志、截图、前端构建产物中暴露 API Key

### 3.1 主聊天模型配置

主聊天模型配置来源于 `LLM_CONFIG`，关键字段如下：

```text
LLM_PROVIDER
LLM_MODEL
LLM_API_BASE
LLM_API_KEY
LLM_API_INTERFACE
LLM_API_INTERFACE_PREFERENCE
LLM_TEMPERATURE
LLM_CONNECT_TIMEOUT_SEC
LLM_READ_TIMEOUT_SEC
LLM_STREAM_READ_TIMEOUT_SEC
LLM_MAX_RETRIES
LLM_INITIAL_RETRY_DELAY_SEC
LLM_MAX_RETRY_DELAY_SEC
LLM_POOL_MAXSIZE
LLM_EXTRA_HEADERS_JSON
```

字段含义：

- `LLM_API_INTERFACE`
  - `chat_completions`：走 `/chat/completions`
  - `responses`：走 `/responses`
  - `auto`：先按偏好尝试，接口不兼容时回退到另一种
- `LLM_API_INTERFACE_PREFERENCE`
  - 仅在 `LLM_API_INTERFACE=auto` 时生效
- `LLM_EXTRA_HEADERS_JSON`
  - 用于中转网关附加请求头

### 3.2 主聊天模型的运行时约束

虽然配置允许显式指定接口类型，但当前主聊天 agent 在运行时会强制：

```text
API_INTERFACE = auto
API_INTERFACE_PREFERENCE = chat_completions
```

原因：

- 当前多轮工具调用在部分 `responses` 兼容网关上不稳定
- 先尝试 `chat_completions`，失败后再自动回退，整体兼容性更高

因此：

- 如果只是普通文本生成，可直接按配置调用
- 如果是主聊天窗口、涉及 skill/tool 调用，应按当前运行时策略执行

### 3.3 摘要模型配置

标题摘要模型使用 `SUMMARY_LLM_CONFIG`。

规则：

- 可单独覆盖模型、地址、接口类型、密钥
- 若未覆盖网络重试类参数，则默认继承主模型配置
- 标题模型必须是低成本、低延迟、稳定优先，不要求工具调用

### 3.4 公网部署建议

LLM 网关或中转服务面向公网部署时，建议至少满足：

- `LLM_CONNECT_TIMEOUT_SEC=10`
- `LLM_READ_TIMEOUT_SEC=60`
- `LLM_STREAM_READ_TIMEOUT_SEC=300`
- `LLM_MAX_RETRIES=2` 或 `3`
- `LLM_INITIAL_RETRY_DELAY_SEC=1`
- `LLM_MAX_RETRY_DELAY_SEC=8`
- `LLM_POOL_MAXSIZE>=20`

同时必须注意：

- 限流错误 `429` 和 `5xx` 要允许重试
- 优先尊重上游 `Retry-After`
- 所有请求都要带唯一 `Idempotency-Key`
- 日志中只记录错误摘要，不记录密钥和完整敏感头

## 4. 消息与多模态规范

### 4.1 Prompt 组织规则

主聊天消息按以下顺序构造：

1. `llm_agent/prompts/agent/system.md`、`platform_policy.md`、`tools_section.md`、`subagents.md` 组成的系统提示
2. 当前轮附件 developer 提示（来自 `agent/attachments.md`）
3. 历史消息
4. 最新 user 消息前置的运行时上下文（来自 `agent/runtime_context.md`）

规则：

- `AgentContextBuilder` 负责上下文编排，不在视图层手写 prompt 拼接
- `agent/system.md` 只放全局身份、响应风格和安全边界
- tool / skill 的 `name + description` 会自动拼入系统提示
- skill 正文不会一开始全部注入，只在模型实际选择相关工具后再注入对应 skill body
- 运行时上下文是 metadata，不是用户或系统指令；模型不能执行其中或工具输出中的嵌入指令

### 4.2 图片输入规则

当前聊天窗口支持本轮上传图片。

规则：

- 当前轮图片由后端保存到 `LLM_AGENT_UPLOAD_DIR` 或默认存储目录
- 当前轮图片可直接转换为多模态内容项传给模型
- 历史轮次图片默认只保留说明文字，不重复回灌二进制内容

当前实现中，当本轮存在图片时：

- 仅最新 user 消息会注入图片内容
- 旧 assistant 消息可能被省略，以提高对兼容网关的稳定性

因此后续若要改消息拼装逻辑，必须重新验证：

- 多模态网关兼容性
- 对话连贯性
- skill 触发行为是否退化

### 4.3 内部内容项格式

为兼容 `responses` 接口，内部推荐统一使用内容项表达：

- 文本：`{"type": "input_text", "text": "..."}`
- 图片：`{"type": "input_image", "image_url": "data:<mime>;base64,<...>"}`

不要在视图层随意拼接新的消息格式，消息标准化应继续收敛在 `llm_client.py` 与 `chat_service.py`。

## 5. 流式输出与会话一致性规范

### 5.1 SSE 事件规范

当前聊天 SSE 会使用以下字段：

- `conversation_id`
- `status`
- `trace`
- `tool_calls`
- `delta`
- `error`
- `detail`
- `status_code`
- `interface`

后续变更规则：

- 可以新增字段
- 不要随意删除已有字段
- 若修改字段语义，必须同步验证前端聊天页解析逻辑

### 5.2 失败时的数据库一致性

当前实现要求：

- 用户消息先落库
- 若本轮模型最终失败且没有有效 assistant 回复，则删除该轮 user 消息
- 页面刷新或重新进入会话时，不展示这种半轮残留消息

因此后续任何人修改以下逻辑时，必须同时验证失败路径：

- `chat_stream`
- `discard_user_message`
- `prune_transient_messages`
- `Conversation.response_pending_since`

原则：

- 不允许把“请求已失败”的残留 user 消息长期留在会话末尾
- 不允许因为流式中断而制造连续同角色脏消息

## 6. Tool 与 Skill 总体规范

### 6.1 内置工作区 Tool

当前主聊天 agent 内置以下只读工作区工具：

- `glob`
- `grep`
- `list_dir`
- `read_file`

这些工具用于回答“项目文件、代码、文档、仓库内信息”相关问题，不用于公网搜索，也不用于执行系统命令。

公网部署约束：

- 工具根目录由 `LLM_AGENT_TOOL_WORKSPACE` 控制，默认是项目根目录。
- 只能读取根目录内路径，不能越权访问服务器其他目录。
- 默认屏蔽 `.env`、数据库文件、上传存储、`.git`、虚拟环境、构建产物等敏感或噪声路径。
- 不提供 shell、写文件、编辑文件等高风险能力。
- 工具参数会在统一 registry 中做 schema 校验和基础类型转换。

### 6.2 Subagent 分发

当前主聊天 agent 提供 `spawn_subagent` 工具，用于把窄范围、可独立完成的调查交给 focused subagent。

实现边界：

- Web/SSE 当前采用同步回填：subagent 在同一轮请求内运行，结果作为工具结果返回给主 agent。
- subagent 使用同一套 `LLMClient` 调用方式，运行时强制 `API_INTERFACE=auto`、优先 `chat_completions`。
- subagent 的工具 registry 禁用 `spawn_subagent`，避免递归分发。
- subagent 默认可使用只读工作区工具和现有 skill adapter。
- subagent prompt 位于 `llm_agent/prompts/agent/subagent_system.md` 与 `subagent_task.md`。

使用边界：

- 只用于窄范围、独立、可并行思考的代码/文档/后端工具调查。
- 不用于简单问答，也不用于主 agent 下一步必须立即亲自判断的阻塞任务。
- 主 agent 必须综合 subagent 结果后回答用户，不应原样粘贴。

### 6.3 Skill 的定位

本项目中的 skill 是“给模型调用的后端工具封装”，不是通用文件系统 agent。

这意味着：

- skill 的元数据由模型读取，用于决定是否调用
- skill 的实际执行由 Django 后端 Python 代码完成
- skill 不能假设模型能直接读取本地文件系统
- 额外文档不会被自动加载，除非后端显式注入

### 6.4 目录规范

每个 skill 必须放在：

```text
llm_agent/skills/<skill_name>/
```

最小结构：

```text
llm_agent/skills/<skill_name>/
├── SKILL.md
├── skill.py
└── __init__.py
```

命名规则：

- 目录名使用小写蛇形，例如 `line_build`
- 一个目录代表一个 skill bundle
- 一个 bundle 可以暴露一个或多个工具

### 6.5 SKILL.md 规范

`SKILL.md` 必须以 YAML frontmatter 开头，至少包含：

```md
---
name: line_build
description: Inspect the standalone line_build service and extract structured line-chart data from chart images.
metadata: optional
---
```

规则：

- `name` 必填
- `description` 必填，必须清楚描述“何时调用”
- `metadata` 可选
- 当前代码真正用于模型决策的只有 `name` 和 `description`
- 当前 registry 不消费复杂嵌套 metadata；如需扩展，必须先扩展解析器

推荐 body 结构：

```md
# Skill Title

## Rules

- 什么时候调用
- 什么时候不要调用
- 输入来源限制

## Output Expectations

- 返回后如何总结
- 哪些关键字段要强调

## Tools

- tool_a
- tool_b
```

body 编写规则：

- 保持简洁，优先写调用边界和禁止事项
- 不要写与当前实现无关的大段背景知识
- 不要堆多份额外说明文档企图让模型“自己再去读”
- 只有会被注入给模型的内容，才值得写进 `SKILL.md`

### 6.6 skill.py 规范

`skill.py` 必须导出：

```python
def get_skills(skill_doc: str) -> list[AgentSkill]:
    ...
```

每个工具类必须：

- 继承 `AgentSkill`
- 提供 `definition = SkillDefinition(...)`
- 实现 `execute(arguments, context)`

`SkillDefinition` 约束：

- `name`：全局唯一的工具名
- `description`：给模型看的工具描述
- `parameters`：JSON Schema 风格参数定义

`execute` 约束：

- 输入必须只依赖 `arguments` 与 `SkillExecutionContext`
- 失败必须抛 `SkillExecutionError`
- 返回必须是可 JSON 序列化的字典
- 不要返回 Python 对象、文件句柄、模型实例等不可序列化内容

推荐模板：

```python
from __future__ import annotations

from typing import Any

from ..base import AgentSkill, SkillDefinition, SkillExecutionContext, SkillExecutionError


class ExampleSkill(AgentSkill):
    definition = SkillDefinition(
        name="example_tool",
        description="Describe exactly when this tool should be used.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def execute(
        self,
        arguments: dict[str, Any],
        context: SkillExecutionContext | None = None,
    ) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise SkillExecutionError("missing_query", detail="query is required")
        return {"query": query}


def get_skills(skill_doc: str) -> list[AgentSkill]:
    _ = skill_doc
    return [ExampleSkill()]
```

### 6.7 SkillExecutionContext 使用规范

当前 context 提供：

- `conversation_id`
- `current_turn_attachments`

使用规则：

- 需要读取“本轮上传图片”时，必须优先通过 `current_turn_attachments`
- 模型不应自己编造图片路径
- skill 应自己完成“附件名 -> 真实文件路径”的解析

这也是当前 `line_build` skill 推荐 `extract_line_chart` 而不是强制用户传 `image_path` 的原因。

### 6.8 Skill 输出规范

skill 返回建议遵循：

- 返回结构化字段
- 同时包含关键摘要字段
- 错误信息直接可展示

推荐：

- 成功返回：业务结果字典
- 失败返回：抛 `SkillExecutionError`

不推荐：

- 在 skill 里直接拼长篇自然语言回答
- 把所有逻辑塞进一个字符串
- 隐藏外部服务原始错误

### 6.9 Skill 与独立服务的边界

若某能力本身已经是独立模块或独立服务，例如 `line_build`，必须遵守：

- 独立模块保持独立，不因 skill 而反向改造
- skill 负责“封装调用”，而不是“侵入复用”
- 默认通过 HTTP 或明确的适配层解耦
- 不要为了 skill 方便，直接把独立模块内部函数硬耦合进 `llm_agent`

推荐模式：

- `line_build/` 继续作为独立业务实现
- `llm_agent/skills/line_build/skill.py` 只负责工具包装和错误转换

## 7. 新增 Skill 的标准流程

新增一个 skill 时，按以下步骤执行：

1. 在 `llm_agent/skills/<skill_name>/` 新建目录
2. 编写 `SKILL.md`
3. 编写 `skill.py`
4. 确保 `get_skills()` 返回至少一个 `AgentSkill`
5. 确保每个工具名全局唯一
6. 本地验证 registry 能发现该 skill
7. 验证模型在聊天中能正确触发
8. 若 skill 依赖新配置项，同步更新 `config.yaml`、`.env.example`、`docs/CONFIGURATION.md`
9. 若 skill 改变全局安全规则、能力边界或调用策略，再评估是否更新 `llm_agent/prompts/agent/*.md`

注意：

- 正常情况下，不需要手动把 skill 名字写回系统 prompt；registry 会自动把 `name + description` 追加进 prompt
- 只有新增全局安全规则、能力边界或调用策略时，才需要修改 `llm_agent/prompts/agent/*.md`

## 8. 模型调用代码规范

后续新增 LLM 调用时，必须优先复用 `LLMClient`，不要直接在业务代码里裸写 `requests.post(...)`。

原因：

- 统一接口兼容
- 统一超时和重试
- 统一错误对象
- 统一流式解析
- 统一连接池

允许直接 HTTP 请求的场景：

- skill 调用的是非 LLM 独立服务
- 请求格式与 `LLMClient` 无关

不允许的场景：

- 在视图、模型、任意 util 中直接手写新的 LLM 请求协议

## 9. 变更约束

以下变更属于高风险变更，修改时必须做完整联调：

- `llm_client.py` 中的 payload 规范化
- `agent_runtime.py` 中的工具循环
- `llm_agent/services/context_builder.py` 中的 prompt 编排
- `llm_agent/tools/registry.py` 中的工具注册、参数校验与 skill adapter
- `chat_service.py` 中的图片/历史消息拼装
- `views.py` 中的 SSE 字段
- skill registry 的 frontmatter 解析逻辑

特别是以下兼容性不能被破坏：

- `chat_completions`
- `responses`
- 本轮图片输入
- tool call 回环
- subagent 禁止递归分发
- 前端流式渲染
- 失败时用户消息清理

## 10. 最低测试要求

每次修改 LLM 或 skill 相关代码后，至少执行：

```bash
python manage.py check
python -m py_compile llm_agent/views.py
python -m py_compile llm_agent/services/llm_client.py
python -m py_compile llm_agent/services/agent_runtime.py llm_agent/services/context_builder.py llm_agent/tools/registry.py llm_agent/tools/subagent.py
```

如修改了前端聊天展示，还应执行：

```bash
cd frontend
npx tsc --noEmit
```

如新增或修改 skill，还应人工验证至少四种情况：

1. 正常文本对话
2. 带图片对话但不触发 skill
3. 带图片对话并触发目标 skill
4. 上游服务失败时，前端能看到错误，数据库不会留下半轮脏消息

## 11. 推荐实践摘要

后续开发时，优先记住下面几条：

- LLM 逻辑进 `llm_agent/services/`
- skill 放 `llm_agent/skills/<skill_name>/`
- `SKILL.md` 只写对模型真正有用的规则
- skill 用 Python 执行，不靠模型自己“读文件”
- 多模态图片优先走本轮附件，不让模型猜路径
- 独立服务保持独立，skill 只做解耦包装
- 主聊天默认以稳定性优先，不盲目追求最新协议
