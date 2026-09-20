import type {
  IncarCategory,
  IncarParamDef,
  IncarPreset,
  PrecisionMode,
  TaskType,
} from '../../types';

/**
 * INCAR 参数定义、精度预设与任务类型默认模板。
 * 后续接入后端时，可改为从 settings.json / task_registry.json 读取，结构保持一致。
 */

const BOOL: Omit<IncarParamDef, 'key' | 'label' | 'defaultValue'> = {
  type: 'bool',
};

export const INCAR_CATEGORIES: IncarCategory[] = [
  {
    key: 'basic',
    label: '体系与精度',
    params: [
      { key: 'SYSTEM', label: 'SYSTEM', type: 'string', hint: '体系名称，仅用于标识', defaultValue: 'VASP' },
      {
        key: 'PREC',
        label: 'PREC',
        type: 'enum',
        hint: '整体精度设置',
        defaultValue: 'Normal',
        options: [
          { value: 'Low', label: 'Low' },
          { value: 'Normal', label: 'Normal' },
          { value: 'Accurate', label: 'Accurate', hint: '更严格网格与收敛' },
        ],
      },
      { key: 'ENCUT', label: 'ENCUT', type: 'number', unit: 'eV', hint: '平面波截断能', defaultValue: '500' },
      { key: 'EDIFF', label: 'EDIFF', type: 'number', unit: 'eV', hint: '电子步收敛判据', defaultValue: '1E-5' },
      { key: 'EDIFFG', label: 'EDIFFG', type: 'number', unit: 'eV/Å', hint: '离子步力收敛判据（负值）', defaultValue: '-0.03' },
      {
        key: 'IVDW',
        label: 'IVDW',
        type: 'enum',
        hint: '色散修正（留空则不写入；11 = DFT-D3(BJ)）',
        defaultValue: '11',
        options: [
          { value: '0', label: '0', hint: '不做色散修正' },
          { value: '1', label: '1', hint: 'DFT-D2' },
          { value: '10', label: '10', hint: 'DFT-D3，零阻尼' },
          { value: '11', label: '11', hint: 'DFT-D3(BJ)，Becke-Jonson 阻尼（推荐）' },
          { value: '12', label: '12', hint: 'DFT-D3，零阻尼 + 三体项' },
          { value: '20', label: '20', hint: 'TS 方法（需 TSVDW）' },
          { value: '21', label: '21', hint: 'TS/HI 方法' },
          { value: '263', label: '263', hint: 'MBD 方法' },
        ],
      },
    ],
  },
  {
    key: 'ionic',
    label: '离子弛豫',
    params: [
      {
        key: 'IBRION',
        label: 'IBRION',
        type: 'enum',
        hint: '离子运动算法',
        defaultValue: '2',
        options: [
          { value: '-1', label: '-1', hint: '不移动离子（单点/静态计算）' },
          { value: '0', label: '0', hint: '分子动力学（需 MDALGO）' },
          { value: '1', label: '1', hint: 'RMM-DIIS 准牛顿' },
          { value: '2', label: '2', hint: '共轭梯度（CG），最常用' },
          { value: '3', label: '3', hint: '阻尼分子动力学' },
          { value: '5', label: '5', hint: '有限位移频率计算' },
        ],
      },
      {
        key: 'ISIF',
        label: 'ISIF',
        type: 'enum',
        hint: '计算自由度：应力/晶格/离子',
        defaultValue: '2',
        options: [
          { value: '0', label: '0', hint: '固定晶格，仅弛豫离子' },
          { value: '1', label: '1', hint: '弛豫离子，保持晶格形状与体积' },
          { value: '2', label: '2', hint: '弛豫离子，固定晶格体积（最常用）' },
          { value: '3', label: '3', hint: '同时弛豫离子与晶格' },
          { value: '4', label: '4', hint: '固定离子，仅优化晶格' },
          { value: '6', label: '6', hint: '固定离子，优化晶格与体积' },
          { value: '7', label: '7', hint: '固定离子，只优化体积' },
        ],
      },
      { key: 'NSW', label: 'NSW', type: 'number', hint: '最大离子步数', defaultValue: '100' },
      { key: 'POTIM', label: 'POTIM', type: 'number', unit: 'fs / Å', hint: '离子步长', defaultValue: '0.2' },
      {
        key: 'NFREE',
        label: 'NFREE',
        type: 'number',
        hint: '频率计算位移数（1/2/3）',
        defaultValue: '2',
        fracOnly: true,
      },
    ],
  },
  {
    key: 'electronic',
    label: '电子自洽',
    params: [
      {
        key: 'ALGO',
        label: 'ALGO',
        type: 'enum',
        hint: '电子步算法',
        defaultValue: 'Normal',
        options: [
          { value: 'Normal', label: 'Normal', hint: '标准 Davidson 块迭代' },
          { value: 'Fast', label: 'Fast', hint: '更快但稍不稳定' },
          { value: 'VeryFast', label: 'VeryFast', hint: '最快，适合粗略计算' },
          { value: 'All', label: 'All' },
          { value: 'Damped', label: 'Damped', hint: '阻尼算法，难收敛时使用' },
          { value: 'Exact', label: 'Exact', hint: '精确对角化（小体系）' },
        ],
      },
      {
        key: 'ISTART',
        label: 'ISTART',
        type: 'enum',
        hint: '是否读取 WAVECAR',
        defaultValue: '0',
        options: [
          { value: '0', label: '0', hint: '从头开始，不读 WAVECAR' },
          { value: '1', label: '1', hint: '读取 WAVECAR 续算' },
        ],
      },
      {
        key: 'ICHARG',
        label: 'ICHARG',
        type: 'enum',
        hint: '电荷密度初值来源',
        defaultValue: '0',
        options: [
          { value: '0', label: '0', hint: '从初始波函数生成' },
          { value: '1', label: '1', hint: '读 CHGCAR' },
          { value: '2', label: '2', hint: '原子电荷叠加（不迭代）' },
          { value: '10', label: '10', hint: '读 CHGCAR 且不自洽（DOS 等）' },
          { value: '11', label: '11', hint: '读 CHGCAR，只做一步（Bader）' },
        ],
      },
      { key: 'NELM', label: 'NELM', type: 'number', hint: '最大电子步数', defaultValue: '60' },
      {
        key: 'ISMEAR',
        label: 'ISMEAR',
        type: 'enum',
        hint: '态密度展宽方法',
        defaultValue: '0',
        options: [
          { value: '-5', label: '-5', hint: 'BLOCK 方法（绝缘体推荐）' },
          { value: '-4', label: '-4', hint: '四面体方法' },
          { value: '-1', label: '-1', hint: 'Fermi 展宽（不推荐）' },
          { value: '0', label: '0', hint: '高斯展宽（金属推荐）' },
          { value: '1', label: '1', hint: 'Methfessel-Paxton 1 阶' },
          { value: '2', label: '2', hint: 'Methfessel-Paxton 2 阶' },
        ],
      },
      { key: 'SIGMA', label: 'SIGMA', type: 'number', unit: 'eV', hint: '展宽宽度', defaultValue: '0.05' },
      {
        key: 'LREAL',
        label: 'LREAL',
        type: 'enum',
        hint: '实空间投影',
        defaultValue: 'Auto',
        options: [
          { value: 'Auto', label: 'Auto', hint: '自动选择（推荐）' },
          { value: '.FALSE.', label: '.FALSE.', hint: '倒空间（小体系更准）' },
          { value: '.TRUE.', label: '.TRUE.', hint: '强制实空间' },
        ],
      },
    ],
  },
  {
    key: 'spin',
    label: '自旋与磁性',
    params: [
      {
        key: 'ISPIN',
        label: 'ISPIN',
        type: 'enum',
        hint: '自旋极化',
        defaultValue: '1',
        options: [
          { value: '1', label: '1', hint: '非自旋极化' },
          { value: '2', label: '2', hint: '自旋极化' },
        ],
      },
      { key: 'MAGMOM', label: 'MAGMOM', type: 'string', hint: '初始磁矩（按原子数给出，留空则不写入）', defaultValue: '' },
    ],
  },
  {
    key: 'output',
    label: '输出与文件',
    params: [
      { key: 'LWAVE', label: 'LWAVE', ...BOOL, hint: '是否写 WAVECAR', defaultValue: '.FALSE.' },
      { key: 'LCHARG', label: 'LCHARG', ...BOOL, hint: '是否写 CHGCAR', defaultValue: '.FALSE.' },
      { key: 'LAECHG', label: 'LAECHG', ...BOOL, hint: '是否写 AECCAR（Bader 分析）', defaultValue: '.FALSE.' },
      { key: 'LVTOT', label: 'LVTOT', ...BOOL, hint: '是否写 LOCPOT（静电势）', defaultValue: '.FALSE.' },
      {
        key: 'LORBIT',
        label: 'LORBIT',
        type: 'enum',
        hint: '投影态密度输出',
        defaultValue: '11',
        options: [
          { value: '0', label: '0', hint: '不输出投影' },
          { value: '10', label: '10', hint: '输出 DOSCAR 投影' },
          { value: '11', label: '11', hint: '输出投影 + 相角（推荐）' },
          { value: '12', label: '12', hint: '更多轨道分解' },
        ],
      },
    ],
  },
  {
    key: 'parallel',
    label: '并行与性能',
    params: [
      {
        key: 'NCORE',
        label: 'NCORE',
        type: 'number',
        hint: '每核组核数（2–4 常用，约 √每组核数）；留空即不写入 INCAR',
        defaultValue: '',
      },
      { key: 'KPAR', label: 'KPAR', type: 'number', hint: 'k 点并行数（≤ k 点数，能整除更好）；留空即不写入', defaultValue: '' },
    ],
  },
];

