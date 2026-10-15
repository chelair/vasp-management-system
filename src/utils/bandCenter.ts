/**
 * 带中心（band center）：对某条态密度曲线在给定能量区间内做加权平均。
 *
 *     center = ∫ E·DOS(E) dE / ∫ DOS(E) dE
 *
 * 口径（2026-10-15 用户确认）：
 * - **含未占据态** —— 区间跨过 E_F 时照样积分。d 带中心本来就是按"占据 + 未占据"的
 *   加权平均来表征吸附活性的（只看占据态会丢掉反键态那一半的信息）；
 * - **自旋 up / down 各自算**（每条曲线一个值，Fe d↑ 与 d↓ 的差就是磁学信息）；
 * - **相对 E_F**（与前端横轴一致，调用方传入的 xs 已经是 E − E_F）。
 *
 * 实现：一维梯形积分，区间边界按线性插值**裁剪**（曲线边界常常落在区间外，
 * 不裁剪会把整段算进来）。区间内没有态（分母≈0）返回 `null`。
 */

export interface BandCenterInput {
  /** 能量（相对 E_F），与 values 一一对应、单调递增 */
  xs: number[];
  /** 态密度值 */
  values: number[];
  /** 积分区间（相对 E_F） */
  min: number;
  max: number;
}

export function bandCenter({ xs, values, min, max }: BandCenterInput): number | null {
  const n = Math.min(xs.length, values.length);
  if (n < 2 || !(max > min)) return null;
  let num = 0;
  let den = 0;
  for (let i = 1; i < n; i += 1) {
    const x0 = xs[i - 1];
    const x1 = xs[i];
    const v0 = values[i - 1];
    const v1 = values[i];
    if (!Number.isFinite(x0) || !Number.isFinite(x1) || x1 === x0) continue;
    const lo = Math.max(x0, min);
    const hi = Math.min(x1, max);
    if (hi <= lo) continue;
    const span = x1 - x0;
    const vLo = v0 + ((v1 - v0) * (lo - x0)) / span;
    const vHi = v0 + ((v1 - v0) * (hi - x0)) / span;
    const weight = ((vLo + vHi) / 2) * (hi - lo);
    num += ((lo + hi) / 2) * weight;
    den += weight;
  }
  if (Math.abs(den) < 1e-12) return null;
  return num / den;
}

/** 批量：给多条曲线各算一个带中心（键 = 曲线 id） */
export function bandCenters(
  curves: { id: string; xs: number[]; values: number[] }[],
  min: number,
  max: number,
): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const curve of curves) {
    out[curve.id] = bandCenter({ xs: curve.xs, values: curve.values, min, max });
  }
  return out;
}

/** 展示用格式化：`−1.87`（保留两位；null 显示 —；整数不带多余 0） */
export function formatCenter(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const text = value.toFixed(2);
  return text === '-0.00' ? '0.00' : text;
}
