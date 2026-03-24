# Line Chart Backend API Reference

## 1. 项目定位

该服务用于从折线图图片中提取曲线数据，并返回结构化 JSON 结果。

当前服务默认监听端口为 `8004`，默认无鉴权。

基础地址示例：

```text
http://127.0.0.1:8004
```

在线文档地址：

```text
http://127.0.0.1:8004/docs
http://127.0.0.1:8004/openapi.json
```

## 2. 处理流程

每次识别请求大致经过以下步骤：

1. 接收图片文件或服务端图片路径。
2. 使用 `LineFormer` 模型提取折线像素点。
3. 使用 OCR 检测和识别坐标轴文本。
4. 拟合横轴、纵轴刻度与原点。
5. 将像素坐标换算为实际坐标值。
6. 输出中间 CSV、结果 CSV 和可视化图片。
7. 返回摘要信息、坐标轴信息、产物路径和可选数据行。

## 3. 通用约定

### 3.1 Content-Type

- `GET /api/v1/health`：无需请求体
- `POST /api/v1/line-charts/extract`：`multipart/form-data`
- `POST /api/v1/line-charts/extract-by-path`：`application/json`

### 3.2 返回格式

成功时统一返回 JSON。

失败时返回 FastAPI 标准错误结构：

```json
{
  "detail": "错误描述"
}
```

### 3.3 输出目录

每次请求会在 `storage/<request_id>/` 下生成独立目录：

```text
storage/<request_id>/
  input/
  intermediate/
  visualizations/
  output/
```

## 4. 接口列表

### 4.1 健康检查

```http
GET /api/v1/health
```

用途：

- 判断服务是否启动成功
- 确认当前服务监听端口

示例请求：

```bash
curl http://127.0.0.1:8004/api/v1/health
```

示例响应：

```json
{
  "status": "ok",
  "service": "line-chart-backend",
  "port": 8004
}
```

字段说明：

- `status`：服务状态，正常时为 `ok`
- `service`：服务名称
- `port`：当前服务实际监听端口

### 4.2 上传图片识别

```http
POST /api/v1/line-charts/extract
Content-Type: multipart/form-data
```

用途：

- 适合网站后端上传图片后直接调用
- 不要求图片文件事先存在于容器内部

表单字段：

- `file`：必填，图片文件
- `include_data_rows`：选填，`true/false`，是否在响应中返回完整数据行

`curl` 示例：

```bash
curl -X POST "http://127.0.0.1:8004/api/v1/line-charts/extract" \
  -F "file=@./example.png" \
  -F "include_data_rows=true"
```

成功响应示例：

```json
{
  "request_id": "514e9191edc54c8b8b2732fa9a0f3a8a",
  "summary": {
    "curve_count": 2,
    "point_count": 356
  },
  "axis": {
    "origin": [171, 695],
    "x_scale": 0.0123,
    "x_offset": 1.2,
    "y_scale": 0.0876,
    "y_offset": -42.1,
    "x_unit": "GHz",
    "x_unit_factor": 1000000000.0,
    "x_axis_tick_count": 5,
    "y_axis_tick_count": 6
  },
  "artifacts": {
    "request_directory": "storage/514e9191edc54c8b8b2732fa9a0f3a8a",
    "source_image": "storage/514e9191edc54c8b8b2732fa9a0f3a8a/input/example.png",
    "line_csv": "storage/514e9191edc54c8b8b2732fa9a0f3a8a/intermediate/example.csv",
    "result_csv": "storage/514e9191edc54c8b8b2732fa9a0f3a8a/output/example.csv",
    "ocr_visualization": "storage/514e9191edc54c8b8b2732fa9a0f3a8a/visualizations/example_ocr_vis.png",
    "line_visualization": null,
    "axis_visualization": "storage/514e9191edc54c8b8b2732fa9a0f3a8a/visualizations/example_axis_vis.png"
  },
  "data": [
    {
      "x": 168.0,
      "y": 656.0,
      "line_id": 0,
      "x_shift": -3.0,
      "y_shift": 39.0,
      "actual_x": 3.9451,
      "actual_y": -46.8772,
      "x_unit": "GHz",
      "x_unit_factor": 1000000000.0
    }
  ]
}
```

### 4.3 按服务端路径识别

```http
POST /api/v1/line-charts/extract-by-path
Content-Type: application/json
```

用途：

- 适合图片已经保存在服务器或容器内部某个目录的场景
- 常用于业务系统先上传文件到共享存储，再调用算法服务

