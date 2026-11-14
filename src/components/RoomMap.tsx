import { hexCorners, hexWorldCenter, worldToMap } from '../lib/map';
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

  const tableTopLeft = worldToMap({ x: 0, y: 0 }, tableSize, MAP);
  const tableBottomRight = worldToMap({ x: tableSize.width, y: tableSize.height }, tableSize, MAP);
  const tableWidth = tableBottomRight.x - tableTopLeft.x;
  const tableHeight = tableBottomRight.y - tableTopLeft.y;
  const hexScale = tableWidth / (tableSize.width + 1.6);

  return (
    <section className="room-map card" aria-label="Top-down room map">
      <div className="card-heading">
        <strong>Room map</strong>
        <span>heat follows speakers</span>
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
        <rect width={MAP.width} height={MAP.height} rx="14" fill="#10141B" />
        <rect
          x={tableTopLeft.x}
          y={tableTopLeft.y}
          width={tableWidth}
          height={tableHeight}
          rx="10"
          fill="#151A23"
          stroke="#3A4150"
        />
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
                key={`${hex.q}:${hex.r}`}
                points={points}
                fill={fill}
                opacity={hex.opacity}
                className={hex.ownerId === activeSpeakerId ? 'hot-hex' : undefined}
              />
            );
          })}
        </g>
        <g aria-label="People markers">
          {frames.map((frame) => {
            const person = people.find((item) => item.id === frame.id);
            if (!person) return null;
            const point = worldToMap(frame.mapPosition, tableSize, MAP);
            const active = frame.id === activeSpeakerId;
            const radius = 12 + (active ? level * 9 : 0);
            return (
              <g key={frame.id} opacity={frame.state === 'away' ? 0.4 : 1}>
                {active ? <circle cx={point.x} cy={point.y} r={radius} fill={person.color} opacity="0.22" filter="url(#speaker-glow)" /> : null}
                {frame.state === 'standing' ? <circle cx={point.x} cy={point.y} r="18" fill="none" stroke={person.color} strokeDasharray="4 4" /> : null}
                <foreignObject x={point.x - 10} y={point.y - 10} width="20" height="20">
                  <ShapeGlyph shape={person.shape} color={person.color} size={20} />
                </foreignObject>
                <text x={point.x} y={point.y + 29} textAnchor="middle" className="map-label">
                  {person.name}
                </text>
              </g>
            );
          })}
        </g>
        <g className="camera-marker" transform={`translate(${MAP.width / 2} ${MAP.height - 16})`}>
          <path d="M-58 0 0 -64 58 0" fill="#5B8DEF12" stroke="#5B8DEF55" />
          <rect x="-11" y="-9" width="22" height="14" rx="4" fill="#5B8DEF" />
          <circle r="3" fill="#10141B" />
        </g>
      </svg>
    </section>
  );
}
