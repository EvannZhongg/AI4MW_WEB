export type CurveExtractionPoint = {
  x: number;
  y: number;
  line_id: number;
  x_shift?: number;
  y_shift?: number;
  actual_x?: number;
  actual_y?: number;
  x_unit?: string;
  x_unit_factor?: number;
};

export type CurveExtractionAxis = {
  origin?: [number, number];
  x_scale?: number;
  x_offset?: number;
  y_scale?: number;
  y_offset?: number;
  x_unit?: string;
  x_unit_factor?: number;
  x_axis_tick_count?: number;
  y_axis_tick_count?: number;
};

export type CurveExtractionSummary = {
  curve_count?: number;
  point_count?: number;
};

export type CurveExtractionArtifacts = Record<string, string | null>;

export type CurveExtractionResult = {
  request_id: string;
  summary?: CurveExtractionSummary;
  axis?: CurveExtractionAxis;
  artifacts?: CurveExtractionArtifacts;
  data?: CurveExtractionPoint[];
};

export type CurveSeriesPoint = {
  actualX: number;
  actualY: number;
};

export type CurveSeries = {
  lineId: number;
  points: CurveSeriesPoint[];
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function buildCurveSeries(data: CurveExtractionPoint[] = []) {
  const grouped = new Map<number, CurveSeriesPoint[]>();

  for (const point of data) {
    const actualX = isFiniteNumber(point.actual_x) ? point.actual_x : point.x;
    const actualY = isFiniteNumber(point.actual_y) ? point.actual_y : point.y;
    if (!isFiniteNumber(actualX) || !isFiniteNumber(actualY)) {
      continue;
    }
    if (!grouped.has(point.line_id)) {
      grouped.set(point.line_id, []);
    }
    grouped.get(point.line_id)?.push({ actualX, actualY });
  }

  return Array.from(grouped.entries())
    .map(([lineId, points]) => ({
      lineId,
      points: [...points].sort((left, right) => left.actualX - right.actualX)
    }))
    .filter((series) => series.points.length > 0);
}

export function getCurveBounds(series: CurveSeries[]) {
  if (series.length === 0) {
    return null;
  }

  const xValues = series.flatMap((item) => item.points.map((point) => point.actualX));
  const yValues = series.flatMap((item) => item.points.map((point) => point.actualY));

  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);

  return {
    minX,
    maxX: maxX === minX ? maxX + 1 : maxX,
    minY,
    maxY: maxY === minY ? maxY + 1 : maxY
  };
}

export function formatMetric(value: number | undefined, digits = 4) {
  if (!isFiniteNumber(value)) {
    return "--";
  }
  return value.toFixed(digits);
}
