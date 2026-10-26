import type { ReactNode } from 'react';

const ACCENTS = {
  blue: { color: '#4A7BDD', bg: '#EAF1FF' },
  teal: { color: '#1FA58A', bg: '#E5F7F1' },
  green: { color: '#2FA36B', bg: '#E9F8EF' },
  orange: { color: '#D98A2B', bg: '#FFF3E2' },
  red: { color: '#D9535B', bg: '#FDECED' },
} as const;

interface Props {
  label: string;
  value: number | string;
  icon: ReactNode;
  accent?: keyof typeof ACCENTS;
  trend?: string;
  delay?: number;
  /** 点击回调（传值时卡片变为可点击，用于跳转/展开） */
  onClick?: () => void;
  /** 高亮态（如正在展开运行中任务列表） */
  active?: boolean;
}

export default function StatCard({
  label,
  value,
  icon,
  accent = 'blue',
  trend,
  delay = 0,
  onClick,
  active = false,
}: Props) {
  const a = ACCENTS[accent];
  return (
    <div
      className={`stat-card${onClick ? ' stat-card--clickable' : ''}${active ? ' stat-card--active' : ''}`}
      style={{ animationDelay: `${delay}s` }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="stat-card__icon" style={{ background: a.bg, color: a.color }}>
        {icon}
      </div>
      <div>
        <div className="stat-card__label">{label}</div>
        <div className="stat-card__value">{value}</div>
        {trend && <div className="stat-card__trend">{trend}</div>}
      </div>
    </div>
  );
}
