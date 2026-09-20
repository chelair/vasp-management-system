/**
 * 3Dmol 结构视图数据工具：解析 vasp2cif 生成的 CIF、VESTA 元素配色、
 * 按共价半径计算键。从测试页 poscar_cif.js 移植。
 */

export interface Structure3DAtom {
  element: string;
  /** 笛卡尔坐标（Å），3Dmol 渲染与成键计算用 */
  x: number;
  y: number;
  z: number;
  /**
   * 分数坐标（CIF 的 `_atom_site_fract_*` 原值，与 POSCAR 坐标行一致），
   * 供 3D 视图左上角显示"选中原子坐标"用；缺失时界面显示 —。
   */
  fx?: number;
  fy?: number;
  fz?: number;
}

export interface Structure3D {
  lattice: number[][];
  elements: string[];
  counts: number[];
  atoms: Structure3DAtom[];
  lengths: { a: number; b: number; c: number };
  angles: { alpha: number; beta: number; gamma: number };
  volume: number;
}

export const ELEMENT_COLORS: Record<string, string> = {
  H: '#ffffff',
  He: '#d9ffff',
  Li: '#cc80ff',
  Be: '#c2ff00',
  B: '#ffb5b5',
  C: '#909090',
  N: '#3050f8',
  O: '#ff0d0d',
  F: '#90e050',
  Ne: '#b3e7f5',
  Na: '#ab5cf2',
  Mg: '#8aff00',
  Al: '#bfa6a6',
  Si: '#f0c8a0',
  P: '#ff8000',
  S: '#ffff30',
  Cl: '#1ff01f',
  Ar: '#80d1e3',
  K: '#8f40d4',
  Ca: '#3dff00',
  Sc: '#e6e6e6',
  Ti: '#bfc2c7',
  V: '#a6a6ab',
  Cr: '#8a99c7',
  Mn: '#b05cf6',
  Fe: '#e06633',
  Co: '#a0a0ff',
  Ni: '#50d050',
  Cu: '#c88033',
  Zn: '#7d80b0',
  Ga: '#c28f8f',
  Ge: '#668080',
  As: '#bd80e3',
  Se: '#ffa11f',
  Br: '#a62929',
  Kr: '#5cb8d1',
  Rb: '#ff00a1',
  Sr: '#00ff00',
  Y: '#94ffff',
  Zr: '#94e0e0',
  Nb: '#73fefd',
  Mo: '#54b5b5',
  Tc: '#3b9e9e',
  Ru: '#248f8f',
  Rh: '#0a7d8c',
  Pd: '#006985',
  Ag: '#c0c0c0',
  Cd: '#ffd98f',
  In: '#a67573',
  Sn: '#668080',
  Sb: '#9e63b5',
  Te: '#d47a00',
  I: '#940094',
  Xe: '#429eb0',
  Cs: '#57178f',
  Ba: '#00c900',
  La: '#70d4ff',
  Hf: '#4ddcff',
  Ta: '#4da6ff',
  W: '#2194d6',
  Re: '#267dab',
  Os: '#266696',
  Ir: '#175487',
  Pt: '#d0d0e0',
  Au: '#ffd123',
  Hg: '#b8b8d0',
  Tl: '#a6544d',
  Pb: '#575961',
  Bi: '#9e4fb5',
  U: '#008fff',
};

const COVALENT_RADII: Record<string, number> = {
  H: 0.31,
  B: 0.84,
  C: 0.76,
  N: 0.71,
  O: 0.66,
  F: 0.57,
  Al: 1.21,
  Si: 1.11,
  P: 1.07,
  S: 1.05,
  Cl: 1.02,
  Ti: 1.6,
  V: 1.53,
  Cr: 1.39,
  Mn: 1.39,
  Fe: 1.32,
  Co: 1.26,
  Ni: 1.24,
  Cu: 1.32,
  Zn: 1.22,
  Ga: 1.22,
  Ge: 1.2,
  Mo: 1.54,
  Ag: 1.45,
  Sn: 1.39,
  W: 1.62,
  Pt: 1.36,
  Au: 1.36,
};

function det3(m: number[][]): number {
  return (
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  );
}

function matVec(m: number[][], v: number[]): number[] {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ];
}

