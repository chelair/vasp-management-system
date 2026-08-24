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
 * 推荐 k 点网格：每个方向 ≈ 密度系数 / 晶格常数（最小为 1）。
 * 密度系数 20 表示约每埃 20 个 k 点，与多数脚本习惯一致。
 */
export function recommendKgrid(
  lengths: { a: number; b: number; c: number },
  density: number,
): [number, number, number] {
  const g = (L: number) => Math.max(1, Math.round(density / (L || 1)));
  return [g(lengths.a), g(lengths.b), g(lengths.c)];
}

/** 生成 KPOINTS 文件内容 */
export function buildKpoints(
  comment: string,
  meshType: 'Gamma' | 'Monkhorst-Pack',
  grid: [number, number, number],
  density: number,
): string {
  return `${comment} KPOINTS (密度 ${density})
0
${meshType}
${grid.join(' ')}
0 0 0`;
}