/**
 * 带主开关的扩展卡片（DFT+U / 偶极矩修正）。
 * UI 由 IncarEditor 单独渲染（开关 + 元素表 / 三分量），但参数属于预设集合：
 * 1) 不出现在「其他参数」里重复出现；
 * 2) 主开关关闭时，整组参数都不写进 INCAR（见 INCAR_TEXT_CATEGORIES 的 gate）。
 */
export const INCAR_SWITCH_GROUPS: {
  key: string;
  label: string;
  keys: string[];
  hint: string;
}[] = [
  {
    key: 'LDAU',
    label: 'DFT+U',
    keys: ['LDAU', 'LDAUTYPE', 'LMAXMIX', 'LDAUL', 'LDAUU', 'LDAUJ'],
    hint: '关闭时不写入任何 LDAU* 参数；打开时写入 LDAU = .TRUE. 与下方元素表',
  },
  {
    key: 'LDIPOL',
    label: '偶极矩修正',
    keys: ['LDIPOL', 'IDIPOL', 'DIPOL', 'EFIELD'],
    hint: '关闭时不写入 LDIPOL / IDIPOL / DIPOL / EFIELD',
  },
];

/** LDAUTYPE 可选值 */
export const LDAUTYPE_OPTIONS = [
  { value: '1', label: '1', hint: 'Liechtenstein 等（VASP 默认，一般用这个）' },
  { value: '2', label: '2', hint: 'Dudarev 等简化形式（只用 U−J）' },
  { value: '4', label: '4', hint: 'Liechtenstein 等 + 交换分裂' },
];

