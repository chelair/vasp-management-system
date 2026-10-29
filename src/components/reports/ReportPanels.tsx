/**
 * 报告正文里的**看板组件**（2026-10-15，v0.9.62）：自由能路径 / NEB 能垒。
 *
 * 这两块在报告里原本是后端 `report_panels.py` 生成的静态 SVG（统计卡 + 图例 + 图
 * 拼在一张图里），现在报告页把它们就地换成「HTML 统计卡 + 图例 + ECharts 图」——
 * **版式与读数完全对齐原静态图**（同样的 4 张卡、同样的图例三项、同样的边距），
 * 只是图上可以悬停读数（自由能出信息卡、NEB 头部出读数），点击可打开对应的结构三视图。
 * 导出的单文件 HTML 仍用后端静态 SVG 兜底（与能量/力曲线同一口径）。
 */

import { useMemo } from 'react';

import NebEnergyCurve, { type NebCurveImage } from '../inspection/NebEnergyCurve';
import PathStepChart from '../inspection/PathStepChart';
import type { FreeEnergyStructure } from '../../api/inspections';
import ReportNeb3D from './ReportNeb3D';

/** 一排统计卡（对齐静态图 `stat_cards`：浅渐变底 + 圆角 12 + 三行文字） */
export function ReportStatCards({
  cards,
}: {
  cards: { label: string; value: string; sub?: string }[];
}) {
  return (
    <div className="report-cards">
      {cards.map((card) => (
        <div className="report-card" key={card.label}>
          <span className="report-card__label">{card.label}</span>
          <strong className="report-card__value">{card.value}</strong>
          {card.sub ? <span className="report-card__sub">{card.sub}</span> : null}
        </div>
      ))}
    </div>
  );
}

const signed = (v: number | null | undefined, digits = 3) =>
  v == null || !Number.isFinite(v) ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
const fixed = (v: number | null | undefined, digits = 3) =>
  v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);

/** 报告结构化数据里的工作量与工期（`basic_info.workload`） */
export interface ReportWorkload {
  total_units?: number;
  done_units?: number;
  remaining_units?: number;
  core_hours_total?: number;
  core_hours_done?: number;
  core_hours_remaining?: number;
  core_hours_per_weight?: number;
  core_hours_per_day?: number;
  max_cores?: number;
  utilization?: number;
  eta_days?: number | null;
  eta_at?: string | null;
}

/** 报告结构化数据里的进度分块（`basic_info.progress_segments[]`） */
export interface ReportProgressSegment {
  label?: string;
  color?: string;
  count?: number;
  done?: number;
  weight?: number;
  done_weight?: number;
  percent?: number;
  share?: number;
}

/**
 * 项目进度看板（v0.9.62）：原 `charts/progress.svg`（后端 `segmented_progress_chart`）
 * 就地换成 DOM 版 —— **版式与文案逐句对齐**：标题 + 右侧大百分比 + 主进度条 +
 * 「块宽 = 当量占比」的分段条 + 每类型的图例行 + 工作量/算力两行说明 + 底部口径说明。
 */
