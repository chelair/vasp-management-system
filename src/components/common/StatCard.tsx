import { motion } from 'framer-motion';
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
}

export default function StatCard({
  label,
  value,
  icon,
  accent = 'blue',
  trend,
  delay = 0,
}: Props) {
  const a = ACCENTS[accent];
  return (
    <motion.div
      className="stat-card"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: 'easeOut' }}
      whileHover={{ y: -4, boxShadow: '0 12px 30px rgba(35, 48, 67, 0.12)' }}
    >
      <div className="stat-card__icon" style={{ background: a.bg, color: a.color }}>
        {icon}
      </div>
      <div>
        <div className="stat-card__label">{label}</div>
        <div className="stat-card__value">{value}</div>
        {trend && <div className="stat-card__trend">{trend}</div>}
      </div>
    </motion.div>
  );
}