/** LDAUL 可选值（-1 = 该元素不加 U） */
export const LDAUL_OPTIONS = [
  { value: '-1', label: '-1', hint: '不施加 U' },
  { value: '0', label: '0', hint: 's 轨道' },
  { value: '1', label: '1', hint: 'p 轨道' },
  { value: '2', label: '2', hint: 'd 轨道（过渡金属常用）' },
  { value: '3', label: '3', hint: 'f 轨道（镧系/锕系）' },
];

/** IDIPOL 可选值 */
export const IDIPOL_OPTIONS = [
  { value: '1', label: '1', hint: '沿 a 方向' },
  { value: '2', label: '2', hint: '沿 b 方向' },
  { value: '3', label: '3', hint: '沿 c 方向（表面/二维体系常用，默认）' },
  { value: '4', label: '4', hint: '所有方向（孤立分子）' },
];

type GatedIncarCategory = IncarCategory & { gate?: string };

/** 写 INCAR 时的完整分类顺序：通用分类 + 两个带主开关的扩展卡片 */
const INCAR_TEXT_CATEGORIES: GatedIncarCategory[] = [
  ...INCAR_CATEGORIES,
  {
    key: 'ldau',
    label: 'DFT+U',
    gate: 'LDAU',
    params: [
      { key: 'LDAU', label: 'LDAU', type: 'bool', hint: 'DFT+U 主开关（.TRUE. 时生效）', defaultValue: '.TRUE.' },
      {
        key: 'LDAUTYPE',
        label: 'LDAUTYPE',
        type: 'enum',
        hint: 'DFT+U 类型（1 = Liechtenstein，2 = Dudarev，4 = 带交换分裂）',
        defaultValue: '1',
        options: LDAUTYPE_OPTIONS,
      },
      { key: 'LMAXMIX', label: 'LMAXMIX', type: 'number', hint: '电荷混合的最高 l（d 体系 4，f 体系 6）', defaultValue: '4' },
      { key: 'LDAUL', label: 'LDAUL', type: 'string', hint: '每个元素施加 U 的 l 量子数（-1 = 不加 U）', defaultValue: '' },
      { key: 'LDAUU', label: 'LDAUU', type: 'string', hint: '每个元素的 U 值（eV）', defaultValue: '' },
      { key: 'LDAUJ', label: 'LDAUJ', type: 'string', hint: '每个元素的 J 值（eV）', defaultValue: '' },
    ],
  },
  {
    key: 'dipole',
    label: '偶极矩修正',
    gate: 'LDIPOL',
    params: [
      { key: 'LDIPOL', label: 'LDIPOL', type: 'bool', hint: '偶极矩修正主开关', defaultValue: '.TRUE.' },
      { key: 'IDIPOL', label: 'IDIPOL', type: 'enum', hint: '修正方向（1/2/3 = a/b/c 方向）', defaultValue: '3', options: IDIPOL_OPTIONS },
      { key: 'EFIELD', label: 'EFIELD', type: 'number', hint: '外加静电场（eV/Å，只填一个数值；方向由 IDIPOL 决定）', defaultValue: '' },
      { key: 'DIPOL', label: 'DIPOL', type: 'string', hint: '偶极矩参考点坐标（三个分量都填才写入）', defaultValue: '' },
    ],
  },
];

