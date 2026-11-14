import { useMemo } from 'react';
import type { SpeakerShape } from '../contract';
import { generateHexGrid, hexCorners, hexWorldCenter, worldToMap } from '../lib/map';
import { useRoundtableStore } from '../state/store';

const MAP = { width: 352, height: 218 };

function shapePath(shape: SpeakerShape, cx: number, cy: number, size: number): string {
  const r = size / 2;
  if (shape === 'square') return `M${cx - r},${cy - r}h${size}v${size}h${-size}Z`;
  if (shape === 'diamond') return `M${cx},${cy - r * 1.15}L${cx + r * 1.15},${cy}L${cx},${cy + r * 1.15}L${cx - r * 1.15},${cy}Z`;
  if (shape === 'triangle') return `M${cx},${cy - r * 1.1}L${cx + r * 1.1},${cy + r * 0.85}L${cx - r * 1.1},${cy + r * 0.85}Z`;
  return `M${cx - r},${cy}a${r},${r} 0 1,0 ${size},0a${r},${r} 0 1,0 ${-size},0Z`;
}

export function RoomMap() {
  const tableSize = useRoundtableStore((state) => state.tableSize);
  const hexes = useRoundtableStore((state) => state.mapHexes);
  const people = useRoundtableStore((state) => state.people);
  const frames = useRoundtableStore((state) => state.frames);
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);
  const level = useRoundtableStore((state) => state.level);

  const baseCells = useMemo(() => generateHexGrid(tableSize), [tableSize]);
  const fallbackPositions = [
    { id: 'p1', x: 0.42, y: -0.45 },
    { id: 'p2', x: 0.9, y: -0.45 },
    { id: 'p3', x: 1.5, y: -0.45 },
  ];
  const markerPositions = frames.length
    ? frames.map((frame) => ({ id: frame.id, ...frame.mapPosition }))
    : fallbackPositions;

  const tableTopLeft = worldToMap({ x: 0, y: 0 }, tableSize, MAP);
  const tableBottomRight = worldToMap({ x: tableSize.width, y: tableSize.height }, tableSize, MAP);
  const tableWidth = tableBottomRight.x - tableTopLeft.x;
  const tableHeight = tableBottomRight.y - tableTopLeft.y;
  const hexScale = tableWidth / tableSize.width;
  const heatByCell = new Map(hexes.map((hex) => [`${hex.q}:${hex.r}`, hex]));

  return (
    <section className="room-map card" aria-label="Top-down room map">
      <div className="card-heading map-heading">
        <strong>Room map</strong>
        <div className="segmented-control" aria-label="Heat window" title="Heat accumulates over the whole session">
          <span>60 s</span>
          <span className="active">All</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${MAP.width} ${MAP.height}`} role="img" aria-label="Map of speakers around the table">
        <defs>
          <filter id="speaker-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
        </defs>
        <g aria-hidden="true">
          {baseCells.map((cell) => {
            const key = `${cell.q}:${cell.r}`;
            if (heatByCell.has(key)) return null;
            const world = hexWorldCenter(cell);
            const center = worldToMap(world, tableSize, MAP);
            const nearest = markerPositions.reduce((best, current) => {
              const bestDistance = Math.hypot(best.x - world.x, best.y - world.y);
              const currentDistance = Math.hypot(current.x - world.x, current.y - world.y);
              return currentDistance < bestDistance ? current : best;
            }, markerPositions[0]);
            const person = people.find((item) => item.id === nearest.id);
            const points = hexCorners(center, 0.1 * hexScale * 0.88)
              .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
              .join(' ');
            return <polygon key={key} points={points} fill={person?.color ?? '#6B7380'} opacity="0.13" />;
          })}
        </g>
        <g>
          {hexes.map((hex) => {
            const world = hexWorldCenter(hex);
            const center = worldToMap(world, tableSize, MAP);
            const person = people.find((item) => item.id === hex.ownerId);
            const fill = hex.contested ? '#8a91a0' : person?.color ?? '#2A303C';
            const points = hexCorners(center, 0.1 * hexScale * 0.9)
              .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
              .join(' ');
            return (
              <polygon
                key={`heat-${hex.q}:${hex.r}`}
                points={points}
                fill={fill}
                opacity={Math.max(0.13, hex.opacity)}
                style={{ transition: 'opacity 300ms linear', color: fill }}
                className={hex.ownerId === activeSpeakerId && hex.opacity > 0.5 ? 'hot-hex' : undefined}
              />
            );
          })}
        </g>
        <rect
          x={tableTopLeft.x}
          y={tableTopLeft.y}
          width={tableWidth}
          height={tableHeight}
          rx="6"
          fill="#141923"
          stroke="#3a4150"
          strokeWidth="1.2"
          strokeDasharray="4 3"
        />
        <g aria-label="Camera">
          <path
            d={`M${MAP.width / 2 - 34},${MAP.height - 2} L${MAP.width / 2},${MAP.height - 26} L${MAP.width / 2 + 34},${MAP.height - 2}`}
            fill="rgba(154,161,173,0.08)"
            stroke="rgba(154,161,173,0.25)"
            strokeWidth="1"
          />
          <rect x={MAP.width / 2 - 7} y={MAP.height - 12} width="14" height="9" rx="2" fill="#6b7380" />
          <rect x={MAP.width / 2 - 3} y={MAP.height - 15} width="6" height="3" rx="1" fill="#6b7380" />
        </g>
        <g aria-label="People markers">
          {markerPositions.map((marker) => {
            const person = people.find((item) => item.id === marker.id);
            const frame = frames.find((item) => item.id === marker.id);
            if (!person) return null;
            const point = worldToMap({ x: marker.x, y: marker.y }, tableSize, MAP);
            const active = marker.id === activeSpeakerId;
            const standing = frame?.state === 'standing';
            return (
              <g key={marker.id} opacity={frame?.state === 'away' ? 0.4 : 1} style={{ transition: 'opacity 200ms ease' }}>
                {active ? (
                  <circle cx={point.x} cy={point.y} r={16 + level * 60} fill={person.color} opacity="0.35" filter="url(#speaker-glow)" />
                ) : null}
                {standing ? <circle cx={point.x} cy={point.y} r="15" fill="none" stroke={person.color} strokeWidth="1" strokeDasharray="3 3" /> : null}
                <circle cx={point.x} cy={point.y} r="12" fill="#10141b" opacity="0.92" />
                <path d={shapePath(person.shape, point.x, point.y, 15)} fill={active ? '#10141b' : person.color} stroke={person.color} strokeWidth={active ? 3 : 1.5} strokeLinejoin="round" />
              </g>
            );
          })}
        </g>
      </svg>
      <div className="map-footer">Color = who talks here · brightness = how much</div>
    </section>
  );
}
