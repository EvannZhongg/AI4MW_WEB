---
name: line_build
description: Inspect the standalone line_build service and extract structured line-chart data from chart images. Use when the user asks for line chart health checks, curve extraction, axis fitting details, artifact paths, or point-level data from a chart image. Prefer the current turn's uploaded image when available, and fall back to explicit server-accessible image paths only when needed.
---

# Line Build

Use this skill to call the standalone `line_build` backend.

## Rules

- Use `line_chart_service_health` when the user wants to confirm whether the service is reachable or healthy.
- Use `extract_line_chart` for normal chat usage. It can directly consume the current turn's uploaded image and forward the file to the standalone `line_build` service without requiring the model to know the backend path.
- Use `extract_line_chart_by_path` only when the image path is already visible to the backend or the line_build service.
- If the current turn contains multiple uploaded images, pass `attachment_name` to `extract_line_chart` when you need to select a specific one.
- Do not pretend that a browser blob URL or local desktop path is a valid server-side path. Only `extract_line_chart` may rely on the backend's current-turn attachment forwarding.

## Output Expectations

- Summarize the extraction outcome in plain language.
- Highlight key fields such as `summary`, `axis`, `artifacts`, and whether `data` rows are included.
- If the backend returns an error, surface it directly and suggest the next likely fix.

## Tools

- `line_chart_service_health`
- `extract_line_chart`
- `extract_line_chart_by_path`
