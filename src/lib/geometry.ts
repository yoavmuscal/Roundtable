import type { CalibrationPayload, Point, Size } from '../contract';

export const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

export function polygonArea(points: Point[]): number {
  let area = 0;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    area += a.x * b.y - b.x * a.y;
  }
  return area / 2;
}

export function isConvex(points: Point[]): boolean {
  if (points.length < 3) return false;
  let sign = 0;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    const c = points[(i + 2) % points.length];
    const cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    if (Math.abs(cross) < 1e-9) continue;
    const current = Math.sign(cross);
    if (sign === 0) sign = current;
    if (current !== sign) return false;
  }
  return true;
}

export function validateCalibration(payload: CalibrationPayload): string | null {
  const [farLeft, farRight, nearRight, nearLeft] = payload.corners;
  if (!isConvex(payload.corners)) {
    return 'The corner outline crosses over itself. Click far-left, far-right, near-right, then near-left.';
  }
  if (Math.abs(polygonArea(payload.corners)) < 0.015) {
    return 'The four corners need to enclose more of the table. Click farther apart.';
  }
  if (farLeft.x >= farRight.x || nearLeft.x >= nearRight.x) {
    return 'The left corners must be to the left of the right corners.';
  }
  if (farLeft.y >= nearLeft.y || farRight.y >= nearRight.y) {
    return 'The far corners must be above the near corners in the camera view.';
  }
  const centerError = Math.hypot(
    payload.center.x - (farLeft.x + farRight.x + nearRight.x + nearLeft.x) / 4,
    payload.center.y - (farLeft.y + farRight.y + nearRight.y + nearLeft.y) / 4,
  );
  if (centerError > 0.12) {
    return 'The center click is too far from the taped table center. Repeat Check B.';
  }
  return null;
}

function solveLinearSystem(matrix: number[][], values: number[]): number[] {
  const n = values.length;
  const a = matrix.map((row, index) => [...row, values[index]]);
  for (let column = 0; column < n; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < n; row += 1) {
      if (Math.abs(a[row][column]) > Math.abs(a[pivot][column])) pivot = row;
    }
    if (Math.abs(a[pivot][column]) < 1e-12) throw new Error('Degenerate calibration');
    [a[column], a[pivot]] = [a[pivot], a[column]];
    const divisor = a[column][column];
    for (let c = column; c <= n; c += 1) a[column][c] /= divisor;
    for (let row = 0; row < n; row += 1) {
      if (row === column) continue;
      const factor = a[row][column];
      for (let c = column; c <= n; c += 1) a[row][c] -= factor * a[column][c];
    }
  }
  return a.map((row) => row[n]);
}

export type Homography = number[];

export function homographyFromPoints(source: Point[], target: Point[]): Homography {
  if (source.length !== 4 || target.length !== 4) throw new Error('Homography needs four points');
  const rows: number[][] = [];
  const values: number[] = [];
  for (let i = 0; i < 4; i += 1) {
    const { x, y } = source[i];
    const { x: u, y: v } = target[i];
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    values.push(u);
    rows.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    values.push(v);
  }
  return [...solveLinearSystem(rows, values), 1];
}

export function applyHomography(h: Homography, point: Point): Point {
  const denominator = h[6] * point.x + h[7] * point.y + h[8];
  return {
    x: (h[0] * point.x + h[1] * point.y + h[2]) / denominator,
    y: (h[3] * point.x + h[4] * point.y + h[5]) / denominator,
  };
}

export function invert3x3(m: Homography): Homography {
  const a = m[0];
  const b = m[1];
  const c = m[2];
  const d = m[3];
  const e = m[4];
  const f = m[5];
  const g = m[6];
  const h = m[7];
  const i = m[8];
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const determinant = a * A + b * B + c * C;
  if (Math.abs(determinant) < 1e-12) throw new Error('Degenerate calibration');
  return [
    A / determinant,
    -(b * i - c * h) / determinant,
    (b * f - c * e) / determinant,
    B / determinant,
    (a * i - c * g) / determinant,
    -(a * f - c * d) / determinant,
    C / determinant,
    -(a * h - b * g) / determinant,
    (a * e - b * d) / determinant,
  ];
}

export function tableGridLines(size: Size, stepMeters = 0.25): Point[][] {
  const lines: Point[][] = [];
  for (let x = 0; x <= size.width + 1e-9; x += stepMeters) {
    lines.push([
      { x, y: 0 },
      { x, y: size.height },
    ]);
  }
  for (let y = 0; y <= size.height + 1e-9; y += stepMeters) {
    lines.push([
      { x: 0, y },
      { x: size.width, y },
    ]);
  }
  return lines;
}

export interface CoverTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
  drawnWidth: number;
  drawnHeight: number;
}

export function coverTransform(container: Size, source: Size): CoverTransform {
  const scale = Math.max(container.width / source.width, container.height / source.height);
  const drawnWidth = source.width * scale;
  const drawnHeight = source.height * scale;
  return {
    scale,
    drawnWidth,
    drawnHeight,
    offsetX: (container.width - drawnWidth) / 2,
    offsetY: (container.height - drawnHeight) / 2,
  };
}

export function normalizedToStage(
  point: Point,
  container: Size,
  source: Size = { width: 16, height: 9 },
): Point {
  const transform = coverTransform(container, source);
  return {
    x: transform.offsetX + point.x * source.width * transform.scale,
    y: transform.offsetY + point.y * source.height * transform.scale,
  };
}

export function tableToMap(point: Point, tableSize: Size, mapSize: Size): Point {
  const margin = 0.8;
  const x = (point.x + margin) / (tableSize.width + margin * 2);
  const y = (point.y + margin) / (tableSize.height + margin * 2);
  return { x: x * mapSize.width, y: y * mapSize.height };
}
