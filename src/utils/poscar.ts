import type { PoscarInfo } from '../types';

/**
 * POSCAR 解析与 KPOINTS 网格推荐工具。
 * 框架阶段在前端解析；后续接入后端后可改为由 pymatgen 返回，接口保持一致。
 */

function vecLen(v: number[]): number {
  return Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

function angleBetween(a: number[], b: number[]): number {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cos = dot / (vecLen(a) * vecLen(b) || 1);
  return Math.acos(Math.max(-1, Math.min(1, cos))) * (180 / Math.PI);
}

function cross(a: number[], b: number[]): number[] {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function dot(a: number[], b: number[]): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/**
 * 解析 POSCAR 文本，返回晶格信息；无法解析时返回 null。
 * 兼容 VASP 4（无元素行）与 VASP 5（含元素行）、Selective dynamics、Direct/Cartesian。
 */
export function parsePoscar(text: string): PoscarInfo | null {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length < 7) return null;

  const comment = lines[0];
  const scale = parseFloat(lines[1]);
  if (!Number.isFinite(scale) || scale === 0) return null;

  const lattice: number[][] = [];
  for (let i = 0; i < 3; i += 1) {
    const parts = lines[2 + i].split(/\s+/).map(Number);
    if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return null;
    lattice.push(parts.slice(0, 3).map((n) => n * scale));
  }

  let idx = 5;
  let elements: string[] = [];
  let counts: number[] = [];
  const first = lines[5].split(/\s+/);
  if (first.every((s) => /^\d+$/.test(s))) {
    // VASP 4：无元素行，按计数顺序生成占位元素名
    counts = first.map(Number);
    elements = counts.map((_, i) => `El${i + 1}`);
    idx = 6;
  } else {
    elements = first;
    if (!lines[6] || !lines[6].split(/\s+/).every((s) => /^\d+$/.test(s))) {
      return null;
    }
    counts = lines[6].split(/\s+/).map(Number);
    idx = 7;
  }

  // Selective dynamics 标记行：仅当行首为 Selective/selective，
  // 或整行只含 S/T/F 标志（不能误伤 "Direct" 中的 't'）
  const marker = lines[idx] ?? '';
  if (/^selective/i.test(marker) || /^[sStTfF](\s+[sStTfF])*$/.test(marker)) idx += 1;
  const coordMode = lines[idx] ?? 'Direct';
  if (!/^(Direct|Cartesian)/i.test(coordMode)) return null;
  if (elements.length !== counts.length) return null;

  const [a, b, c] = lattice;
  const volume = Math.abs(dot(a, cross(b, c)));
  if (!Number.isFinite(volume) || volume <= 0) return null;

  return {
    comment,
    scale,
    lattice,
    elements,
    counts,
    coordMode,
    lengths: { a: vecLen(a), b: vecLen(b), c: vecLen(c) },
    angles: {
      alpha: angleBetween(b, c),
      beta: angleBetween(a, c),
      gamma: angleBetween(a, b),
    },
    volume,
  };
}

/**
 * 推荐 k 点网格：每个方向取**满足 `k × 晶格常数 > 密度系数` 的最小整数**。
 *
 * 密度系数 20 表示"每埃至少 20 个 k 点"的密度要求；取严格大于（而不是四舍五入）
 * 是为了让每个轴的 k×a 都落在巡检的合格区间（> 20）里。
 */
export function recommendKgrid(
  lengths: { a: number; b: number; c: number },
  density: number,
): [number, number, number] {
  /**
   * 推荐标准：满足 `k × 晶格常数 > 密度系数` 的**最小整数** k。
   *
   * 即 `k = floor(密度系数 / L) + 1`（严格大于，不是四舍五入）——
   * 这样每个轴的 k×a 都会落在巡检的 `> 20` 合格区间里。
   * 例：L=10 Å、系数 20 → k=3（k×a=30）；L=15 Å → k=2（30）；L=30 Å → k=1（30）。
   */
  const g = (L: number) => {
    const length = Number.isFinite(L) && L > 0 ? L : 1;
    return Math.max(1, Math.floor(density / length) + 1);
  };
  return [g(lengths.a), g(lengths.b), g(lengths.c)];
}

/** 是不是 CIF 文件：按扩展名，或按内容特征（CIF 标签）判断 */
export function looksLikeCif(filename: string, text: string): boolean {
  if (/\.cif$/i.test(String(filename || '').trim())) return true;
  const head = String(text || '').slice(0, 8000);
  const hasTag = /(^|\n)\s*(_cell_length_a|_atom_site_fract_x|_atom_site_label|_symmetry_equiv_pos_as_xyz)/i.test(head);
  const hasBlock = /(^|\n)\s*(data_|loop_|#)/i.test(head);
  return hasTag && hasBlock;
}

/** 生成 KPOINTS 文件内容 */
export function buildKpoints(
  comment: string,
  meshType: 'Gamma' | 'Monkhorst-Pack',
  grid: [number, number, number],
  density: number,
): string {
  // 首行注释必须是纯 ASCII：部分工具/编码会把中文注释读成乱码
  const safe = comment.replace(/[^\x20-\x7E]/g, '').trim();
  return `${safe} KPOINTS (density ${density})
0
${meshType}
${grid.join(' ')}
0 0 0`;
}
