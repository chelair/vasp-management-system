/**
 * 电子结构分析面板（2026-10-13 改版）。
 *
 * 用户口径："PDOS 等放到巡检的**一级菜单**里，放在电子结构分析章节；其他功能如 Bader、功函数
 * 放在和 PDOS 并列的标签上，点击对应标签切换分析视图，**切到那个加载那个**。"
 *
 * 结构：基础信息（子类型 / 远程目录 / 可分析内容）+ **并列的分析标签页**：
 *   [PDOS] [Bader] [COHP] [功函数]
 * - 标签页惰性挂载（antd Tabs 默认：切到才创建），切过一次后保留现场；
 * - "可分析内容"要探远端文件（~1s），所以**不随详情打开就拉** —— 首次切换标签时才去识别；
 * - PDOS 标签 = `PdosPanel`（分析 / 查看图表 / 重新分析 / 清除，功能与之前一致）；
 * - 其余标签是预留位：说明需要哪些输出文件、当前是否具备（不改变原有"未实现"行为）。
 */

import { useMemo, useState } from 'react';
import { Descriptions, Empty, Tabs, Tag } from 'antd';

import ErrorBoundary from '../common/ErrorBoundary';
import PdosPanel from './PdosPanel';
import { fetchAvailableAnalyses } from '../../api/inspections';
import type { InspectionDetail } from '../../types';

interface Props {
  detail: InspectionDetail;
}

/** 可分析内容（后端 /available-analyses 的返回） */
interface Analyses {
  pdos?: boolean;
  bader?: boolean;
  cohp?: boolean;
  work_function?: boolean;
  diff_charge?: boolean;
  remote_dir?: string;
}

/** 预留的分析类型（除 PDOS 外都还没实现，保持原状） */
const PLACEHOLDER_TABS = [
  { key: 'bader', label: 'Bader', needs: 'AECCAR0 / AECCAR1 / AECCAR2', tip: '电荷转移分析' },
  { key: 'cohp', label: 'COHP', needs: 'COHPCAR（ISYM=-1 + LORBIT）', tip: '键合分析' },
  { key: 'work_function', label: '功函数', needs: 'LOCPOT（LVHAR）', tip: '功函数 / 真空能级' },
] as const;

export default function EleAnalysisPanel({ detail }: Props) {
  const [activeTab, setActiveTab] = useState('pdos');
  /**
   * 可分析内容（要不要探远端文件）：详情载荷里不再带。
   * 首次**切换标签**时才拉（后端 120s 缓存），避免仅仅打开详情就连一次远端。
   */
  const [aa, setAa] = useState<Analyses | null>(
    (detail.available_analyses as Analyses | null) ?? null,
  );
  const [aaLoading, setAaLoading] = useState(false);

  const probe = () => {
    if (aa || aaLoading) return;
    setAaLoading(true);
    fetchAvailableAnalyses(detail.task_id)
      .then((data) => setAa(data as Analyses))
      .catch(() => setAa(null))
      .finally(() => setAaLoading(false));
  };

  const availableText = useMemo(() => {
    if (!aa) return aaLoading ? '正在识别远端输出文件…' : '切换标签后识别';
    const names = [
      aa.pdos ? 'PDOS' : '',
      aa.bader ? 'Bader' : '',
      aa.cohp ? 'COHP' : '',
      aa.work_function ? '功函数' : '',
    ].filter(Boolean);
    return names.length ? names.join(' / ') : '暂无（缺 DOSCAR / AECCAR / LOCPOT 等）';
  }, [aa, aaLoading]);

  return (
    <div>
      <ErrorBoundary title="电子结构分析面板出错了">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="子类型">{detail.model_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="远程目录">
            {detail.current_output?.dir || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="可分析内容">{availableText}</Descriptions.Item>
        </Descriptions>

        <Tabs
          activeKey={activeTab}
          onChange={(key) => {
            setActiveTab(key);
            probe(); // 切到标签时才去识别远端可分析内容（也首次挂载该标签内容）
          }}
          items={[
            {
              key: 'pdos',
              label: (
                <span>
                  PDOS
                  {aa && !aa.pdos ? <span className="preview-note">（缺 DOSCAR）</span> : null}
                </span>
              ),
              children: <PdosPanel taskId={detail.task_id} taskName={detail.model_name} />,
            },
            ...PLACEHOLDER_TABS.map((tab) => ({
              key: tab.key,
              label: (
                <span>
                  {tab.label}
                  {aa && !aa[tab.key as 'bader' | 'cohp' | 'work_function'] ? (
                    <span className="preview-note">（文件缺失）</span>
                  ) : null}
                </span>
              ),
              children: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <span>
                      {tab.tip} · 尚未实现（预留）
                      <br />
                      <span className="preview-note">
                        需要 {tab.needs}
                        {aa
                          ? aa[tab.key as 'bader' | 'cohp' | 'work_function']
                            ? '：当前输出文件已具备'
                            : '：当前输出文件缺失'
                          : '（切换本标签后会自动识别）'}
                      </span>
                    </span>
                  }
                />
              ),
            })),
          ]}
          tabBarExtraContent={
            aaLoading ? <Tag color="processing">识别中…</Tag> : null
          }
        />
      </ErrorBoundary>
    </div>
  );
}
