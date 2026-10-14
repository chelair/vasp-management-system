/**
 * Bader 电荷着色（巡检详情页 Bader 标签的结构预览，v0.9.55）。
 *
 * 口径（与受力那套 `forceColor.ts` 平行）：
 * - 优先按**净电荷**（Δq = ZVAL − Bader 电荷）着色：**红 = 失电子（Δq > 0）**，
 *   **蓝 = 得电子（Δq < 0）**，接近 0 用灰，一眼分得出得失电子方向；
 * - 没有 ZVAL（算不出净电荷）时退化成按 **Bader 电荷**（体积内电子数）着色，
 *   偏离该结构平均值越多颜色越深（并给出说明，避免误读成净电荷）；
 * - 用对称尺度：上限 = max(|Δq|)（有下限 0.5 e，避免极小的电荷被放大成大红大蓝）。
 */

export const CHARGE_POS = '#D9535B'; // 失电子（正）
export const CHARGE_NEG = '#3E7CB1'; // 得电子（负）
export const CHARGE_ZERO = '#C3CBD6'; // 接近 0

export interface ChargeColorScale {
  /** 着色用的"满格"绝对值（e） */
  extent: number;
  /** 着色依据：净电荷 / 原始 Bader 电荷 */
  basis: 'net' | 'raw';
  /** 说明文字（给用户看） */
  note: string;
  colorFor: (value: number) => string;
}

function parseHex(hex: string): [number, number, number] {
  const raw = hex.replace('#', '');
  const n = Number.parseInt(raw, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(a: string, b: string, k: number): string {
  const [r1, g1, b1] = parseHex(a);
  const [r2, g2, b2] = parseHex(b);
  const t = Math.min(1, Math.max(0, k));
  const ch = (x: number, y: number) => Math.round(x + (y - x) * t);
  const hex = (v: number) => v.toString(16).padStart(2, '0');
  return `#${hex(ch(r1, r2))}${hex(ch(g1, g2))}${hex(ch(b1, b2))}`;
}

export function makeChargeScale(values: number[], basis: 'net' | 'raw'): ChargeColorScale {
  const absMax = values.reduce((acc, v) => Math.max(acc, Math.abs(v)), 0);
  const extent = Math.max(absMax, 0.5);
  const colorFor = (value: number) => {
    const k = Math.abs(value) / extent;
    if (k < 0.05) return CHARGE_ZERO;
    return value >= 0 ? mix(CHARGE_ZERO, CHARGE_POS, k) : mix(CHARGE_ZERO, CHARGE_NEG, k);
  };
  const note =
    basis === 'net'
      ? `红 = 失电子（Δq > 0）· 蓝 = 得电子（Δq < 0）· 满格 ±${extent.toFixed(2)} e`
      : `按 Bader 电荷着色（该结构没有 ZVAL，算不出净电荷）：紫红 = 偏离平均更大 · 灰 = 接近平均`;
  return { extent, basis, note, colorFor };
}

/** 逐原子颜色（键 = CIF 原子下标 0 起）：`values[i]` 对应第 i 个原子 */
export function buildChargeColors(values: (number | null)[]): {
  colors: Record<number, string> | null;
  scale: ChargeColorScale | null;
} {
  const known = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (!known.length) return { colors: null, scale: null };
  const scale = makeChargeScale(known, 'net');
  const colors: Record<number, string> = {};
  values.forEach((value, index) => {
    if (value != null && Number.isFinite(value)) colors[index] = scale.colorFor(value);
  });
  return { colors, scale };
}