export function ProjectProgressPanel({
  segments,
  mainPercent,
  taskStats,
  workload,
}: {
  segments: ReportProgressSegment[];
  mainPercent?: number;
  taskStats?: { completed?: number; total?: number; archived?: number };
  workload?: ReportWorkload;
}) {
  const percent = Number(mainPercent ?? 0);
  const totalShare =
    segments.reduce((sum, seg) => sum + Number(seg.share || 0), 0) || 1;
  const detail =
    taskStats && taskStats.total != null
      ? `当量加权主进度 · 未归档任务 ${taskStats.completed ?? 0}/${taskStats.total} 已完成` +
        (taskStats.archived ? `，${taskStats.archived} 个已关闭` : '')
      : '';
  const w = workload;
  const notes: string[] = [];
  if (w && w.total_units != null) {
    notes.push(
      `折算工作量 ${Number(w.total_units).toFixed(1)} 当量 ≈ ${Number(
        w.core_hours_total ?? 0,
      ).toLocaleString('en-US', { maximumFractionDigits: 0 })} 核时（1 当量 ${Number(
        w.core_hours_per_weight ?? 0,
      ).toFixed(0)} 核时）· 已完成 ${Number(w.core_hours_done ?? 0).toLocaleString('en-US', {
        maximumFractionDigits: 0,
      })} · 剩余 ${Number(w.core_hours_remaining ?? 0).toLocaleString('en-US', {
        maximumFractionDigits: 0,
      })} 核时`,
    );
    const eta =
      w.eta_days != null && Number(w.core_hours_remaining ?? 0) > 0
        ? ` → 按当量估算还需 ${Number(w.eta_days).toFixed(1)} 天，预计 ${w.eta_at ?? ''} 完成`
        : ' → 剩余工作量为 0，项目已收尾';
    notes.push(
      `有效算力 ${Number(w.core_hours_per_day ?? 0).toLocaleString('en-US', {
        maximumFractionDigits: 0,
      })} 核时/天（${Number(w.max_cores ?? 0).toFixed(0)} 核 × 24h × ${(
        Number(w.utilization ?? 0) * 100
      ).toFixed(0)}%）${eta}`,
    );
  }

  if (!segments.length && !detail) return null;

  return (
    <div className="report-progress">
      <div className="report-progress__head">
        <span className="report-progress__title">项目进度</span>
        <strong className="report-progress__percent">{percent.toFixed(1)}%</strong>
      </div>
      {detail ? <p className="report-progress__detail">{detail}</p> : null}
      <div className="report-progress__main">
        <i style={{ width: `${Math.max(0, Math.min(percent, 100))}%` }} />
      </div>
      <div className="report-progress__segs">
        {segments.map((seg) => (
          <div
            className="report-progress__seg"
            key={seg.label ?? ''}
            style={{
              flexGrow: Number(seg.share || 0) / totalShare,
              background: `${seg.color ?? '#5B8DEF'}29`,
            }}
            title={`${seg.label ?? ''} ${seg.done ?? 0}/${seg.count ?? 0}`}
          >
            <i
              style={{
                width: `${Math.max(0, Math.min(Number(seg.percent || 0), 100))}%`,
                background: seg.color ?? '#5B8DEF',
              }}
            />
          </div>
        ))}
      </div>
      <div className="report-progress__legend">
        {segments.map((seg) => (
          <span className="report-progress__legend-item" key={seg.label ?? ''}>
            <span
              className="report-legend-dot"
              style={{ background: seg.color ?? '#5B8DEF' }}
            />
            {`${seg.label ?? ''} ${seg.done ?? 0}/${seg.count ?? 0} · ${Number(
              seg.percent || 0,
            ).toFixed(0)}% · 当量 ${Number(seg.weight || 0).toFixed(1)}（占 ${Number(
              seg.share || 0,
            ).toFixed(0)}%）`}
          </span>
        ))}
      </div>
      {notes.map((note) => (
        <p className="report-progress__note" key={note}>
          {note}
        </p>
      ))}
      <p className="report-progress__foot">
        块宽 = 该类型的任务当量占比；当量按任务类型权重折算（结构优化 1 · 频率矫正 1 · NEB 5 ·
        电子结构 0.4）
      </p>
    </div>
  );
}

/** 报告结构化数据里的自由能路径（`science.free_energy[]`） */
export interface ReportFreeEnergyPath {
  group_id?: string;
  group_name?: string;
  structures?: {
    structure_label?: string;
    opt_task_id?: string;
    dft_energy_ev?: number | null;
    correction_ev?: number | null;
    free_energy_ev?: number | null;
    converged?: boolean;
    corrected?: boolean;
    dialog?: string | null;
  }[];
}

/** 自由能路径看板：4 张统计卡 + 图例 + 台阶图（与巡检详情同版式，点击台阶看结构三视图） */
export function FreeEnergyReportPanel({
  path,
  onOpenDialog,
}: {
  path: ReportFreeEnergyPath;
  onOpenDialog?: (dialogId: string) => void;
}) {
  const structures = path.structures ?? [];
  const mapped = useMemo<FreeEnergyStructure[]>(
    () =>
      structures.map((s) => ({
        task_id: String(s.opt_task_id ?? ''),
        structure_label: String(s.structure_label ?? ''),
        dft_energy: s.dft_energy_ev ?? null,
        correction: s.correction_ev ?? null,
        free_energy: s.free_energy_ev ?? null,
        converged: Boolean(s.converged),
        corrected: Boolean(s.corrected),
      })),
    [structures],
  );

  const cards = useMemo(() => {
    const withEnergy = structures.filter((s) => s.free_energy_ev != null);
    const ref = withEnergy.length ? Number(withEnergy[0].free_energy_ev) : null;
    const rels = withEnergy.map((s) => ({
      rel: Number(s.free_energy_ev) - Number(ref),
      item: s,
    }));
    const top = rels.length ? rels.reduce((a, b) => (b.rel > a.rel ? b : a)) : null;
    const corrected = structures.filter((s) => s.corrected).length;
    const converged = structures.filter((s) => s.converged).length;
    const total = structures.length;
    return [
      {
        label: '中间体数量',
        value: String(total),
        sub: total ? `结构 1 – ${total}` : '—',
      },
      {
        label: '矫正项完成度',
        value: `${corrected} / ${total}`,
        sub: total && corrected === total ? '全部已矫正' : '部分中间体待矫正',
      },
      {
        label: '结构优化收敛',
        value: `${converged} / ${total}`,
        sub: total && converged === total ? '全部已收敛' : '存在未收敛中间体',
      },
      {
        label: '最高相对能',
        value: signed(top?.rel ?? null),
        sub: top ? `结构 ${top.item.structure_label}` : '暂无对比数据',
      },
    ];
  }, [structures]);

  const referenceLabel =
    structures.find((s) => s.free_energy_ev != null)?.structure_label ?? '1';
  const dialogByTask = useMemo(() => {
    const map = new Map<string, string>();
    structures.forEach((s) => {
      if (s.opt_task_id && s.dialog) map.set(String(s.opt_task_id), String(s.dialog));
    });
    return map;
  }, [structures]);

  if (!structures.length) return null;

  return (
    <div className="report-panel">
      <ReportStatCards cards={cards} />
      <div className="report-panel__legend">
        <span className="report-legend-item">
          <span className="report-legend-dot" style={{ background: '#2C9DA8' }} />
          收敛且已矫正
        </span>
        <span className="report-legend-item">
          <span className="report-legend-dot" style={{ background: '#E8A33D' }} />
          未收敛 / 未矫正
        </span>
        <span className="report-legend-item">
          <span className="report-legend-dot report-legend-dot--empty" />
          无数据
        </span>
        <span className="report-panel__legend-ref">
          相对值以结构 {referenceLabel} 为参考 · {path.group_name ?? path.group_id ?? ''} ·
          点台阶看结构三视图
        </span>
      </div>
      <PathStepChart
        structures={mapped}
        onSelect={(taskId) => {
          const dialogId = dialogByTask.get(taskId);
          if (dialogId && onOpenDialog) onOpenDialog(dialogId);
        }}
      />
    </div>
  );
}

