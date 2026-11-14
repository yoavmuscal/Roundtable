import { useEffect, useMemo, useRef, useState } from 'react';
import type { Point } from '../contract';
import {
  applyHomography,
  homographyFromPoints,
  invert3x3,
  tableGridLines,
  validateCalibration,
} from '../lib/geometry';
import { defaultSeats } from '../lib/people';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

const DEMO_CORNERS: [Point, Point, Point, Point] = [
  { x: 0.22, y: 0.7 },
  { x: 0.78, y: 0.7 },
  { x: 0.97, y: 0.98 },
  { x: 0.03, y: 0.98 },
];

const TABLE_CORNERS: Point[] = [
  { x: 0, y: 0 },
  { x: 1.8, y: 0 },
  { x: 1.8, y: 0.9 },
  { x: 0, y: 0.9 },
];

function eventPoint(svg: SVGSVGElement, event: React.PointerEvent): Point {
  const rect = svg.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) / rect.width,
    y: (event.clientY - rect.top) / rect.height,
  };
}

export function SetupScreen() {
  const people = useRoundtableStore((state) => state.people);
  const calibration = useRoundtableStore((state) => state.calibration);
  const setPhase = useRoundtableStore((state) => state.setPhase);
  const [corners, setCorners] = useState<Point[]>(DEMO_CORNERS);
  const [center, setCenter] = useState<Point>({ x: 0.5, y: 0.84 });
  const [clickingCenter, setClickingCenter] = useState(false);
  const [seats, setSeats] = useState<Record<string, Point>>(() => defaultSeats(people));
  // Seats follow the enrolled people: new people get a default seat, removed people lose theirs.
  useEffect(() => {
    setSeats((current) => {
      const defaults = defaultSeats(people);
      const next: Record<string, Point> = {};
      people.forEach((person) => {
        next[person.id] = current[person.id] ?? defaults[person.id];
      });
      return next;
    });
  }, [people]);
  const [draggingSeat, setDraggingSeat] = useState<string>();
  const svgRef = useRef<SVGSVGElement>(null);

  const imageToTable = useMemo(() => {
    if (corners.length !== 4) return null;
    try {
      return homographyFromPoints(corners, TABLE_CORNERS);
    } catch {
      return null;
    }
  }, [corners]);

  const tableToImage = useMemo(() => (imageToTable ? invert3x3(imageToTable) : null), [imageToTable]);
  const validationError =
    corners.length === 4
      ? validateCalibration({ corners: corners as [Point, Point, Point, Point], tableSize: { width: 1.8, height: 0.9 }, center })
      : null;
  const gridLines = useMemo(() => {
    if (!tableToImage) return [];
    return tableGridLines({ width: 1.8, height: 0.9 }).map((line) =>
      line.map((point) => applyHomography(tableToImage, point)),
    );
  }, [tableToImage]);

  const runChecks = () => {
    if (corners.length !== 4 || validationError) return;
    roundtableClient.calibrate({
      corners: corners as [Point, Point, Point, Point],
      tableSize: { width: 1.8, height: 0.9 },
      center,
    });
  };

  const handlePointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!svgRef.current || draggingSeat) return;
    const point = eventPoint(svgRef.current, event);
    if (clickingCenter) {
      setCenter(point);
      setClickingCenter(false);
      return;
    }
    if (corners.length < 4) setCorners([...corners, point]);
  };

  const updateSeat = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!draggingSeat || !svgRef.current || !imageToTable) return;
    const table = applyHomography(imageToTable, eventPoint(svgRef.current, event));
    const next = {
      x: Math.min(2.1, Math.max(-0.3, table.x)),
      y: Math.min(1.2, Math.max(-0.7, table.y)),
    };
    setSeats((current) => ({ ...current, [draggingSeat]: next }));
  };

  return (
    <main className="setup-screen screen-panel">
      <section className="setup-copy">
        <p className="eyebrow">Step 1 · Calibrate the table</p>
        <h1>Make captions land on people, not just the screen.</h1>
        <p>
          Click the taped corners in order: far-left, far-right, near-right, near-left. Then repeat
          Check B by clicking the center tape. Drag seat markers if the numbered dots do not match.
        </p>
        <ol className="check-list">
          <li className={corners.length === 4 && !validationError ? 'done' : ''}>Four corners form a valid table</li>
          <li className={calibration?.ok ? 'done' : ''}>25 cm grid lies flat on the tabletop</li>
          <li className={calibration?.ok ? 'done' : ''}>Center click matches the projected table center</li>
        </ol>
        <div className="button-row">
          <button type="button" onClick={() => { setCorners(DEMO_CORNERS); setCenter({ x: 0.5, y: 0.84 }); }}>
            Use demo corners
          </button>
          <button type="button" onClick={() => setCorners([])}>Clear clicks</button>
          <button type="button" onClick={() => setClickingCenter(true)} aria-pressed={clickingCenter}>
            Click center tape
          </button>
          <button type="button" className="primary" onClick={runChecks} disabled={corners.length !== 4 || Boolean(validationError)}>
            Run visual checks
          </button>
          <button type="button" className="primary" onClick={() => {
              roundtableClient.control('confirm-seats', JSON.stringify(people));
              setPhase('enroll');
            }} disabled={Boolean(validationError)}>
            Continue to enrollment
          </button>
        </div>
        {validationError ? <p className="error-message">{validationError}</p> : null}
        {calibration ? (
          <p className={calibration.ok ? 'success-message' : 'error-message'} role="status">
            {calibration.message}
            {calibration.centerError !== undefined ? ` Center error: ${(calibration.centerError * 100).toFixed(1)}%.` : ''}
          </p>
        ) : null}
      </section>

      <section className="setup-stage" aria-label="Calibration camera preview">
        <svg
          ref={svgRef}
          viewBox="0 0 1000 562"
          onPointerDown={handlePointerDown}
          onPointerMove={updateSeat}
          onPointerUp={() => {
            if (draggingSeat) roundtableClient.seatDrag(draggingSeat, seats[draggingSeat]);
            setDraggingSeat(undefined);
          }}
          role="application"
          aria-label="Click table corners and drag seats"
        >
          <rect width="1000" height="562" fill="#0B0E13" />
          <g opacity="0.45">
            {Array.from({ length: 30 }, (_, index) => (
              <line key={`v-${index}`} x1={index * 40} y1="0" x2={index * 40} y2="562" stroke="#1E242E" />
            ))}
            {Array.from({ length: 17 }, (_, index) => (
              <line key={`h-${index}`} x1="0" y1={index * 40} x2="1000" y2={index * 40} stroke="#1E242E" />
            ))}
          </g>
          {corners.length > 1 ? (
            <polygon
              points={corners.map((point) => `${point.x * 1000},${point.y * 562}`).join(' ')}
              fill="#5B8DEF10"
              stroke="#5B8DEF"
              strokeWidth="3"
            />
          ) : null}
          {gridLines.map((line, index) => (
            <polyline
              key={index}
              points={line.map((point) => `${point.x * 1000},${point.y * 562}`).join(' ')}
              fill="none"
              stroke="#5B8DEF55"
              strokeWidth="1.5"
            />
          ))}
          {corners.map((point, index) => (
            <g key={`${point.x}-${point.y}-${index}`}>
              <circle cx={point.x * 1000} cy={point.y * 562} r="13" fill="#5B8DEF" />
              <text x={point.x * 1000} y={point.y * 562 + 5} textAnchor="middle" className="calibration-number">
                {index + 1}
              </text>
            </g>
          ))}
          <circle cx={center.x * 1000} cy={center.y * 562} r="10" fill="#F5A524" />
          {tableToImage
            ? people.map((person) => {
                const seat = seats[person.id];
                if (!seat) return null;
                const image = applyHomography(tableToImage, seat);
                return (
                  <g
                    key={person.id}
                    transform={`translate(${image.x * 1000} ${image.y * 562})`}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      setDraggingSeat(person.id);
                    }}
                    className="seat-marker"
                  >
                    <circle r="23" fill={person.color} opacity="0.22" />
                    <foreignObject x="-13" y="-13" width="26" height="26">
                      <ShapeGlyph shape={person.shape} color={person.color} size={26} />
                    </foreignObject>
                    <text y="43" textAnchor="middle">{person.name}</text>
                  </g>
                );
              })
            : null}
        </svg>
      </section>
    </main>
  );
}
