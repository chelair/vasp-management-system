import { Button, Card, Tag, Tooltip } from 'antd';
import { ReloadOutlined, RollbackOutlined, SyncOutlined } from '@ant-design/icons';
import type { TaskInputState } from '../../api/jobs';

interface Props {
  input: TaskInputState | null;
  syncing?: boolean;
  onSync: () => void;
  onRevert: (file: 'INCAR' | 'KPOINTS') => void;
}

/**
 * 输入文件来源横幅（v0.8.2）：本次计算参数从哪来、什么时候同步的、
 * 有哪些改动待生效（改动只在下一次续算时应用，不改运行中的作业）。
 */
export default function InputSourceBanner({ input, syncing, onSync, onRevert }: Props) {
  const source = input?.source ?? null;
  const pending = (input?.changes ?? []).filter((c) => !c.applied_at);
  const applied = input?.last_applied?.items ?? [];

  return (
    <Card size="small" className="job-card input-source">
      <div className="input-source__row">
        <div className="input-source__meta">
          <Tag color={input?.synced ? 'processing' : 'default'} bordered={false}>
            {input?.synced ? '本次计算的输入参数' : '未同步（显示本地/默认值）'}
          </Tag>
          <span>
            提交目录：<code className="path-cell">{source?.con || '主目录'}</code>
            {source?.job_id ? ` · 作业 ${source.job_id}` : ''}
            {source?.synced_at ? ` · ${source.synced_at.replace('T', ' ').slice(5, 16)}` : ''}
          </span>
        </div>
        <Tooltip title="从远端最新计算目录重新读取 INCAR / KPOINTS / POSCAR / CONTCAR">
          <Button size="small" icon={<SyncOutlined />} loading={syncing} onClick={onSync}>
            同步最新参数
          </Button>
        </Tooltip>
      </div>

      {pending.length > 0 && (
        <div className="input-source__pending">
          <div className="input-source__pending-title">
            <ReloadOutlined /> 待生效修改 {pending.length} 项 · 将在<b>下次续算</b>时写入新目录
          </div>
          {pending.map((c) => (
            <div key={`${c.file}-${c.key}`} className="input-source__change">
              <Tag color="orange" bordered={false}>
                {c.file}
              </Tag>
              <span className="input-source__change-key">{c.key}</span>
              <span className="input-source__change-val">{c.from || '—'}</span>
              <span className="input-source__change-arrow">→</span>
              <span className="input-source__change-val input-source__change-val--new">{c.to}</span>
              <Button
                type="text"
                size="small"
                icon={<RollbackOutlined />}
                onClick={() => onRevert(c.file)}
              >
                撤销
              </Button>
            </div>
          ))}
        </div>
      )}

      {applied.length > 0 && (
        <div className="input-source__applied">
          上次续算已应用 {applied.length} 项：
          {applied.map((c) => `${c.key} ${c.from}→${c.to}`).join('；')}
          （{input?.last_applied?.con}）
        </div>
      )}
    </Card>
  );
}
