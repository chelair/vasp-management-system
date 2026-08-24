interface Props {
  value: number;
  showText?: boolean;
}

export default function ProgressBar({ value, showText = false }: Props) {
  const percent = Math.min(100, Math.max(0, value));
  return (
    <div className="progress-wrap">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      {showText && <span className="progress-text">{percent}%</span>}
    </div>
  );
}
