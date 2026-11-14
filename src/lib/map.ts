import type { Point, Size } from '../contract';

export interface AxialHex {
  q: number;
  r: number;
}

export function axialToPixel(hex: AxialHex, size: number): Point {
  return {
    x: size * Math.sqrt(3) * (hex.q + hex.r / 2),
    y: size * 1.5 * hex.r,
  };
}

export function generateHexGrid(tableSize: Size, margin = 0.8, size = 0.1): AxialHex[] {
  const cells: AxialHex[] = [];
  const qMin = Math.floor((-margin - tableSize.height) / (Math.sqrt(3) * size)) - 2;
  const qMax = Math.ceil((tableSize.width + margin + tableSize.height) / (Math.sqrt(3) * size)) + 2;
  const rMin = Math.floor(-margin / (1.5 * size)) - 2;
  const rMax = Math.ceil((tableSize.height + margin) / (1.5 * size)) + 2;
  for (let r = rMin; r <= rMax; r += 1) {
    for (let q = qMin; q <= qMax; q += 1) {
      const center = hexWorldCenter({ q, r }, size);
      const insideExtent =
        center.x >= -margin &&
        center.x <= tableSize.width + margin &&
        center.y >= -margin &&
        center.y <= tableSize.height + margin;
      const underTable = center.x > 0 && center.x < tableSize.width && center.y > 0 && center.y < tableSize.height;
      if (insideExtent && !underTable) cells.push({ q, r });
    }
  }
  return cells;
}

export function hexWorldCenter(hex: AxialHex, size = 0.1): Point {
  return {
    x: size * Math.sqrt(3) * (hex.q + hex.r / 2),
    y: size * 1.5 * hex.r,
  };
}

export function hexCorners(center: Point, size: number): Point[] {
  const points: Point[] = [];
  for (let i = 0; i < 6; i += 1) {
    const angle = (Math.PI / 180) * (60 * i - 90);
    points.push({ x: center.x + size * Math.cos(angle), y: center.y + size * Math.sin(angle) });
  }
  return points;
}

export function fitRect(content: Size, container: Size): { scale: number; x: number; y: number } {
  const scale = Math.min(container.width / content.width, container.height / content.height);
  return {
    scale,
    x: (container.width - content.width * scale) / 2,
    y: (container.height - content.height * scale) / 2,
  };
}

export function worldToMap(point: Point, tableSize: Size, mapSize: Size): Point {
  const margin = 0.8;
  const world = { width: tableSize.width + margin * 2, height: tableSize.height + margin * 2 };
  const fit = fitRect(world, mapSize);
  return {
    x: fit.x + (point.x + margin) * fit.scale,
    y: fit.y + (point.y + margin) * fit.scale,
  };
}

export function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const secs = Math.floor(safe % 60).toString().padStart(2, '0');
  return `${minutes}:${secs}`;
}

export function percentage(value: number): string {
  return `${Math.round(value * 100)}%`;
}
