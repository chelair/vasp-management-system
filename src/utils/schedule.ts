/**
 * 定时的"人话"表达 ↔ 后端调度表达式（v0.9.11）。
 *
 * 界面上只出现「每隔 30 分钟 / 每天 02:00 / 每周一 08:30 / 每月 15 日 09:00 /
 * 30 分钟后执行一次」这类说法，用户看不到也不需要写 cron 表达式；这里负责双向转换，
 * 并保留"高级：自定义表达式"入口给需要的人（解析不出来时按自定义处理）。
 */

export type ScheduleKind = 'minutes' | 'hours' | 'daily' | 'weekly' | 'monthly' | 'custom';

export interface ScheduleSpec {
  kind: ScheduleKind;
  /** minutes / hours：间隔数量 */
  every?: number;
  /** daily / weekly / monthly：小时与分钟 */
  hour?: number;
  minute?: number;
  /** weekly：0=周日 … 6=周六 */
  weekday?: number;
  /** monthly：几号（1-31） */
  day?: number;
  /** custom：原始表达式 */
  expression?: string;
}

export const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function pad(value: number): string {
  return String(Math.max(0, Math.floor(value))).padStart(2, '0');
}

/** "人话" → 调度表达式 */
export function scheduleToCron(spec: ScheduleSpec): string {
  const minute = Math.min(59, Math.max(0, Math.floor(spec.minute ?? 0)));
  const hour = Math.min(23, Math.max(0, Math.floor(spec.hour ?? 0)));
  switch (spec.kind) {
    case 'minutes': {
      const every = Math.min(59, Math.max(1, Math.floor(spec.every ?? 30)));
      return every === 1 ? '* * * * *' : `*/${every} * * * *`;
    }
    case 'hours': {
      const every = Math.min(23, Math.max(1, Math.floor(spec.every ?? 2)));
      return every === 1 ? `${minute} * * * *` : `${minute} */${every} * * *`;
    }
    case 'daily':
      return `${minute} ${hour} * * *`;
    case 'weekly':
      return `${minute} ${hour} * * ${Math.min(6, Math.max(0, Math.floor(spec.weekday ?? 1)))}`;
    case 'monthly':
      return `${minute} ${hour} ${Math.min(28, Math.max(1, Math.floor(spec.day ?? 1)))} * *`;
    default:
      return String(spec.expression ?? '').trim() || '0 2 * * *';
  }
}

/**
 * 调度表达式 → "人话"。
 *
 * 只认本文件生成的几种形态（界面里能选到的那些）；其它形态归到 custom，
 * 界面上显示"自定义"并保留原始表达式。
 */
export function cronToSchedule(expression: string | undefined): ScheduleSpec {
  const text = String(expression ?? '').trim();
  const parts = text.split(/\s+/);
  if (parts.length !== 5) return { kind: 'custom', expression: text };
  const [minute, hour, day, month, weekday] = parts;
  const isNumber = (value: string) => /^\d+$/.test(value);

  if (minute === '*' && hour === '*' && day === '*' && month === '*' && weekday === '*') {
    return { kind: 'minutes', every: 1 };
  }
  if (minute.startsWith('*/') && hour === '*' && day === '*' && month === '*' && weekday === '*') {
    const every = Number(minute.slice(2));
    if (Number.isFinite(every) && every >= 1 && every <= 59) return { kind: 'minutes', every };
  }
  if (isNumber(minute) && hour.startsWith('*/') && day === '*' && month === '*' && weekday === '*') {
    const every = Number(hour.slice(2));
    if (Number.isFinite(every) && every >= 1 && every <= 23) {
      return { kind: 'hours', every, minute: Number(minute) };
    }
  }
  if (isNumber(minute) && hour === '*' && day === '*' && month === '*' && weekday === '*') {
    return { kind: 'hours', every: 1, minute: Number(minute) };
  }
  if (isNumber(minute) && isNumber(hour)) {
    if (day === '*' && month === '*' && weekday === '*') {
      return { kind: 'daily', hour: Number(hour), minute: Number(minute) };
    }
    if (day === '*' && month === '*' && isNumber(weekday) && Number(weekday) <= 6) {
      return { kind: 'weekly', weekday: Number(weekday), hour: Number(hour), minute: Number(minute) };
    }
    if (isNumber(day) && month === '*' && weekday === '*') {
      return { kind: 'monthly', day: Number(day), hour: Number(hour), minute: Number(minute) };
    }
  }
  return { kind: 'custom', expression: text };
}

/** "人话"描述（列表与弹窗里显示这个，不显示表达式） */
export function describeSchedule(spec: ScheduleSpec): string {
  switch (spec.kind) {
    case 'minutes':
      return (spec.every ?? 1) === 1 ? '每分钟' : `每隔 ${spec.every} 分钟`;
    case 'hours':
      return (spec.every ?? 1) === 1 ? '每小时' : `每隔 ${spec.every} 小时`;
    case 'daily':
      return `每天 ${pad(spec.hour ?? 0)}:${pad(spec.minute ?? 0)}`;
    case 'weekly':
      return `${WEEKDAY_LABELS[Math.min(6, Math.max(0, spec.weekday ?? 0))]} ${pad(spec.hour ?? 0)}:${pad(
        spec.minute ?? 0,
      )}`;
    case 'monthly':
      return `每月 ${spec.day ?? 1} 日 ${pad(spec.hour ?? 0)}:${pad(spec.minute ?? 0)}`;
    default:
      return `自定义：${spec.expression || '（未填写）'}`;
  }
}

/** 一次性延迟的描述 */
export function describeDelay(seconds: number | null | undefined): string {
  const total = Math.max(1, Math.round(Number(seconds ?? 0)));
  if (total % 3600 === 0) return `${total / 3600} 小时后执行一次`;
  if (total % 60 === 0) return `${total / 60} 分钟后执行一次`;
  return `${total} 秒后执行一次`;
}
