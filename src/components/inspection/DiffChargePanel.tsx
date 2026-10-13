/**
 * 差分电荷面板（2026-10-14）：入口在**巡检详情**的「电子结构分析 → 差分电荷」标签。
 *
 * 用户口径：
 * - 第一次点击依次做四件事：① 远端校验文件完整性（完整结构 + 各分块 CHGCAR，
 *   大小差别应 < 1%）② VTST 算 `charge_diff` ③ 回传 `charge_diff` 文件
 *   ④ 导入 VESTA 导出 a/b/c 三轴图 → 图片直接呈现在这里；
 * - 之后每次加载按阶梯：**本地图 → 本地差分文件 → 远端差分文件 → 远端可算**；
 * - CHGCAR 大、VESTA 慢：全链路异步 + 阶段上报，中断后再点一次只补缺的那步。
 *
 * 实现要点：状态由后端 `charge_diff` 链路给（`/charge-diff/status`），
 * 本组件只做"展示 + 轮询 + 触发"；图片走带鉴权头的 fetch → blob URL（见 `requestBlobUrl`）。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Image, Popconfirm, Progress, Spin, Tag } from 'antd';
import { DeleteOutlined, PictureOutlined, ReloadOutlined } from '@ant-design/icons';

import {
  clearChargeDiff,
  fetchChargeDiffImage,
  fetchChargeDiffStatus,
  triggerChargeDiff,
} from '../../api/jobs';
import type { ChargeDiffStatus } from '../../types';

interface Props {
  taskId: string;
  taskName?: string;
  /** 该 ele 任务下是否已经划过差分电荷分块（没划就没得算） */
  hasBlocks: boolean;
}

const AXES: Array<'a' | 'b' | 'c'> = ['a', 'b', 'c'];

/** 阶梯状态 → 展示文案（与 backend/charge_diff.py 的 STATE_* 一致） */
const STATE_LABELS: Record<string, string> = {
  images: '本地已有三视图',
  local_diff: '本地已有 CHGCAR_diff（可直接出图）',
  remote_diff: '远端已有 CHGCAR_diff（回传即可）',
  remote_ready: '远端分块齐全，可以计算',
  remote_incomplete: '远端文件不完整',
  no_blocks: '还没有差分电荷分块',
};

