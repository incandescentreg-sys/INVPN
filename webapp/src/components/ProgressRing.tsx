/** Circular progress showing how much of the paid period is left. */
export function ProgressRing({
  value,
  caption,
  number,
  size = 92,
  stroke = 8,
}: {
  /** 0..100 */
  value: number
  caption?: string
  number?: string
  size?: number
  stroke?: number
}) {
  const clamped = Math.max(0, Math.min(100, value))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const dash = (clamped / 100) * circumference

  return (
    <div className="ring" style={{ ['--size' as string]: `${size}px` }}>
      <svg
        className="ring__svg"
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        aria-hidden="true"
      >
        <circle className="ring__track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} />
        <circle
          className="ring__value"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          strokeDasharray={`${dash} ${circumference - dash}`}
        />
      </svg>
      <div className="ring__label">
        {number && <span className="ring__number">{number}</span>}
        {caption && <span className="ring__caption">{caption}</span>}
      </div>
    </div>
  )
}