请求体：

```json
{
  "image_path": "storage/demo/example.png",
  "include_data_rows": true
}
```

字段说明：

- `image_path`：服务端可访问路径。对于 Docker 容器，路径必须是容器内真实存在的路径
- `include_data_rows`：是否返回完整数据行，默认为 `null`，即按配置项决定

`curl` 示例：

```bash
curl -X POST "http://127.0.0.1:8004/api/v1/line-charts/extract-by-path" \
  -H "Content-Type: application/json" \
  -d "{\"image_path\":\"/app/storage/demo/example.png\",\"include_data_rows\":true}"
```

注意：

- 如果容器没有挂载宿主机目录，那么宿主机上的 `F:\...` 路径在容器里不可见
- 建议将待测目录挂载到容器内，例如 `/app/storage`

## 5. 响应字段说明

### 5.1 顶层字段

- `request_id`：本次请求唯一 ID
- `summary`：提取结果摘要
- `axis`：坐标轴拟合结果
- `artifacts`：生成文件路径
- `data`：逐点明细数据

### 5.2 `summary`

- `curve_count`：识别到的曲线条数
- `point_count`：输出的数据点总数

### 5.3 `axis`

- `origin`：坐标原点像素坐标，格式为 `[x, y]`
- `x_scale`：横轴像素到实际值的缩放因子
- `x_offset`：横轴拟合偏移量
- `y_scale`：纵轴像素到实际值的缩放因子
- `y_offset`：纵轴拟合偏移量
- `x_unit`：横轴单位
- `x_unit_factor`：单位换算因子
- `x_axis_tick_count`：参与横轴拟合的刻度数量
- `y_axis_tick_count`：参与纵轴拟合的刻度数量

### 5.4 `artifacts`

- `request_directory`：本次请求输出目录
- `source_image`：实际用于识别的输入图片路径
- `line_csv`：折线像素点 CSV 路径
- `result_csv`：最终实际坐标 CSV 路径
- `ocr_visualization`：OCR 可视化图路径
- `line_visualization`：折线可视化图路径
- `axis_visualization`：坐标轴检测可视化图路径

### 5.5 `data`

`data` 中每一项通常包含以下字段：

- `x`：原始像素横坐标
- `y`：原始像素纵坐标
- `line_id`：曲线编号
- `x_shift`：相对原点横向偏移
- `y_shift`：相对原点纵向偏移
- `actual_x`：换算后的实际横坐标
- `actual_y`：换算后的实际纵坐标
- `x_unit`：横轴单位
- `x_unit_factor`：横轴单位换算因子

## 6. 错误码说明

### 400 Bad Request

常见原因：

- 上传文件名为空
- 上传文件内容为空
- 表单参数格式错误

### 404 Not Found

常见原因：

- `extract-by-path` 中指定的图片路径不存在
- 服务未挂载对应目录导致容器内无法访问该路径

### 422 Unprocessable Entity

常见原因：

- 没有检测到坐标轴原点
- OCR 未识别出足够刻度
- 刻度拟合失败
- 图片质量或图表结构不满足当前算法前提

### 500 Internal Server Error

常见原因：

- 模型文件不存在
- 运行时依赖缺失
- 推理链路出现未捕获异常

## 7. 部署与联调建议

### 7.1 Docker 启动

服务已经默认切换到 `8004`，可直接启动：

```bash
docker run --rm -p 8004:8004 line-chart-backend:latest
```

### 7.2 挂载输出目录

如果你希望保留识别结果文件，建议挂载 `storage/`：

```bash
docker run --rm -p 8004:8004 \
  -v /your/storage:/app/storage \
  line-chart-backend:latest
```

### 7.3 测试脚本

项目已提供接口测试脚本：

```text
scripts/test_api.py
```

示例：

```bash
python scripts/test_api.py --base-url http://127.0.0.1:8004 --image ./example.png
```

如果要测试服务端路径接口：

```bash
python scripts/test_api.py \
  --base-url http://127.0.0.1:8004 \
  --image ./example.png \
  --path-in-container /app/storage/demo/example.png
```

## 8. 当前限制

- 当前主要面向标准二维线性坐标折线图
- 对对数坐标、断轴图、强遮挡图支持有限
- 依赖 OCR 能识别出足够坐标刻度文本
- `extract-by-path` 仅适合服务端真实可见路径，不适合直接传本机路径字符串
