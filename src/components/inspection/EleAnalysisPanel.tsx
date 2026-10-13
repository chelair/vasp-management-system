import { useEffect, useState } from 'react';
import { App, Button, Descriptions, Dropdown, Tooltip } from 'antd';
import PdosModal from './PdosModal';
import { clearPdos, fetchPdosStatus } from '../../api/jobs';
import { fetchAvailableAnalyses } from '../../api/inspections';
import type { InspectionDetail } from '../../types';

interface Props {
  detail: InspectionDetail;
}

/** 电子结构任务分析面板：基础信息 + 可分析内容识别 + 分析入口 */
export default function EleAnalysisPanel({ detail }: Props) {
  const { message } = App.useApp();
  const [pdosOpen, setPdosOpen] = useState(false);
  /** 点「PDOS · 开始分析」进来的 → 没有结果时自动开跑；其它入口只展示 */
  const [pdosAutoStart, setPdosAutoStart] = useState(false);
  const [pdosBusy, setPdosBusy] = useState(false);
  /** 二级菜单里"有没有已有结果"（打开菜单时查一次，用于禁用"查看已有结果"） */
  const [pdosHasData, setPdosHasData] = useState<boolean | null>(null);
  /**
   * 可分析内容：详情载荷里不再带（那里探远端文件会让每次打开详情都慢 ~1s），
   * 改为**面板挂载后再拉**（面板本身也只在用户展开「电子结构分析」时才挂载）。
   */
  const [aa, setAa] = useState(detail.available_analyses ?? null);
  const [aaLoading, setAaLoading] = useState(!detail.available_analyses);
  useEffect(() => {
    if (detail.available_analyses) return;
    let cancelled = false;
    setAaLoading(true);
    fetchAvailableAnalyses(detail.task_id)
      .then((data) => {
        if (!cancelled) setAa(data as typeof aa);
      })
      .catch(() => {
        if (!cancelled) setAa(null);
      })
      .finally(() => {
        if (!cancelled) setAaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail.task_id, detail.available_analyses]);

  /**
   * PDOS 的**二级菜单**（2026-10-13 用户要求）：
   * 一级 = 电子结构分析里的「PDOS」；点开二级菜单后选「开始分析 / 查看已有结果 / 清除」，
   * **在点"开始分析"之前不弹任何窗口**。
   */
  const openPdosMenu = async () => {
    setPdosBusy(true);
    try {
      const st = await fetchPdosStatus(detail.task_id);
      setPdosHasData(st.has_data === true);
    } catch {
      setPdosHasData(null);
    } finally {
      setPdosBusy(false);
    }
  };

  const items = [
    { key: 'pdos', label: 'PDOS · 开始分析', available: aa?.pdos ?? false, reason: '需要 DOSCAR' },
    { key: 'bader', label: 'Bader', available: aa?.bader ?? false, reason: '需要 AECCAR0/1/2' },
    { key: 'cohp', label: 'COHP', available: aa?.cohp ?? false, reason: '开发中' },
    { key: 'work_function', label: '功函数', available: aa?.work_function ?? false, reason: '开发中' },
  ];

  return (
    <div>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="子类型">{detail.model_name || '—'}</Descriptions.Item>
        <Descriptions.Item label="远程目录">
          {detail.current_output?.dir || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="可分析内容">
          {aaLoading ? (
            <span className="preview-note">正在识别远端输出文件…</span>
          ) : (
            ['pdos', 'bader', 'cohp', 'work_function']
              .filter((key) => (aa as Record<string, boolean> | null)?.[key])
              .map((key) => ({ pdos: 'PDOS', bader: 'Bader', cohp: 'COHP', work_function: '功函数' })[key])
              .join(' / ') || '暂无（缺 DOSCAR/AECCAR/LOCPOT 等）'
          )}
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {items.map((it) => {
          const disabled = !it.available || it.reason === '开发中';
          return (
            <Tooltip
              key={it.key}
              title={
                it.reason === '开发中'
                  ? '该分析暂未实现'
                  : it.available
                    ? it.key === 'pdos'
                      ? '展开二级菜单：开始分析 / 查看已有结果 / 清除'
                      : '点击开始分析'
                    : it.reason
              }
            >
              {it.key === 'pdos' ? (
                <Dropdown
                  trigger={['click']}
                  onOpenChange={(openNow) => {
                    if (openNow) void openPdosMenu();
                  }}
                  menu={{
                    items: [
                      {
                        key: 'analyze',
                        label: pdosHasData ? '重新分析（重跑远端 vaspkit）' : '开始分析（远端 vaspkit 提取）',
                      },
                      { key: 'view', label: '查看已有结果', disabled: pdosHasData === false },
                      { type: 'divider' },
                      { key: 'clear', label: '清除本地分析结果', disabled: pdosHasData === false },
                    ],
                    onClick: async ({ key }) => {
                      if (key === 'analyze') {
                        setPdosAutoStart(true);
                        setPdosOpen(true);
                        return;
                      }
                      if (key === 'view') {
                        setPdosAutoStart(false);
                        setPdosOpen(true);
                        return;
                      }
                      if (key === 'clear') {
                        try {
                          const r = await clearPdos(detail.task_id);
                          setPdosHasData(false);
                          message.success(
                            r.removed.length ? `已清除：${r.removed.join('、')}` : '本地本来就没有分析结果',
                          );
                        } catch (e) {
                          message.error(e instanceof Error ? e.message : '清除失败');
                        }
                      }
                    },
                  }}
                >
                  <Button disabled={disabled} loading={pdosBusy}>
                    {it.label}
                    {!it.available ? '（文件缺失）' : ''}
                  </Button>
                </Dropdown>
              ) : (
                <Button disabled={disabled}>
                  {it.label}
                  {it.reason === '开发中' ? '（开发中）' : !it.available ? '（文件缺失）' : ''}
                </Button>
              )}
            </Tooltip>
          );
        })}
      </div>
      <PdosModal
        open={pdosOpen}
        taskId={detail.task_id}
        taskName={detail.model_name}
        autoStart={pdosAutoStart}
        onClose={() => {
          setPdosOpen(false);
          setPdosAutoStart(false);
        }}
      />
    </div>
  );
}
