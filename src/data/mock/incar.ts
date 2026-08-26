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
      { key: 'POTIM', label: 'POTIM', type: 'number', unit: 'fs / Å', hint: '离子步长', defaultValue: '0.5' },
      { key: 'NFREE', label: 'NFREE', type: 'number', hint: '频率计算位移数（1/2/3）', defaultValue: '2' },
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
      { key: 'ADDGRID', label: 'ADDGRID', ...BOOL, hint: '增加网格精度（软赝势）', defaultValue: '.FALSE.' },
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
      { key: 'MAGMOM', label: 'MAGMOM', type: 'string', hint: '初始磁矩（按原子数给出）', defaultValue: '1' },
      { key: 'LNONCOLLINEAR', label: 'LNONCOLLINEAR', ...BOOL, hint: '非共线磁性', defaultValue: '.FALSE.' },
      { key: 'LSORBIT', label: 'LSORBIT', ...BOOL, hint: '自旋轨道耦合', defaultValue: '.FALSE.' },
    ],
  },
  {
    key: 'output',
    label: '输出与文件',
    params: [
      { key: 'LWAVE', label: 'LWAVE', ...BOOL, hint: '是否写 WAVECAR', defaultValue: '.TRUE.' },
      { key: 'LCHARG', label: 'LCHARG', ...BOOL, hint: '是否写 CHGCAR', defaultValue: '.TRUE.' },
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
      { key: 'NCORE', label: 'NCORE', type: 'number', hint: '每核组核数（约 √节点核数）', defaultValue: '8' },
      { key: 'NPAR', label: 'NPAR', type: 'number', hint: '并行分组（与 NCORE 二选一）', defaultValue: '' },
      { key: 'KPAR', label: 'KPAR', type: 'number', hint: 'k 点并行数（≤ k 点数）', defaultValue: '1' },
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
    EDIFF: '1E-3',
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
    ENCUT: '600',
    EDIFF: '1E-6',
    EDIFFG: '-0.01',
    NSW: '200',
    ISMEAR: '0',
    SIGMA: '0.02',
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
      if (def.defaultValue !== '') params[def.key] = def.defaultValue;
    }
  }
  const override = TASK_TYPE_INCAR[taskType];
  if (override) Object.assign(params, override);
  return params;
}

/** 生成 INCAR 文本：按键宽对齐，布尔转 .TRUE./.FALSE.，数字规范科学计数法 */
export function buildIncarText(
  params: Record<string, string>,
  categories: IncarCategory[] = INCAR_CATEGORIES,
): string {
  const rows: { key: string; value: string }[] = [];
  for (const cat of categories) {
    for (const def of cat.params) {
      const raw = params[def.key];
      if (raw == null || String(raw).trim() === '') continue;
      rows.push({ key: def.key, value: formatIncarValue(def, raw) });
    }
  }
  if (rows.length === 0) return '';
  const width = Math.max(...rows.map((r) => r.key.length));
  return rows.map((r) => `${r.key.padEnd(width + 2)}= ${r.value}`).join('\n');
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
  const known = new Set(
    INCAR_CATEGORIES.flatMap((cat) => cat.params.map((p) => p.key)),
  );
  for (const raw of content.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).split('#')[0].trim();
    if (known.has(key) && value) params[key] = value;
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