/** 精度预设：切换低/中/高时自动应用的参数子集 */
export const PRECISION_PRESETS: Record<
  Exclude<PrecisionMode, 'custom'>,
  Record<string, string>
> = {
  low: {
    PREC: 'Low',
    ENCUT: '400',
    EDIFF: '1E-4',
    EDIFFG: '-0.05',
    NSW: '80',
    ISMEAR: '0',
    SIGMA: '0.1',
    ALGO: 'Fast',
  },
  medium: {
    PREC: 'Normal',
    ENCUT: '500',
    EDIFF: '1E-5',
    EDIFFG: '-0.03',
    NSW: '100',
    ISMEAR: '0',
    SIGMA: '0.05',
    ALGO: 'Normal',
  },
  high: {
    PREC: 'Accurate',
    ENCUT: '500',
    EDIFF: '1E-6',
    EDIFFG: '-0.02',
    NSW: '500',
    ISMEAR: '0',
    SIGMA: '0.05',
    ALGO: 'Normal',
  },
};

/** 任务类型默认 INCAR（对齐 task_registry.json 的 default_incar） */
export const TASK_TYPE_INCAR: Partial<Record<TaskType, Record<string, string>>> = {
  opt: { IBRION: '2', NSW: '100', EDIFFG: '-0.02', ISIF: '2' },
  frac: { IBRION: '5', NFREE: '2', POTIM: '0.015', NSW: '1', ISIF: '2' },
  neb: { IBRION: '1', NSW: '100', EDIFF: '1E-5', ISIF: '0', SPRING: '-5' },
  ele: { ICHARG: '11', NSW: '0', IBRION: '-1', LORBIT: '11' },
};

