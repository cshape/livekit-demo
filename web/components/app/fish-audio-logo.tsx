import { cn } from '@/lib/shadcn/utils';

// Fish Audio waveform-fish mark, same bars as platform-web's nav icon.
const BARS = [
  { fill: '#7a7a7a', x: 297.1, y: 299.3, height: 21.4 },
  { fill: '#7a7a7a', x: 456.7, y: 249.9, height: 27.1 },
  { fill: '#7a7a7a', x: 424.7, y: 256.6, height: 47.4 },
  { fill: '#7a7a7a', x: 392.9, y: 264.3, height: 52.1 },
  { fill: '#7a7a7a', x: 360.9, y: 270.7, height: 51.6 },
  { fill: '#7a7a7a', x: 328.9, y: 276.4, height: 46 },
  { fill: '#000', x: 38.1, y: 200, height: 19.4 },
  { fill: '#000', x: 71, y: 202.7, height: 30.7 },
  { fill: '#000', x: 103.9, y: 198.4, height: 77.4 },
  { fill: '#000', x: 136.9, y: 192, height: 20 },
  { fill: '#000', x: 136.9, y: 245.4, height: 58.3 },
  { fill: '#000', x: 168.6, y: 235.1, height: 100.8 },
  { fill: '#000', x: 200.6, y: 222.4, height: 102.2 },
  { fill: '#000', x: 232.6, y: 204.1, height: 115.8 },
  { fill: '#000', x: 264.5, y: 190.2, height: 120.1 },
  { fill: '#000', x: 297.1, y: 181.9, height: 107.1 },
  { fill: '#000', x: 328.9, y: 177, height: 87.8 },
  { fill: '#000', x: 392.9, y: 178.1, height: 75.4 },
  { fill: '#000', x: 360.9, y: 175, height: 86.6 },
  { fill: '#000', x: 424.7, y: 185.2, height: 60.2 },
  { fill: '#000', x: 456.7, y: 204.1, height: 38 },
];

// The mark only spans y≈175–335 of the 512 viewBox, so crop the vertical
// whitespace to make it size predictably inside a header row.
export function FishAudioLogo({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 160 512 192"
      className={cn('dark:invert', className)}
      aria-label="Fish Audio"
      role="img"
    >
      {BARS.map((bar) => (
        <rect
          key={`${bar.x}-${bar.y}`}
          fill={bar.fill}
          x={bar.x}
          y={bar.y}
          width="16"
          height={bar.height}
          rx="8"
        />
      ))}
    </svg>
  );
}