function formatBytes(bytes?: number): string {
  if (!bytes) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function formatTime(stamp?: number): string {
  if (!stamp) return '—';
  return new Date(stamp * 1000).toLocaleString();
}

export default function DiffChargePanel({ taskId, taskName, hasBlocks }: Props) {
  const { message } = App.useApp();
  const [status, setStatus] = useState<ChargeDiffStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  /** 三视图 blob URL（卸载 / 重新出图时要 revoke） */
  const [urls, setUrls] = useState<Partial<Record<'a' | 'b' | 'c', string>>>({});
  const pollRef = useRef<number | null>(null);
  const urlsRef = useRef<Partial<Record<'a' | 'b' | 'c', string>>>({});
  const aliveRef = useRef(true);
  /** 已成功取过图的指纹（taskId + image_mtime）：避免同一批图被重复拉 3 次 */
  const loadedStampRef = useRef('');

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const revokeUrls = useCallback(() => {
    for (const url of Object.values(urlsRef.current)) {
      if (url) URL.revokeObjectURL(url);
    }
    urlsRef.current = {};
    loadedStampRef.current = '';
  }, []);

  const loadImages = useCallback(async () => {
    const fingerprint = `${taskId}:${status?.local?.image_mtime ?? ''}`;
    if (loadedStampRef.current === fingerprint) return;
    try {
      const entries = await Promise.all(
        AXES.map(async (axis) => [axis, await fetchChargeDiffImage(taskId, axis)] as const),
      );
      if (!aliveRef.current) {
        entries.forEach(([, url]) => URL.revokeObjectURL(url));
        return;
      }
      revokeUrls();
      const next: Partial<Record<'a' | 'b' | 'c', string>> = {};
      for (const [axis, url] of entries) next[axis] = url;
      urlsRef.current = next;
      setUrls(next);
      loadedStampRef.current = fingerprint;
    } catch (e) {
      if (aliveRef.current) {
        setError(e instanceof Error ? e.message : '三视图加载失败');
      }
    }
  }, [revokeUrls, status?.local?.image_mtime, taskId]);

  /** 拉一次状态；`remote=true` 时才连远端（阶梯最后一步） */
  const load = useCallback(
    async (remote: boolean) => {
      try {
        const data = await fetchChargeDiffStatus(taskId, { remote });
        if (!aliveRef.current) return;
        setStatus(data);
        setError(data.status === 'failed' ? String(data.error || '计算失败') : '');
        if (data.status === 'running') {
          setBusy(true);
        }
        return data;
      } catch (e) {
        if (aliveRef.current) {
          setError(e instanceof Error ? e.message : '读取差分电荷状态失败');
        }
        return null;
      } finally {
        if (aliveRef.current) setLoading(false);
      }
    },
    [taskId],
  );

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const data = await load(false);
      if (!data) return;
      if (data.status !== 'running') {
        stopPolling();
        setBusy(false);
        if (data.status === 'done') {
          message.success('差分电荷计算完成');
          await load(true);
          await loadImages();
        }
      }
    }, 1500);
  }, [load, loadImages, message, stopPolling]);

  // 首次挂载：先看本地阶梯（零 SSH）；本地什么都没有才回退探测远端
  useEffect(() => {
    aliveRef.current = true;
    // 没划块就没得算：不连后端、不探远端（这条分支只显示"先去作业管理划块"）
    if (!hasBlocks) {
      setLoading(false);
      return () => {
        aliveRef.current = false;
        stopPolling();
        revokeUrls();
      };
    }
    (async () => {
      const local = await load(false);
      if (!aliveRef.current) return;
      if (local?.status === 'running') {
        startPolling();
        return;
      }
      if (local && !local.local?.has_images && !local.local?.has_diff) {
        await load(true); // 阶梯最后一步：远端看差分类文件 / 分块完整性
      }
    })();
    return () => {
      aliveRef.current = false;
      stopPolling();
      revokeUrls();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // 有图就取图（image_mtime 变了 = 重新出过图，重新取）
  useEffect(() => {
    if (hasBlocks && status?.local?.has_images) {
      void loadImages();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasBlocks, status?.local?.has_images, status?.local?.image_mtime, taskId]);

  const analyze = useCallback(
    async (force: boolean) => {
      setBusy(true);
      setError('');
      try {
        await triggerChargeDiff(taskId, { force });
        message.info(force ? '已重新开始计算差分电荷' : '已开始计算差分电荷');
        await load(false);
        startPolling();
      } catch (e) {
        setBusy(false);
        setError(e instanceof Error ? e.message : '触发失败');
      }
    },
    [load, message, startPolling, taskId],
  );

  const clearAll = useCallback(
    async (imagesOnly: boolean) => {
      try {
        await clearChargeDiff(taskId, imagesOnly);
        revokeUrls();
        setUrls({});
        message.success(imagesOnly ? '已清除三视图' : '已清除本地差分电荷结果');
        // 整体清除后本地阶梯为空 → 顺带探一次远端（远端差分文件通常还在，可只补回传）
        await load(!imagesOnly);
      } catch (e) {
        setError(e instanceof Error ? e.message : '清除失败');
      }
    },
    [load, message, revokeUrls, taskId],
  );

  if (!hasBlocks) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <span>
            该电子结构任务还没有差分电荷分块
            <br />
            <span className="preview-note">
              先在「作业管理 → 该任务 → 差分电荷计算」里按原子划块并提交各分块计算，
              这里才能算差分电荷
            </span>
          </span>
        }
      />
    );
  }

  const local = status?.local;
  const remote = status?.remote;
  const running = status?.status === 'running' || busy;
  const record = status?.charge_diff ?? null;
  const hasImages = Boolean(local?.has_images);
  const stateLabel = STATE_LABELS[String(status?.state || '')] || '—';
  const bytesTotal = status?.bytes_total ?? 0;
  const bytesDone = status?.bytes_done ?? 0;
  const percent =
    bytesTotal > 0 ? Math.min(100, Math.round((bytesDone / bytesTotal) * 100)) : 0;

  return (
    <div>
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="当前状态">
          {running ? (
            <Tag color="processing">
              {status?.stage_label || '计算中'}
            </Tag>
          ) : hasImages ? (
            <Tag color="success">已完成（三视图已生成）</Tag>
          ) : local?.has_diff ? (
            <Tag color="warning">本地已有差分文件，还差三视图</Tag>
          ) : (
            <Tag>{stateLabel}</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="本地差分文件">
          {local?.has_diff
            ? `diffcharge_files/chgfiles/CHGCAR_diff.vasp（${formatBytes(
                local.diff_bytes,
              )}，${formatTime(local.diff_mtime)}）`
            : '—'}
        </Descriptions.Item>
        {remote && (
          <Descriptions.Item label="远端检查">
            {remote.reason || STATE_LABELS[String(remote.state || '')] || '—'}
            {remote.integrity && !remote.integrity.ok ? (
              <span className="preview-note"> （校验未通过）</span>
            ) : null}
          </Descriptions.Item>
        )}
        {record?.ok && record.elapsed_seconds ? (
          <Descriptions.Item label="上次计算">
            {formatBytes(record.bytes)} · 共 {record.elapsed_seconds} s
            {record.render_seconds ? `（其中出图 ${record.render_seconds} s）` : ''}
            {record.reused_remote ? ' · 远端已有差分，未重算' : ''}
          </Descriptions.Item>
        ) : null}
      </Descriptions>

      <p className="preview-note" style={{ marginBottom: 12 }}>
        点击后依次执行：远端校验三个 CHGCAR 的完整性（大小差别 &lt; 1%）→ VTST
        <code>chgsum.pl</code> + <code>chgdiff.pl</code> 算差分 → 回传
        <code>CHGCAR_diff</code> → VESTA 导入并导出 a / b / c 三轴图。
        大文件（200MB+）耗时较长，可离开页面；再次打开按「本地图 → 本地差分文件 →
        远端差分文件」补缺，不会重复搬运。
      </p>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <Button
          type="primary"
          icon={<PictureOutlined />}
          loading={running}
          onClick={() => void analyze(Boolean(hasImages))}
        >
          {hasImages ? '重新计算（含重出图）' : busy && !hasImages ? '计算中…' : '计算差分电荷'}
        </Button>
        {hasImages && (
          <Popconfirm
            title="只删除三视图？"
            description="本地 CHGCAR_diff 会保留，再点「计算差分电荷」只补出图（不再回传）。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => void clearAll(true)}
          >
            <Button icon={<DeleteOutlined />}>清除三视图</Button>
          </Popconfirm>
        )}
        {(local?.has_diff || hasImages) && (
          <Popconfirm
            title="清除本地差分电荷结果？"
            description="会删掉 CHGCAR_diff.vasp 与三视图；远端文件不动，重新点击会重新回传。"
            okText="清除"
            cancelText="取消"
            onConfirm={() => void clearAll(false)}
          >
            <Button danger icon={<ReloadOutlined />}>
              清除本地结果
            </Button>
          </Popconfirm>
        )}
      </div>

      {running && (
        <div style={{ marginBottom: 12 }}>
          {bytesTotal > 0 ? (
            <Progress
              percent={percent}
              status="active"
              format={() => `${formatBytes(bytesDone)} / ${formatBytes(bytesTotal)}`}
            />
          ) : (
            <span>
              <Spin size="small" /> {status?.stage_label || '处理中…'}
              {status?.elapsed_seconds ? `（已用 ${status.elapsed_seconds} s）` : ''}
            </span>
          )}
        </div>
      )}

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="差分电荷链路失败"
          description={error}
          action={
            <Button size="small" onClick={() => void analyze(false)}>
              重试
            </Button>
          }
        />
      ) : null}

      {hasImages ? (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {AXES.map((axis) => (
            <div key={axis} style={{ flex: '1 1 260px', minWidth: 240 }}>
              <div className="preview-note" style={{ marginBottom: 4 }}>
                沿 {axis} 轴看（点击可放大）
              </div>
              {urls[axis] ? (
                <Image
                  src={urls[axis]}
                  alt={`${taskName || '差分电荷'} ${axis} 轴视图`}
                  style={{ width: '100%', border: '1px solid #f0f0f0', borderRadius: 6 }}
                />
              ) : (
                <div style={{ padding: 24, textAlign: 'center' }}>
                  <Spin size="small" />
                </div>
              )}
            </div>
          ))}
        </div>
      ) : loading ? (
        <Spin />
      ) : (
        !running && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有差分电荷三视图：点上面的「计算差分电荷」"
          />
        )
      )}
    </div>
  );
}
