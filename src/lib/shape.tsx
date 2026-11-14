import type { SpeakerShape } from '../contract';

export function ShapeGlyph({
  shape,
  color,
  size = 14,
  className,
}: {
  shape: SpeakerShape;
  color: string;
  size?: number;
  className?: string;
}) {
  const common = { width: size, height: size, viewBox: '0 0 20 20', className, 'aria-hidden': true };
  if (shape === 'square') {
    return (
      <svg {...common}>
        <rect x="3" y="3" width="14" height="14" rx="3" fill={color} />
      </svg>
    );
  }
  if (shape === 'diamond') {
    return (
      <svg {...common}>
        <path d="M10 2 18 10 10 18 2 10Z" fill={color} />
      </svg>
    );
  }
  if (shape === 'triangle') {
    return (
      <svg {...common}>
        <path d="M10 2 18 17H2Z" fill={color} />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="10" cy="10" r="8" fill={color} />
    </svg>
  );
}
