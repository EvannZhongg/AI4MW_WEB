"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CurveExtractionChart } from "@/components/CurveExtractionChart";
import { runtimeConfig } from "@/config/runtime";
import type { CurveExtractionResult } from "@/lib/curveExtraction";

type ServiceHealth = {
  status: string;
  service?: string;
  port?: number;
};

type PreviewMeta = {
  width: number;
  height: number;
};

const tableColumns = ["line_id", "actual_x", "actual_y", "x", "y", "x_shift", "y_shift"];

export default function CurveExtractionPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewMeta, setPreviewMeta] = useState<PreviewMeta | null>(null);
  const [includeDataRows, setIncludeDataRows] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CurveExtractionResult | null>(null);
  const [health, setHealth] = useState<ServiceHealth | null>(null);

  useEffect(() => {
    const loadHealth = async () => {
      try {
        const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/line-charts/health`);
        if (!response.ok) {
          throw new Error("health_failed");
        }
        const data = (await response.json()) as ServiceHealth;
        setHealth(data);
      } catch (loadError) {
        setHealth({
          status: "offline",
          service: "line-chart-backend"
        });
      }
    };
    void loadHealth();
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const previewRows = useMemo(() => {
    return (result?.data ?? []).slice(0, 18);
  }, [result?.data]);

  const selectFile = (file: File | null) => {
    setError(null);
    setResult(null);
    setSelectedFile(file);
    setPreviewMeta(null);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    if (file) {
      setPreviewUrl(URL.createObjectURL(file));
    }
  };

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) {
      return;
    }
    const [file] = Array.from(files).filter((item) => item.type.startsWith("image/"));
    if (!file) {
      setError("请上传 PNG、JPG、JPEG 等图片格式。");
      return;
    }
    selectFile(file);
  };

  const handleSubmit = async () => {
    if (!selectedFile || isSubmitting) {
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("include_data_rows", String(includeDataRows));

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/line-charts/extract`, {
        method: "POST",
        body: formData
      });
      const payload = (await response.json().catch(() => null)) as
        | CurveExtractionResult
        | { detail?: string; error?: string }
        | null;

      if (!response.ok) {
        const detail =
          payload && "detail" in payload && payload.detail
            ? payload.detail
            : payload && "error" in payload && payload.error
              ? payload.error
              : "曲线提取失败，请稍后重试。";
        throw new Error(detail);
      }

      if (!payload || !("request_id" in payload)) {
        throw new Error("算法服务返回了不可识别的结果。");
      }

      setResult(payload);
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "曲线提取失败，请稍后再试。"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="feature-page">
      <header className="page-header page-header-wide">
        <div>
          <span className="page-kicker">Line Chart Extraction</span>
          <h1>曲线提取工作台</h1>
          <p>
            上传折线图图片后，系统会通过 `LineFormer + OCR + 坐标拟合` 生成结构化曲线点集，并在页面内直接完成结果可视化。
          </p>
        </div>
        <div className="service-card">
          <span className={`service-dot ${health?.status === "ok" ? "online" : "offline"}`} />
          <div>
            <strong>曲线提取引擎</strong>
            <p>
              {health?.status === "ok"
                ? "当前可接收识别任务，结果将直接返回到此页面。"
                : "当前暂不可用，请稍后重试或联系管理员排查服务状态。"}
            </p>
          </div>
        </div>
      </header>

      <div className="curve-page-grid">
        <div className="curve-upload-panel panel-card">
          <div className="panel-head">
            <div>
              <span className="page-kicker">Input</span>
              <h2>上传折线图图片</h2>
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                if (selectedFile) {
                  selectFile(null);
                  return;
                }
                inputRef.current?.click();
              }}
            >
              {selectedFile ? "清空" : "选择图片"}
            </button>
          </div>

          <label
            className={`curve-dropzone ${selectedFile ? "has-file is-previewing" : ""}`}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              handleFiles(event.dataTransfer.files);
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className="file-input"
              onChange={(event) => handleFiles(event.target.files)}
            />
            {previewUrl ? (
              <div className="curve-image-frame curve-image-frame-inline">
                <div className="curve-image-stage">
                  <img
                    src={previewUrl}
                    alt={selectedFile?.name ?? "上传图像"}
                    onLoad={(event) => {
                      const image = event.currentTarget;
                      setPreviewMeta({
                        width: image.naturalWidth,
                        height: image.naturalHeight
                      });
                    }}
                  />
                </div>
              </div>
            ) : (
              <div className="curve-dropzone-copy">
                <strong>拖拽图片到此，或点击选择文件</strong>
                <p>推荐上传结构清晰、坐标轴完整、刻度文字清楚的标准二维折线图。</p>
              </div>
            )}
          </label>

          {previewUrl ? (
            <p className="preview-note">
              预览已直接嵌入上传区域。你可以继续拖拽新图片替换，或点击右上角“清空”重新开始。
            </p>
          ) : null}

          <div className="curve-upload-controls">
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={includeDataRows}
                onChange={(event) => setIncludeDataRows(event.target.checked)}
              />
              <span>返回完整逐点数据，用于页面内可视化与结果表格预览</span>
            </label>

            <button
              type="button"
              className="solid-button primary-action"
              disabled={!selectedFile || isSubmitting}
              onClick={() => void handleSubmit()}
            >
              {isSubmitting ? "正在提取..." : "开始曲线提取"}
            </button>
          </div>

          {error ? <div className="status-banner error">{error}</div> : null}
          {selectedFile ? (
            <div className="file-metadata">
              <span>{selectedFile.name}</span>
              <span>{(selectedFile.size / 1024).toFixed(1)} KB</span>
              <span>{selectedFile.type || "image/*"}</span>
              {previewMeta ? <span>{previewMeta.width} × {previewMeta.height}px</span> : null}
            </div>
          ) : null}
        </div>

        <div className="curve-visualization-panel panel-card">
          <div className="panel-head">
            <div>
              <span className="page-kicker">Visualization</span>
              <h2>提取结果可视化</h2>
            </div>
          </div>

          {result ? (
            <CurveExtractionChart result={result} />
          ) : (
            <div className="empty-state-card compact">
              <p className="empty-state-title">等待提取结果</p>
              <p>上传图片并开始识别后，这里会展示结构化折线的图形预览与曲线统计。</p>
            </div>
          )}
        </div>
      </div>

      {result ? (
        <div className="curve-results">
          <div className="metric-grid">
            <div className="metric-card">
              <span>Request ID</span>
              <strong>{result.request_id}</strong>
            </div>
            <div className="metric-card">
              <span>识别曲线数</span>
              <strong>{result.summary?.curve_count ?? "--"}</strong>
            </div>
            <div className="metric-card">
              <span>数据点总数</span>
              <strong>{result.summary?.point_count ?? "--"}</strong>
            </div>
            <div className="metric-card">
              <span>横轴单位</span>
              <strong>{result.axis?.x_unit ?? "--"}</strong>
            </div>
          </div>

          <div className="curve-visual-grid">
            <div className="panel-card">
              <div className="panel-head">
                <div>
                  <span className="page-kicker">Axis</span>
                  <h2>坐标拟合信息</h2>
                </div>
              </div>
              <div className="axis-grid">
                <div><span>Origin</span><strong>{result.axis?.origin?.join(", ") ?? "--"}</strong></div>
                <div><span>X Scale</span><strong>{result.axis?.x_scale ?? "--"}</strong></div>
                <div><span>Y Scale</span><strong>{result.axis?.y_scale ?? "--"}</strong></div>
                <div><span>X Offset</span><strong>{result.axis?.x_offset ?? "--"}</strong></div>
                <div><span>Y Offset</span><strong>{result.axis?.y_offset ?? "--"}</strong></div>
                <div><span>X Ticks</span><strong>{result.axis?.x_axis_tick_count ?? "--"}</strong></div>
                <div><span>Y Ticks</span><strong>{result.axis?.y_axis_tick_count ?? "--"}</strong></div>
                <div><span>Unit Factor</span><strong>{result.axis?.x_unit_factor ?? "--"}</strong></div>
              </div>
            </div>

            <div className="panel-card">
              <div className="panel-head">
                <div>
                  <span className="page-kicker">Data Preview</span>
                  <h2>逐点数据预览</h2>
                </div>
              </div>
              {previewRows.length === 0 ? (
                <p className="muted">当前结果没有返回数据行。</p>
              ) : (
                <div className="table-shell">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {tableColumns.map((column) => (
                          <th key={column}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.map((row, index) => (
                        <tr key={`${row.line_id}-${index}`}>
                          <td>{row.line_id}</td>
                          <td>{row.actual_x ?? "--"}</td>
                          <td>{row.actual_y ?? "--"}</td>
                          <td>{row.x}</td>
                          <td>{row.y}</td>
                          <td>{row.x_shift ?? "--"}</td>
                          <td>{row.y_shift ?? "--"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="panel-note">
                页面默认仅展示前 18 行。完整逐点数据已包含在接口响应中，可继续导出或接入后续分析链路。
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