/** 报告结构化数据里的 NEB 任务（`science.neb[]`） */
export interface ReportNebItem {
  task_id?: string;
  task_name?: string;
  barrier_ev?: number | null;
  transition_state_image?: string | null;
  image_count?: number;
  images?: {
    label?: string;
    relative_energy_ev?: number | null;
    energy_ev?: number | null;
    max_force_ev_per_a?: number | null;
    dialog?: string | null;
    cif?: string | null;
  }[];
}

/** NEB 能垒看板：4 张统计卡 + 图例 + 相对能垒曲线（点击映像点看该映像三视图） */
export function NebReportPanel({
  item,
  onOpenDialog,
}: {
  item: ReportNebItem;
  onOpenDialog?: (dialogId: string) => void;
}) {
  const images = item.images ?? [];
  const mapped = useMemo<NebCurveImage[]>(
    () =>
      images.map((img) => ({
        label: String(img.label ?? ''),
        relative: img.relative_energy_ev ?? null,
        max_force: img.max_force_ev_per_a ?? null,
        energy: img.energy_ev ?? null,
      })),
    [images],
  );

  const saddle = useMemo(() => {
    const withEnergy = images
      .map((img, index) => ({ index, rel: img.relative_energy_ev }))
      .filter((x) => x.rel != null);
    if (!withEnergy.length) return -1;
    return withEnergy.reduce((a, b) => (Number(b.rel) > Number(a.rel) ? b : a)).index;
  }, [images]);

  const cards = useMemo(() => {
    const count = images.length;
    const saddleRel = saddle >= 0 ? (images[saddle].relative_energy_ev ?? null) : null;
    const withForce = images
      .map((img, index) => ({ index, force: img.max_force_ev_per_a }))
      .filter((x) => x.force != null);
    const forceIndex = withForce.length
      ? withForce.reduce((a, b) => (Number(b.force) > Number(a.force) ? b : a)).index
      : -1;
    const lastRel = count ? (images[count - 1].relative_energy_ev ?? null) : null;
    return [
      {
        label: '映像数量',
        value: String(count),
        sub: count >= 2 ? `端点 2 + 中间 ${count - 2}` : '含端点',
      },
      {
        label: '能垒 Ea',
        value: signed(saddleRel),
        sub: saddle >= 0 ? `最高点：映像 ${images[saddle].label}` : '暂无数据',
      },
      {
        label: '最大受力',
        value: fixed(forceIndex >= 0 ? images[forceIndex].max_force_ev_per_a : null, 3),
        sub: forceIndex >= 0 ? `映像 ${images[forceIndex].label}（eV/Å）` : '暂无数据',
      },
      {
        label: '末态相对能',
        value: signed(lastRel),
        sub:
          lastRel != null && Math.abs(Number(lastRel)) < 0.01
            ? '与初态基本一致'
            : '相对初态（映像 00）',
      },
    ];
  }, [images, saddle]);

  if (!images.length) return null;
  if (images.some(image => image.cif)) return <ReportNeb3D item={item} />;

  return (
    <div className="report-panel">
      <ReportStatCards cards={cards} />
      <div className="report-panel__legend">
        <span className="report-legend-item">
          <span className="report-legend-dot" style={{ background: '#7B61D6' }} />
          相对能垒（nebef.pl）
        </span>
        <span className="report-legend-item">
          <span className="report-legend-dot" style={{ background: '#D9535B' }} />
          鞍点（能垒最高）
        </span>
        <span className="report-panel__legend-ref">
          横轴为 NEB 映像（{images[0]?.label ?? '00'} = 初态，{images[images.length - 1]?.label}{' '}
          = 末态）· 点数据点看映像三视图
        </span>
      </div>
      <NebEnergyCurve
        images={mapped}
        selected={-1}
        saddle={saddle}
        height={300}
        onSelect={(index) => {
          const dialogId = images[index]?.dialog;
          if (dialogId && onOpenDialog) onOpenDialog(String(dialogId));
        }}
      />
    </div>
  );
}
