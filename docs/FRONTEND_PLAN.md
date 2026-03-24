# 前端架构规划（Next.js + 插件化）

## 1. 技术选型
- Next.js（React）
- App Router（`src/app`）
- 组件与插件分层清晰，全部通过注册表驱动渲染

## 2. 目录结构
```
frontend/
  src/
    app/                 # 页面入口与全局样式
    components/          # UI 组件（卡片、标签、标题）
    plugins/             # 插件定义与注册表
      modules/           # 各插件 UI 模块
      registry.ts        # 插件注册表
      types.ts           # 插件类型定义
    workflows/           # 工作流目录（以 prompt_id 绑定）
    prompts/             # 提示词目录（只展示 metadata）
```

## 3. 插件化规范
- 每个插件包含：`id/title/description/category/status/tags/entry`
- `entry` 为可渲染组件，插件只暴露公开接口信息
- 页面通过 `pluginRegistry` 渲染卡片与功能摘要

## 4. Workflow/Prompt 驱动 UI
- `workflowCatalog` 定义流程：`steps + promptId`
- `promptCatalog` 仅展示提示词元信息（id/版本/作用域）
- 页面以“工作流库”和“提示词目录”作为核心入口

## 5. 设计与视觉
- 深色/冷色调（蓝/紫/灰）
- 卡片化模块（Feature Cards）
- 结构化内容分区：模块、工作流、提示词

## 6. 后续扩展
- 读取后端插件注册表（API）
- 运行时启用/禁用插件
- 工作流可视化编排（拖拽式）

