/**
 * 原子受力着色（巡检详情页 3D 视图「查看原子受力」，v0.9.41）。
 *
 * 口径与后端判定一致：每个原子取**最大力分量** `max(|Fx|,|Fy|,|Fz|)`（VASP 的力判据就是分量），
 * 阈值取 INCAR 的 `|EDIFFG|`（缺失时后端已退回 registry 0.02）。着色规则（收敛与未收敛**分开**）：
 * - 固定原子（Selective dynamics 任一方向 F）→ 灰色，不参与收敛判据；
 * - `≤ 阈值` → 绿色（达标，纯色不平滑）；
 * - `> 阈值` → **黄→红** 线性渐变（越大越红），不经过绿色，一眼分得出"哪些还没收敛"；
 *   渐变上限取 `max(阈值×4, 该结构实测最大)`，保证最红的确实是受力最大的那个原子。
 */
import type { AtomicForces } from '../api/inspections';

export const FORCE_OK = '#2FA36B';
export const FORCE_MID = '#E8B33A';
export const FORCE_BAD = '#D9535B';
export const FORCE_FIXED = '#9AA7B8';

export interface ForceColorScale {
  /** 达标阈值（eV/Å） */
  threshold: number;
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

export function makeForceScale(threshold: number, observedMax: number): ForceColorScale {
  const t = threshold > 0 ? threshold : 0.02;
  const upper = Math.max(t * 4, observedMax > 0 ? observedMax : t * 4);
  const colorFor = (fmax: number, fixed = false) => {
    if (fixed) return FORCE_FIXED;
    if (!(fmax > t)) return FORCE_OK;
    const k = (fmax - t) / Math.max(upper - t, 1e-9);
    // 超阈才上色，且从黄开始 → 不会和"达标绿"混淆
    return mix(FORCE_MID, FORCE_BAD, Math.min(1, Math.max(0, k)));
  };
  return { threshold: t, upper, colorFor };
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
  const observedMax = data.atoms.reduce((m, a) => Math.max(m, a.fmax), 0);
  const scale = makeForceScale(data.threshold?.max_force_threshold ?? 0.02, observedMax);
  const colors: Record<number, string> = {};
  data.atoms.forEach((a) => {
    colors[a.index] = scale.colorFor(a.fmax, a.fixed);
  });
  return { colors, scale, mismatch: false, note: null };
}
