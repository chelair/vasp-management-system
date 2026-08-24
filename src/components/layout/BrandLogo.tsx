interface Props {
  size?: number;
}

export default function BrandLogo({ size = 36 }: Props) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="brandGradient" x1="0" y1="0" x2="48" y2="48">
          <stop stopColor="#5B8DEF" />
          <stop offset="1" stopColor="#67C6B0" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="44" height="44" rx="12" fill="url(#brandGradient)" />
      <circle cx="24" cy="24" r="6" fill="#fff" />
      <ellipse
        cx="24"
        cy="24"
        rx="16"
        ry="7"
        stroke="#fff"
        strokeWidth="2.5"
        fill="none"
        transform="rotate(-25 24 24)"
        opacity="0.95"
      />
      <ellipse
        cx="24"
        cy="24"
        rx="16"
        ry="7"
        stroke="#fff"
        strokeWidth="2.5"
        fill="none"
        transform="rotate(35 24 24)"
        opacity="0.6"
      />
    </svg>
  );
}
