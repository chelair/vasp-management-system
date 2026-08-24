import type {
  ClusterNode,
  ClusterQueueSummary,
  ClusterSnapshot,
  NodeStatus,
  QueueOption,
  ScriptFormat,
  SubmitScriptOptions,
  SuspendRisk,
} from '../../types';

/**
 * 集群节点映射与提交脚本生成。
 * - 权威映射固化在服务器配置 data/config/servers.json 的 node_groups 中（后端读取）
 * - 本文件保留同构映射用于前端离线兜底（后端不可用时仍可预览）
 */

export const JOB_DIRS = {
  localRoot: 'data/projects',
  remoteBase: '/data/gpfs03/mdye/projects/test',
};

export interface NodeGroup {
  queue: string;
  prefix: string;
  start: number;
  end: number;
  coresPerNode: number;
  walltimeDays: number | null;
  cpuModel: string;
  cpuFreq: string;
  suspendRisk: SuspendRisk;
  paid: boolean;
  price: number;
}

/** 与后端 servers.json node_groups 保持一致的节点映射（前端离线兜底） */
export const NODE_GROUPS: NodeGroup[] = [
  {
    queue: 'normal_2week',
    prefix: 'b',
    start: 1,
    end: 14,
    coresPerNode: 48,
    walltimeDays: 14,
    cpuModel: 'Intel E5',
    cpuFreq: '12.5',
    suspendRisk: 'low',
    paid: false,
    price: 0,
  },
  {
    queue: 'ocean_530_1day',
    prefix: 'hd',
    start: 1,
    end: 28,
    coresPerNode: 24,
    walltimeDays: 1,
    cpuModel: 'Intel Platinum',
    cpuFreq: '15',
    suspendRisk: 'medium',
    paid: false,
    price: 0,
  },
  {
    queue: 'ocean6226R_1day',
    prefix: 'hd',
    start: 29,
    end: 41,
    coresPerNode: 32,
    walltimeDays: 1,
    cpuModel: 'Intel Platinum',
    cpuFreq: '15',
    suspendRisk: 'high',
    paid: false,
    price: 0,
  },
  {
    queue: 'normal_1day_new',
    prefix: 's',
    start: 6,
    end: 18,
    coresPerNode: 24,
    walltimeDays: 1,
    cpuModel: 'Intel Platinum',
    cpuFreq: '15',
    suspendRisk: 'low',
    paid: false,
    price: 0,
  },
  {
    queue: 'charge',
    prefix: 's',
    start: 19,
    end: 30,
    coresPerNode: 32,
    walltimeDays: null,
    cpuModel: 'Intel Platinum',
    cpuFreq: '15',
    suspendRisk: 'low',
    paid: true,
    price: 0.015,
  },
];

export function formatWalltime(days: number | null): string {
  if (days == null) return '无限制';
  if (days >= 7 && days % 7 === 0) return `${days / 7}周`;
  return `${days}天`;
}

export function expandNodeGroups(groups: NodeGroup[] = NODE_GROUPS): ClusterNode[] {
  const nodes: ClusterNode[] = [];
  for (const g of groups) {
    for (let i = g.start; i <= g.end; i += 1) {
      nodes.push({
        name: `${g.prefix}${String(i).padStart(3, '0')}`,
        queue: g.queue,
        maxCores: g.coresPerNode,
        runningCores: 0,
        suspendedCores: 0,
        unavailCores: 0,
        idleCores: g.coresPerNode,
        status: 'ok',
        cpuModel: g.cpuModel,
        cpuFreq: g.cpuFreq,
        walltime: formatWalltime(g.walltimeDays),
        suspendRisk: g.suspendRisk,
        paid: g.paid,
        price: g.price,
      });
    }
  }
  return nodes;
}

function hashRatio(name: string, salt = 'vasp'): number {
  let h = 0;
  const s = `${name}:${salt}`;
  for (let i = 0; i < s.length; i += 1) {
    h = (h * 31 + s.charCodeAt(i)) >>> 0;
  }
  return 0.15 + (h % 8000) / 10000;
}

