import { useMemo } from 'react';
import { generateHexGrid, hexCorners, hexWorldCenter, worldToMap } from '../lib/map';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

const MAP = { width: 352, height: 232 };

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

  return (
    <section className="room-map card" aria-label="Top-down room map">
      <div className="card-heading map-heading">
        <strong>Room map</strong>
        <div className="segmented-control" aria-label="Heat window">
          <span className="active">60 s</span>
          <span>All</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${MAP.width} ${MAP.height}`} role="img" aria-label="Map of speakers around the table">
        <defs>
          <filter id="speaker-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <rect width={MAP.width} height={MAP.height} rx="14" fill="#111620" />
        <g>
          {baseCells.map((cell) => {
            const world = hexWorldCenter(cell);
            const center = worldToMap(world, tableSize, MAP);
            const nearest = markerPositions.reduce((best, current) => {
              const bestDistance = Math.hypot(best.x - world.x, best.y - world.y);
              const currentDistance = Math.hypot(current.x - world.x, current.y - world.y);
              return currentDistance < bestDistance ? current : best;
            }, markerPositions[0]);
            const person = people.find((item) => item.id === nearest.id);
            const points = hexCorners(center, 0.1 * hexScale * 0.86)
              .map((point) => `${point.x},${point.y}`)
              .join(' ');
            return <polygon key={`${cell.q}:${cell.r}`} points={points} fill={person?.color ?? '#6B7380'} opacity="0.18" />;
          })}
        </g>
        <g>
          {hexes.map((hex) => {
            const world = hexWorldCenter(hex);
            const center = worldToMap(world, tableSize, MAP);
            const person = people.find((item) => item.id === hex.ownerId);
            const fill = hex.contested ? '#6B7380' : person?.color ?? '#2A303C';
            const points = hexCorners(center, 0.1 * hexScale * 0.9)
              .map((point) => `${point.x},${point.y}`)
              .join(' ');
            return (
              <polygon
                key={`heat-${hex.q}:${hex.r}`}
                points={points}
                fill={fill}
                opacity={Math.max(0.12, hex.opacity)}
                className={hex.ownerId === activeSpeakerId ? 'hot-hex' : undefined}
              />
            );
          })}
        </g>
        <rect
          x={tableTopLeft.x}
          y={tableTopLeft.y}
          width={tableWidth}
          height={tableHeight}
          rx="8"
          fill="#171C25"
          stroke="#2A303C"
          strokeWidth="1.5"
        />
        <g aria-label="People markers">
          {markerPositions.map((marker) => {
            const person = people.find((item) => item.id === marker.id);
            const frame = frames.find((item) => item.id === marker.id);
            if (!person) return null;
            const point = worldToMap({ x: marker.x, y: marker.y }, tableSize, MAP);
            const active = marker.id === activeSpeakerId;
            const radius = 14 + (active ? level * 8 : 0);
            return (
              <g key={marker.id} opacity={frame?.state === 'away' ? 0.4 : 1}>
                {active ? <circle cx={point.x} cy={point.y} r={radius} fill={person.color} opacity="0.28" filter="url(#speaker-glow)" /> : null}
                <circle cx={point.x} cy={point.y} r="13" fill="#10141B" stroke={person.color} strokeWidth="2" />
                <foreignObject x={point.x - 8} y={point.y - 8} width="16" height="16">
                  <ShapeGlyph shape={person.shape} color={person.color} size={16} />
                </foreignObject>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="map-footer">Color = who talks here · brightness = how much</div>
    </section>
  );
}