/** 从参数定义生成完整默认参数表 */
export function buildDefaultParams(taskType: TaskType): Record<string, string> {
  const params: Record<string, string> = {};
  for (const cat of INCAR_CATEGORIES) {
    for (const def of cat.params) {
      if (def.fracOnly && taskType !== 'frac') continue;
      if (def.defaultValue !== '') params[def.key] = def.defaultValue;
    }
  }
  const override = TASK_TYPE_INCAR[taskType];
  if (override) Object.assign(params, override);
  return params;
}

/** 表单预设参数的键集合（用于把"其他参数"分出来；含两个带主开关的卡片） */
export const PRESET_INCAR_KEYS: Set<string> = new Set(
  [
    ...INCAR_CATEGORIES.flatMap((cat) => cat.params.map((def) => def.key)),
    ...INCAR_SWITCH_GROUPS.flatMap((group) => group.keys),
  ],
);

/** VASP 布尔的等价写法：`.T.` ≡ `.TRUE.` ≡ `T` ≡ `1`（大小写不敏感） */
const TRUE_WORDS = new Set(['1', 't', 'true', '.t.', '.true.', 'yes', 'on']);
const FALSE_WORDS = new Set(['0', 'f', 'false', '.f.', '.false.', 'no', 'off']);

export function isIncarTrue(value: unknown): boolean {
  return TRUE_WORDS.has(String(value ?? '').trim().toLowerCase());
}

export function isIncarFalse(value: unknown): boolean {
  return FALSE_WORDS.has(String(value ?? '').trim().toLowerCase());
}

/**
 * INCAR 参数值的**语义等价比较**（判断"有没有真改"用）：
 * - 布尔参数：`.T.` 与 `.TRUE.`、`.F.` 与 `.FALSE.` 视为相同；
 * - 数值参数：`1E-6` 与 `1e-6`、`-0.02` 与 `-0.020` 视为相同；
 * - 其他：去首尾空白后按字符串比较。
 */
export function incarValueEquals(
  def: IncarParamDef | undefined,
  a: unknown,
  b: unknown,
): boolean {
  const va = String(a ?? '').trim();
  const vb = String(b ?? '').trim();
  if (def?.type === 'bool') {
    return (isIncarTrue(va) && isIncarTrue(vb)) || (isIncarFalse(va) && isIncarFalse(vb));
  }
  if (def?.type === 'number' && va !== '' && vb !== '') {
    const na = Number(va.replace(/[dD]/, 'E'));
    const nb = Number(vb.replace(/[dD]/, 'E'));
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na === nb;
  }
  return va === vb;
}

/** 预设表单里该键的定义（找不到返回 undefined） */
export function incarParamDef(key: string): IncarParamDef | undefined {
  for (const cat of INCAR_TEXT_CATEGORIES) {
    const hit = cat.params.find((def) => def.key === key);
    if (hit) return hit;
  }
  return undefined;
}