/** 生成确定性的模拟负载（离线兜底） */
export function simulateFallbackSnapshot(): ClusterSnapshot {
  const nodes = expandNodeGroups().map((n, idx) => {
    const ratio = hashRatio(n.name);
    if (idx % 9 === 3) {
      return { ...n, status: 'unavail' as NodeStatus, unavailCores: n.maxCores, idleCores: 0 };
    }
    let running = Math.round(n.maxCores * ratio);
    let status: NodeStatus = 'ok';
    if (idx % 7 === 4) {
      running = n.maxCores;
      status = 'busy';
    }
    const suspended = idx % 5 === 2 ? Math.round(n.maxCores * 0.04) : 0;
    const idle = Math.max(0, n.maxCores - running - suspended);
    if (status === 'ok' && idle === 0) status = 'busy';
    else if (running > 0 && idle < running) status = 'warning';
    return { ...n, status, runningCores: running, suspendedCores: suspended, idleCores: idle };
  });
  return {
    source: 'mock',
    error: '后端不可用，使用内置映射模拟',
    queriedAt: new Date().toISOString(),
    nodes,
    queues: summarizeQueues(nodes),
  };
}

export function summarizeQueues(nodes: ClusterNode[]): ClusterQueueSummary[] {
  const byQueue = new Map<string, ClusterNode[]>();
  for (const n of nodes) {
    const list = byQueue.get(n.queue) ?? [];
    list.push(n);
    byQueue.set(n.queue, list);
  }
  const queues: ClusterQueueSummary[] = [];
  for (const [queue, members] of byQueue) {
    const total = members.reduce((s, m) => s + m.maxCores, 0);
    const running = members.reduce((s, m) => s + m.runningCores, 0);
    const idle = members.reduce((s, m) => s + m.idleCores, 0);
    const first = members[0];
    queues.push({
      queue,
      walltime: first.walltime,
      coresPerNode: first.maxCores,
      cpuModel: first.cpuModel,
      cpuFreq: first.cpuFreq,
      suspendRisk: first.suspendRisk,
      paid: first.paid,
      price: first.price,
      nodeCount: members.length,
      totalCores: total,
      runningCores: running,
      idleCores: idle,
      busyPercent: total ? Math.round((running / total) * 1000) / 10 : 0,
    });
  }
  return queues;
}

/** 队列/分区选项：LSF 用真实映射队列，Slurm 用通用分区 */
export const QUEUE_OPTIONS: Record<ScriptFormat, QueueOption[]> = {
  lsf: NODE_GROUPS.map((g) => ({
    value: g.queue,
    label: g.queue,
    hint: `${formatWalltime(g.walltimeDays)} · ${g.coresPerNode}核/节点` +
      (g.paid ? ` · 付费 ${g.price}元/核时` : '') +
      (g.suspendRisk === 'high' ? ' · 易挂起' : g.suspendRisk === 'medium' ? ' · 有挂起风险' : ''),
  })),
  slurm: [
    { value: 'normal', label: 'normal', hint: '默认分区' },
    { value: 'express', label: 'express', hint: '快速测试分区' },
    { value: 'bigmem', label: 'bigmem', hint: '大内存分区' },
  ],
};

/** 推荐核数：健康节点（status=ok）最大空闲核数 */
export function recommendCores(nodes: ClusterNode[]): number {
  return nodes
    .filter((n) => n.status === 'ok')
    .reduce((max, n) => Math.max(max, n.idleCores), 1);
}

/** 根据选择的队列过滤节点 */
export function nodesForQueue(queue: string, nodes: ClusterNode[]): ClusterNode[] {
  return nodes.filter((n) => n.queue === queue);
}

/** 生成 LSF / Slurm 提交脚本 */
export function buildSubmitScript(opts: SubmitScriptOptions): string {
  const { format, jobName, queue, cores, remoteDir } = opts;
  if (format === 'slurm') {
    return `#!/bin/bash
#SBATCH --job-name=${jobName}
#SBATCH --partition=${queue}
#SBATCH --ntasks=${cores}
#SBATCH --output=%j.out
#SBATCH --error=%j.err

module load vasp/6.4.1
cd ${remoteDir}

srun vasp_std`;
  }
  return `#!/bin/bash
#BSUB -J ${jobName}
#BSUB -q ${queue}
#BSUB -n ${cores}
#BSUB -o %J.out
#BSUB -e %J.err

module load vasp/6.4.1
cd ${remoteDir}

mpirun -np ${cores} vasp_std`;
}
