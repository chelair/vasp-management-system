/**
 * VASP LSF 提交脚本（vasp.lsf）模板 —— 8 段结构（v0.8.7）。
 *
 * 模板已在实际 HPC 上验证，这里只把它拆成"固定段 + 可配置段"：
 *   S1 HEADER 固定 → S2 BSUB 指令（部分可变）→ S3 配置变量（部分可变）→ S4 环境准备固定
 *   → S5 日志起始固定 → S6 软结束模块（条件）→ S7 主运行固定 → S8 收尾（固定 + 条件）
 *
 * 约束：`#BSUB` 指令必须顶格（行首），且不能写 `$变量`（LSF 不做变量展开）。
 */

export interface VaspLsfOptions {
  /** 任务名称 → #BSUB -J */
  jobName: string;
  /** 队列 → #BSUB -q */
  queue: string;
  /** 截止时间 HH:MM → #BSUB -W */
  walltime: string;
  /** 总核数 → #BSUB -n 与 NPROCS 兜底 */
  cores: number;
  /** 每节点核数 → #BSUB -R "span[ptile=X]" */
  coresPerNode: number;
  /** 软结束模块开关：影响 S2 两条指令 / S6 整段 / S8 的 kill 行 */
  softKill: boolean;
  /** 软结束预警时间（分钟）→ #BSUB -wt（默认 50） */
  warnMinutes?: number;
}

export interface VaspLsfSection {
  id: string;
  /** S1..S8 */
  label: string;
  title: string;
  kind: 'fixed' | 'variable' | 'conditional';
  text: string;
}

const VASP_BIN = '/data/gpfs03/mdye/vasp.6.4.2/bin/vasp_std';
const PSXEVARS = '/data/gpfs03/mdye/intel/parallel_studio_xe_2020/psxevars.sh';
/** 软结束预警时间默认值（分钟）：#BSUB -wt */
export const DEFAULT_WARN_MINUTES = 50;

/** 截止时间：小时 / 分钟 → `HH:MM`（两位补零：4 → `04`，24 → `24`；三位小时原样保留） */
export function formatWalltime(hours: number, minutes: number): string {
  const h = Math.max(0, Math.min(999, Math.trunc(hours)));
  const m = Math.max(0, Math.min(59, Math.trunc(minutes)));
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/** 分钟超界归一：>59 记为 59（与表单行为一致） */
export function normalizeMinute(value: number | null | undefined): number {
  if (value === null || value === undefined || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(59, Math.trunc(value)));
}

/** 预计分配节点数 = ceil(总核数 / 每节点核数)；不做整除校验（LSF 自己会分配） */
export function estimateNodes(cores: number, coresPerNode: number): number {
  if (!(cores > 0) || !(coresPerNode > 0)) return 0;
  return Math.ceil(cores / coresPerNode);
}

/** 8 段内容（软结束关时 S6 为空、S2/S8 自动少几行） */
export function vaspLsfSections(opts: VaspLsfOptions): VaspLsfSection[] {
  const jobName = (opts.jobName || '').trim();
  const queue = (opts.queue || '').trim();
  const walltime = opts.walltime || formatWalltime(24, 0);
  const cores = Math.max(1, Math.trunc(opts.cores || 1));
  const ptile = Math.max(1, Math.trunc(opts.coresPerNode || 1));
  const warnMinutes = Math.max(1, Math.trunc(opts.warnMinutes ?? DEFAULT_WARN_MINUTES));

  const bsub = [
    '#BSUB -J ' + jobName,
    '#BSUB -q ' + queue,
    '#BSUB -o %J.out',
    '#BSUB -e %J.err',
    '#BSUB -W ' + walltime,
  ];
  if (opts.softKill) {
    // 软结束的两条指令插在 -W 与 -n 之间（顺序即语义，不要挪动）
    bsub.push('#BSUB -wt ' + warnMinutes, '#BSUB -wa URG');
  }
  bsub.push('#BSUB -n ' + cores, '#BSUB -R "span[ptile=' + ptile + ']"');

  const watcher = [
    'lsf_watcher() {',
    "    trap 'echo \"LSTOP = .TRUE.\" > STOPCAR; echo \"=== [$(date)] LSF Walltime Warning! STOPCAR generated. ===\" >> result; exit 0' SIGURG",
    '    while true; do sleep 60; done',
    '}',
    'lsf_watcher &',
    'WATCHER_PID=$!',
  ].join('\n');

  const closing = [
    'if [ $RC -eq 0 ]; then',
    '    echo "=== Job Finished normally at $(date) | elapsed=${ELAPSED}s ===" >> result',
    'else',
    '    echo "=== Job Failed at $(date) | elapsed=${ELAPSED}s | exit=$RC ===" >> result',
    'fi',
  ];
  if (opts.softKill) closing.push('kill $WATCHER_PID 2>/dev/null');
  closing.push('exit $RC');

  return [
    { id: 'S1', label: 'S1', title: 'HEADER', kind: 'fixed', text: '#!/bin/bash' },
    { id: 'S2', label: 'S2', title: 'BSUB 指令', kind: 'variable', text: bsub.join('\n') },
    {
      id: 'S3',
      label: 'S3',
      title: '配置变量',
      kind: 'variable',
      text: ['VASP_BIN=' + VASP_BIN, 'NPROCS=${LSB_DJOB_NUMPROC:-' + cores + '}'].join('\n'),
    },
    {
      id: 'S4',
      label: 'S4',
      title: '环境准备',
      kind: 'fixed',
      text: [
        'source ' + PSXEVARS,
        'module load impi',
        '',
        'export I_MPI_HYDRA_BOOTSTRAP=lsf',
        'export I_MPI_FABRICS=shm:ofi',
      ].join('\n'),
    },
    {
      id: 'S5',
      label: 'S5',
      title: '日志起始',
      kind: 'fixed',
      text: [
        'rm -f STOPCAR',
        '',
        'echo "=== Job Started at $(date) | NP=$NPROCS ===" > result',
      ].join('\n'),
    },
    {
      id: 'S6',
      label: 'S6',
      title: '软结束模块',
      kind: 'conditional',
      text: opts.softKill ? watcher : '',
    },
    {
      id: 'S7',
      label: 'S7',
      title: '主运行',
      kind: 'fixed',
      text: [
        'START=$(date +%s)',
        'mpiexec.hydra -genvall -n $NPROCS $VASP_BIN >> result 2>&1',
        'RC=$?',
        'ELAPSED=$(( $(date +%s) - START ))',
      ].join('\n'),
    },
    {
      id: 'S8',
      label: 'S8',
      title: '收尾',
      kind: 'conditional',
      text: closing.join('\n'),
    },
  ];
}

/** 完整脚本（空段自动跳过，段间留一个空行） */
export function buildVaspLsf(opts: VaspLsfOptions): string {
  return (
    vaspLsfSections(opts)
      .map((section) => section.text)
      .filter((text) => text.trim() !== '')
      .join('\n\n') + '\n'
  );
}