/** 不在预设表单里的参数（"其他参数"区显示：来自本次计算的 INCAR 快照） */
export function extraIncarParams(params: Record<string, string>): Record<string, string> {
  const extra: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (!PRESET_INCAR_KEYS.has(key) && String(value ?? '').trim() !== '') {
      extra[key] = String(value);
    }
  }
  return extra;
}

/* ---------- DFT+U：元素表 ↔ LDAUL / LDAUU / LDAUJ 三个数组 ---------- */

/** 元素表的一行（对应 VASP 里一个元素/物种） */
export interface LdauRow {
  ldaul: string;
  ldauu: string;
  ldauj: string;
}

const ARRAY_SPLIT_RE = /[\s,]+/;

function splitArrayValue(value: unknown): string[] {
  return String(value ?? '')
    .trim()
    .split(ARRAY_SPLIT_RE)
    .filter((part) => part !== '');
}

/** 把 LDAUL / LDAUU / LDAUJ 三个数组解析成元素行（行数取三者最大，缺项留空） */
export function parseLdauRows(params: Record<string, string>): LdauRow[] {
  const l = splitArrayValue(params.LDAUL);
  const u = splitArrayValue(params.LDAUU);
  const j = splitArrayValue(params.LDAUJ);
  const count = Math.max(l.length, u.length, j.length);
  return Array.from({ length: count }, (_, i) => ({
    ldaul: l[i] ?? '',
    ldauu: u[i] ?? '',
    ldauj: j[i] ?? '',
  }));
}

/** 元素行 → 三个数组参数（一一对应，行数变化时同步更新） */
export function ldauArrayParams(rows: LdauRow[]): Record<string, string> {
  return {
    LDAUL: rows.map((row) => row.ldaul.trim()).join(' '),
    LDAUU: rows.map((row) => row.ldauu.trim()).join(' '),
    LDAUJ: rows.map((row) => row.ldauj.trim()).join(' '),
  };
}

/**
 * 过滤掉"主开关关闭"的整组参数。
 * 生成 INCAR 文本（buildIncarText）与上传/草稿链路共用同一套开关语义，
 * 保证「主开关关闭 → 不写入该组任何参数」在两条路径上一致。
 */
export function applyIncarGates(params: Record<string, string>): Record<string, string> {
  const gateOf = new Map<string, string>();
  for (const group of INCAR_SWITCH_GROUPS) {
    for (const key of group.keys) gateOf.set(key, group.key);
  }
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    const gate = gateOf.get(key);
    // 主开关关闭 → 整组参数**置空**（而不是"跳过"）：
    // 下游都把空值当作"不写入"，草稿接口（set_incar_draft）也用空值表示
    // "这项回到本次计算值"，所以关掉开关能顺带清掉之前存下的整组草稿，
    // 不会出现"关掉 / 撤销 LDAU 后，下一次续算仍然写入 LDAUU/LDAUL…"。
    if (gate && !isIncarTrue(params[gate] ?? '')) {
      out[key] = '';
      continue;
    }
    out[key] = value;
  }
  return out;
}

/**
 * 编辑器表单的基线参数 = **本次计算实际值 + 待生效草稿**。
 *
 * 刷新页面后草稿仍然存在（后端 input_state.draft），表单必须把它显示出来，
 * 否则会出现"横幅列着待生效修改、下面的参数却回到已同步值"的不一致。
 */
export function incarFormParams(
  taskType: TaskType,
  snapshotParams?: Record<string, string> | null,
  draftParams?: Record<string, string> | null,
): Record<string, string> {
  const draft = draftParams ?? {};
  return snapshotParams
    ? { ...snapshotParams, ...draft }
    : { ...buildDefaultParams(taskType), ...draft };
}

/**
 * 撤销**单项**待生效修改时发给后端的参数补丁（空值 = 回到本次计算值）。
 *
 * 依赖关系：被撤销的键属于带主开关的组（DFT+U / 偶极矩修正）时，
 * 如果撤销后主开关不再是 `.TRUE.`，整组参数一起置空 ——
 * 否则会出现"撤销了 LDAU，下一次续算却仍然写入 LDAUU/LDAUL/LDAUTYPE…"。
 */
