"use client";

import {
  buildCurveSeries,
  formatMetric,
  getCurveBounds,
  type CurveExtractionResult
} from "@/lib/curveExtraction";

const PALETTE = ["#49d0ff", "#5f8dff", "#8a63ff", "#5ee48c", "#ffd166", "#ff7b7b"];

type CurveExtractionChartProps = {
  result: CurveExtractionResult;
};

export function CurveExtractionChart({ result }: CurveExtractionChartProps) {
  const series = buildCurveSeries(result.data ?? []);
  const bounds = getCurveBounds(series);

  if (!bounds || series.length === 0) {
    return (
      <div className="curve-chart-empty">
        <p>当前结果未返回可绘制的点集，暂时无法生成曲线预览。</p>
      </div>
    );
  }

  const width = 900;
  const height = 420;
  const padding = { top: 28, right: 28, bottom: 44, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const xRange = bounds.maxX - bounds.minX;
  const yRange = bounds.maxY - bounds.minY;
  const xTicks = 5;
  const yTicks = 4;

  const mapX = (value: number) => padding.left + ((value - bounds.minX) / xRange) * plotWidth;
  const mapY = (value: number) =>
    padding.top + (1 - (value - bounds.minY) / yRange) * plotHeight;

  return (
    <div className="curve-chart-shell">
      <svg
        className="curve-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="提取结果曲线图"
      >
        <rect
          x={padding.left}
          y={padding.top}
          width={plotWidth}
          height={plotHeight}
          rx="18"
          className="curve-plot-bg"
        />

        {Array.from({ length: yTicks + 1 }, (_, index) => {
          const ratio = index / yTicks;
          const y = padding.top + ratio * plotHeight;
          const value = bounds.maxY - ratio * yRange;
          return (
            <g key={`y-${index}`}>
              <line
                x1={padding.left}
                y1={y}
                x2={padding.left + plotWidth}
                y2={y}
                className="curve-grid-line"
              />
              <text x={padding.left - 12} y={y + 4} textAnchor="end" className="curve-axis-label">
                {formatMetric(value, 2)}
              </text>
            </g>
          );
        })}

        {Array.from({ length: xTicks + 1 }, (_, index) => {
          const ratio = index / xTicks;
          const x = padding.left + ratio * plotWidth;
          const value = bounds.minX + ratio * xRange;
          return (
            <g key={`x-${index}`}>
              <line
                x1={x}
                y1={padding.top}
                x2={x}
                y2={padding.top + plotHeight}
                className="curve-grid-line"
              />
              <text
                x={x}
                y={padding.top + plotHeight + 24}
                textAnchor="middle"
                className="curve-axis-label"
              >
                {formatMetric(value, 2)}
              </text>
            </g>
          );
        })}

        {series.map((item, index) => {
          const color = PALETTE[index % PALETTE.length];
          const points = item.points
            .map((point) => `${mapX(point.actualX)},${mapY(point.actualY)}`)
            .join(" ");
          return (
            <g key={item.lineId}>
              <polyline points={points} fill="none" stroke={color} strokeWidth="3.5" strokeLinejoin="round" />
              {item.points.map((point, pointIndex) => (
                <circle
                  key={`${item.lineId}-${pointIndex}`}
                  cx={mapX(point.actualX)}
                  cy={mapY(point.actualY)}
                  r="2.6"
                  fill={color}
                />
              ))}
            </g>
          );
        })}
      </svg>

      <div className="curve-chart-footer">
        <div className="curve-legend">
          {series.map((item, index) => (
            <div key={item.lineId} className="curve-legend-item">
              <span
                className="curve-legend-swatch"
                style={{ backgroundColor: PALETTE[index % PALETTE.length] }}
              />
              <span>Curve {item.lineId}</span>
              <strong>{item.points.length} pts</strong>
            </div>
          ))}
        </div>
        <div className="curve-range-summary">
          <span>X: {formatMetric(bounds.minX, 2)} to {formatMetric(bounds.maxX, 2)}</span>
          <span>Y: {formatMetric(bounds.minY, 2)} to {formatMetric(bounds.maxY, 2)}</span>
          <span>Unit: {result.axis?.x_unit ?? "--"}</span>
        </div>
      </div>
    </div>
  );
}
