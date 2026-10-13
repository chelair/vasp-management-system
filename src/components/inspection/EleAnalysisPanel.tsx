import { useState } from 'react';
import { App, Button, Descriptions, Dropdown, Tooltip } from 'antd';
import PdosModal from './PdosModal';
import { clearPdos, fetchPdosStatus } from '../../api/jobs';
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
  const aa = detail.available_analyses;

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