export function revertIncarPatch(
  key: string,
  draftParams?: Record<string, string> | null,
  snapshotParams?: Record<string, string> | null,
): Record<string, string> {
  const draft = draftParams ?? {};
  const snapshot = snapshotParams ?? {};
  const patch: Record<string, string> = { [key]: '' };
  const group = INCAR_SWITCH_GROUPS.find((item) => item.keys.includes(key));
  if (!group) return patch;
  // 撤销后该键回到"本次计算值"，据此判断主开关是否仍然打开
  const master =
    key === group.key
      ? String(snapshot[group.key] ?? '')
      : String(draft[group.key] ?? snapshot[group.key] ?? '');
  if (!isIncarTrue(master)) {
    for (const groupKey of group.keys) patch[groupKey] = '';
  }
  return patch;
}

/** 打开 DFT+U 时的默认元素表：第一个元素给 U（LDAUL=2 / LDAUU=4.0），其余不加 U */
export function defaultLdauRows(elementCount: number): LdauRow[] {
  const count = elementCount > 0 ? elementCount : 1;
  return Array.from({ length: count }, (_, i) =>
    i === 0
      ? { ldaul: '2', ldauu: '4.0', ldauj: '0.0' }
      : { ldaul: '-1', ldauu: '0.0', ldauj: '0.0' },
  );
}

/* ---------- 偶极矩修正：DIPOL 的三个分量 ---------- */

/** 把 DIPOL 拆成 x / y / z 三个分量（缺失补空串） */
export function parseDipol(value: unknown): [string, string, string] {
  const parts = splitArrayValue(value);
  return [parts[0] ?? '', parts[1] ?? '', parts[2] ?? ''];
}

/** 三个分量都非空才返回 "x y z"；任一为空返回空串（即不写入 INCAR） */
export function joinDipol(parts: [string, string, string]): string {
  const trimmed = parts.map((part) => String(part ?? '').trim());
  if (trimmed.some((part) => part === '')) return '';
  return trimmed.join(' ');
}

/* ---------- 从 POSCAR 头解析元素符号（用于元素表行标签） ---------- */

/** 解析 VASP5 格式 POSCAR 的元素符号行；VASP4（无元素行）或解析失败返回空数组 */
export function parsePoscarElements(poscar: string | null | undefined): string[] {
  if (!poscar) return [];
  const lines = String(poscar)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== '');
  if (lines.length < 8) return [];
  const body = lines.slice(1); // 跳过注释行
  let index = 0;
  // 跳过缩放系数行（单个数值，或三向缩放的三个数值）
  const scaleTokens = body[index].split(/\s+/).filter(Boolean);
  if (scaleTokens.length <= 3 && scaleTokens.every((token) => /^[-+.\d]/.test(token))) {
    index += 1;
  }
  let lattice = 0;
  while (index < body.length && lattice < 3) {
    const tokens = body[index].split(/\s+/);
    if (tokens.length >= 3 && tokens.slice(0, 3).every((t) => /^[-+.\d]/.test(t))) {
      lattice += 1;
      index += 1;
      continue;
    }
    break;
  }
  if (lattice < 3 || index >= body.length) return [];
  const tokens = body[index].split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return [];
  if (!tokens.every((t) => /^[A-Z][a-z]?$/.test(t))) return []; // 是数字行 → VASP4
  return tokens;
}

function formatRows(rows: { key: string; value: string }[]): string {
  const width = Math.max(...rows.map((r) => r.key.length));
  return rows.map((r) => `${r.key.padEnd(width + 2)}= ${r.value}`).join('\n');
}

