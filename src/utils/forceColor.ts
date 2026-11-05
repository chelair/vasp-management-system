/**
 * 原子受力着色（巡检详情页 3D 视图「查看原子受力」，v0.9.41）。
 *
 * 口径与后端判定一致：每个原子取**合力模长** `sqrt(Fx²+Fy²+Fz²)`，
 * 固定原子（Selective dynamics 任一方向 F）显示灰色，不参与色标上限统计。
 * 其余原子按 0 → 当前结构最大受力映射为绿 → 黄 → 红；最大非零受力始终为红色。
 * 颜色表示相对受力大小，收敛结论仍由原有阈值判定。
 */
import type { AtomicForces } from '../api/inspections';

export const FORCE_OK = '#2FA36B';
export const FORCE_MID = '#E8B33A';
export const FORCE_BAD = '#D9535B';
export const FORCE_FIXED = '#9AA7B8';

export interface ForceColorScale {
  /** 渐变上限（eV/Å） */
  upper: number;
  colorFor: (fmax: number, fixed?: boolean) => string;
}

function mix(a: string, b: string, k: number): string {
  const parse = (hex: string) => {
    const raw = hex.replace('#', '');
    const n = Number.parseInt(raw, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  const t = Math.min(1, Math.max(0, k));
  const ch = (x: number, y: number) => Math.round(x + (y - x) * t);
  const hex = (v: number) => v.toString(16).padStart(2, '0');
  return `#${hex(ch(r1, r2))}${hex(ch(g1, g2))}${hex(ch(b1, b2))}`;
}

export function makeForceScale(observedMax: number): ForceColorScale {
  const upper = observedMax;
  const colorFor = (fmax: number, fixed = false) => {
    if (fixed) return FORCE_FIXED;
    if (upper <= 0) return FORCE_OK;
    const k = Math.min(1, Math.max(0, fmax / upper));
    return k <= 0.5
      ? mix(FORCE_OK, FORCE_MID, k * 2)
      : mix(FORCE_MID, FORCE_BAD, (k - 0.5) * 2);
  };
  return { upper, colorFor };
}

export interface AtomColors {
  /** 逐原子颜色（键 = CIF 原子下标） */
  colors: Record<number, string> | null;
  scale: ForceColorScale | null;
  /** 受力表元素序列与当前 CIF 不一致（结构过期/换过 POSCAR）→ 不着色 */
  mismatch: boolean;
  /** 说明文字（给用户看） */
  note: string | null;
}

/**
 * 由受力数据算出逐原子颜色；与 CIF 原子序列不一致时**不着色**并给出原因。
 */
export function buildAtomColors(
  data: AtomicForces | null,
  cifElements: string[] | null,
): AtomColors {
  if (!data || !data.atoms.length) {
    return { colors: null, scale: null, mismatch: false, note: null };
  }
  const backendElements = data.elements;
  if (backendElements && cifElements && backendElements.length === cifElements.length) {
    const same = backendElements.every(
      (el, i) => String(el).toUpperCase() === String(cifElements[i]).toUpperCase(),
    );
    if (!same) {
      return {
        colors: null,
        scale: null,
        mismatch: true,
        note: '受力表的元素顺序与当前结构不一致（结构可能已更新），暂不着色',
      };
    }
  } else if (cifElements && data.atoms.length !== cifElements.length) {
    return {
      colors: null,
      scale: null,
      mismatch: true,
      note: `受力原子数（${data.atoms.length}）与当前结构原子数（${cifElements.length}）不一致，暂不着色`,
    };
  }
  const observedMax = data.atoms.reduce((m, a) => a.fixed ? m : Math.max(m, a.fmax), 0);
  const scale = makeForceScale(observedMax);
  const colors: Record<number, string> = {};
  data.atoms.forEach((a) => {
    colors[a.index] = scale.colorFor(a.fmax, a.fixed);
  });
  return { colors, scale, mismatch: false, note: null };
}