function buildLatticeFromLengths(
  lengths: { a: number; b: number; c: number },
  angles: { alpha: number; beta: number; gamma: number },
): number[][] {
  const a = lengths.a;
  const b = lengths.b;
  const c = lengths.c;
  const rad = Math.PI / 180;
  const ca = Math.cos(angles.alpha * rad);
  const cb = Math.cos(angles.beta * rad);
  const cg = Math.cos(angles.gamma * rad);
  const sg = Math.sin(angles.gamma * rad);
  const cx = c * cb;
  const cy = (c * (ca - cb * cg)) / (sg || 1);
  const cz = Math.sqrt(Math.max(0, c * c - cx * cx - cy * cy));
  return [
    [a, 0, 0],
    [b * cg, b * sg, 0],
    [cx, cy, cz],
  ];
}

/** 解析 CIF 文本（vasp2cif / VESTA 标准格式），失败返回 null。 */
export function parseCif(text: string): Structure3D | null {
  if (typeof text !== 'string') return null;
  const lines = text.split(/\r?\n/);
  const getNum = (re: RegExp): number | null => {
    for (const line of lines) {
      const m = line.match(re);
      if (m) {
        const v = parseFloat(m[1]);
        if (Number.isFinite(v)) return v;
      }
    }
    return null;
  };
  const a = getNum(/_cell_length_a\s+([\d.]+)/);
  const b = getNum(/_cell_length_b\s+([\d.]+)/);
  const c = getNum(/_cell_length_c\s+([\d.]+)/);
  const alpha = getNum(/_cell_angle_alpha\s+([\d.]+)/) ?? 90;
  const beta = getNum(/_cell_angle_beta\s+([\d.]+)/) ?? 90;
  const gamma = getNum(/_cell_angle_gamma\s+([\d.]+)/) ?? 90;
  if (!a || !b || !c) return null;
  const lattice = buildLatticeFromLengths({ a, b, c }, { alpha, beta, gamma });

  let atomStart = -1;
  let cols: Record<string, number> | null = null;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() !== 'loop_') continue;
    const names: string[] = [];
    let j = i + 1;
    while (j < lines.length && /^_\w+/.test(lines[j].trim())) {
      names.push(lines[j].trim());
      j++;
    }
    if (names.includes('_atom_site_fract_x')) {
      cols = {};
      for (let k = 0; k < names.length; k++) cols[names[k]] = k;
      atomStart = j;
      break;
    }
  }
  if (!cols || atomStart < 0) return null;

  const countsMap: Record<string, number> = {};
  const atoms: Structure3DAtom[] = [];
  for (let i = atomStart; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) break;
    const parts = line.split(/\s+/);
    const get = (name: string): string | null => {
      const idx = cols[name];
      return idx != null && parts[idx] !== undefined ? parts[idx] : null;
    };
    const fx = parseFloat(get('_atom_site_fract_x') ?? '');
    const fy = parseFloat(get('_atom_site_fract_y') ?? '');
    const fz = parseFloat(get('_atom_site_fract_z') ?? '');
    if (!Number.isFinite(fx) || !Number.isFinite(fy) || !Number.isFinite(fz)) break;
    const el = String(get('_atom_site_type_symbol') || get('_atom_site_label') || 'X');
    const cart = matVec(lattice, [fx, fy, fz]);
    atoms.push({ element: el, x: cart[0], y: cart[1], z: cart[2], fx, fy, fz });
    countsMap[el] = (countsMap[el] || 0) + 1;
  }
  if (!atoms.length) return null;

  const elements = Object.keys(countsMap);
  return {
    lattice,
    elements,
    counts: elements.map((el) => countsMap[el]),
    atoms,
    lengths: { a, b, c },
    angles: { alpha, beta, gamma },
    volume: Math.abs(det3(lattice)),
  };
}

function covalentRadius(el: string): number {
  return COVALENT_RADII[el] || 1.1;
}

/**
 * 按共价半径阈值计算原子对键（晶胞内笛卡尔距离，不做周期包裹，
 * 保证画出的键都在可视晶胞内）。返回 [i, j] 索引对数组。
 */
export function computeBonds(structure: Structure3D, tol = 0.45): number[][] {
  const atoms = structure.atoms;
  const bonds: number[][] = [];
  for (let i = 0; i < atoms.length; i++) {
    for (let j = i + 1; j < atoms.length; j++) {
      const dx = atoms[j].x - atoms[i].x;
      const dy = atoms[j].y - atoms[i].y;
      const dz = atoms[j].z - atoms[i].z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const cutoff =
        covalentRadius(atoms[i].element) + covalentRadius(atoms[j].element) + tol;
      if (dist > 0.3 && dist < cutoff) bonds.push([i, j]);
    }
  }
  return bonds;
}