/** 解析自定义输入框中的参数行（KEY = value，任意键均保留，忽略 #/! 注释） */
export function parseCustomIncar(text: string): Record<string, string> {
  const params: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('!')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1);
    for (const marker of ['#', '!']) {
      const pos = value.indexOf(marker);
      if (pos !== -1) value = value.slice(0, pos);
    }
    value = value.trim();
    if (key && value) params[key] = value;
  }
  return params;
}

/**
 * 生成 INCAR 文本：按设置类型（分类）分组输出，分类之间空一行；
 * 按键宽对齐，布尔转 .TRUE./.FALSE.，数字规范科学计数法；
 * customText 为自定义参数行（KEY = value），作为最后一个分组追加。
 */
export function buildIncarText(
  params: Record<string, string>,
  categories: GatedIncarCategory[] = INCAR_TEXT_CATEGORIES,
  customText = '',
): string {
  const blocks: string[] = [];
  const used = new Set<string>();
  for (const cat of categories) {
    const rows: { key: string; value: string }[] = [];
    // 带主开关的分类：主开关不是真值时整组不写入（但键仍标记为已用，
    // 避免它们落到下面的「其他参数」块里被重复写出）
    const gatedOff = cat.gate ? !isIncarTrue(params[cat.gate] ?? '') : false;
    for (const def of cat.params) {
      const raw = params[def.key];
      used.add(def.key);
      if (gatedOff) continue;
      if (raw == null || String(raw).trim() === '') continue;
      rows.push({ key: def.key, value: formatIncarValue(def, raw) });
    }
    if (rows.length > 0) blocks.push(formatRows(rows));
  }
  const customRows = Object.entries(parseCustomIncar(customText)).map(
    ([key, value]) => ({ key, value }),
  );
  // 不在预设表单里的参数（如从远端同步回来的其他参数）也要写进 INCAR
  for (const [key, value] of Object.entries(params)) {
    if (used.has(key)) continue;
    if (value == null || String(value).trim() === '') continue;
    if (customRows.some((row) => row.key.toUpperCase() === key.toUpperCase())) continue;
    customRows.push({ key, value: String(value).trim() });
  }
  if (customRows.length > 0) blocks.push(formatRows(customRows));
  return blocks.join('\n\n');
}

export function formatIncarValue(def: IncarParamDef, raw: string): string {
  if (def.type === 'bool') {
    return ['1', 'true', 'True', 'TRUE', '.TRUE.', 'yes', 'on'].includes(String(raw).trim())
      ? '.TRUE.'
      : '.FALSE.';
  }
  const v = String(raw).trim();
  if (def.type === 'number' && /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(v)) {
    return v.replace(/^\+/, '').replace(/e([+-]?\d+)$/i, 'E$1');
  }
  return v;
}

/** 解析真实 INCAR 文本 → 参数字典（仅收录表单已知参数，忽略注释） */
export function parseIncarContent(content: string): Record<string, string> {
  const params: Record<string, string> = {};
  for (const raw of content.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    // 值保留完整内容（DIPOL = 0.5 0.5 0.18、MAGMOM = 5*2.0 等含空格的参数不能被截断）；
    // 也不过滤"预设之外"的键——它们会出现在「其他参数」里
    const value = line.slice(eq + 1).split('#')[0].trim();
    if (key && value) params[key] = value;
  }
  return params;
}

/** 内置模板列表（加载预设下拉用） */
export const BUILTIN_PRESETS: IncarPreset[] = [
  {
    id: 'tpl:structure_opt',
    name: '默认 · 结构优化 (opt)',
    builtin: true,
    params: buildDefaultParams('opt'),
  },
  {
    id: 'tpl:ele',
    name: '默认 · 电子结构 (ele)',
    builtin: true,
    params: buildDefaultParams('ele'),
  },
  {
    id: 'tpl:frac',
    name: '默认 · 频率矫正 (frac)',
    builtin: true,
    params: buildDefaultParams('frac'),
  },
  {
    id: 'tpl:neb',
    name: '默认 · NEB',
    builtin: true,
    params: buildDefaultParams('neb'),
  },
];
