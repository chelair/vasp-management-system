import { Button, Card, Collapse, Tag, Tooltip } from 'antd';
import { ReloadOutlined, RollbackOutlined, SyncOutlined } from '@ant-design/icons';
import type { TaskInputChange, TaskInputState } from '../../api/jobs';

interface Props {
  input: TaskInputState | null;
  syncing?: boolean;
  onSync: () => void;
  /** 撤销单项待生效修改（只回滚这一项；主开关的依赖参数会一起回滚） */
  onRevertChange: (change: TaskInputChange) => void;
  /** 撤销这些文件的全部待生效修改（按传入顺序逐个撤销） */
  onRevertFiles: (files: ('INCAR' | 'KPOINTS')[]) => void;
}

/**
 * 输入文件来源横幅（v0.8.2）：本次计算参数从哪来、什么时候同步的、
 * 有哪些改动待生效（改动只在下一次续算时应用，不改运行中的作业）。
 */
export default function InputSourceBanner({
  input,
  syncing,
  onSync,
  onRevertChange,
  onRevertFiles,
}: Props) {
  const source = input?.source ?? null;
  const pending = (input?.changes ?? []).filter((c) => !c.applied_at);
  const applied = input?.last_applied?.items ?? [];
  const history = input?.applied_history ?? [];
  const valueText = (value: unknown) => value == null ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
  const eventText = { upload: '已上传参数', continuation: '续算已应用', submit: '提交参数快照' };
  const pendingFiles = Array.from(new Set(pending.map((c) => c.file)));

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
            {pending.length > 1 && (
              <Button
                type="link"
                size="small"
                icon={<RollbackOutlined />}
                onClick={() => onRevertFiles(pendingFiles)}
              >
                全部撤销
              </Button>
            )}
          </div>
          {pending.map((c) => (
            <div key={`${c.file}-${c.key}`} className="input-source__change">
              <Tag color="orange" bordered={false}>
                {c.file}
              </Tag>
              <span className="input-source__change-key">{c.key}</span>
              <span className="input-source__change-val">{c.from || '—'}</span>
              <span className="input-source__change-arrow">→</span>
              <span className="input-source__change-val input-source__change-val--new">
                {c.to === '' ? '（删除）' : c.to}
              </span>
              <Tooltip
                title={`只撤销这一项（${c.key} 回到本次计算值）`}
                placement="left"
              >
                <Button
                  type="text"
                  size="small"
                  icon={<RollbackOutlined />}
                  onClick={() => onRevertChange(c)}
                >
                  撤销
                </Button>
              </Tooltip>
            </div>
          ))}
        </div>
      )}

      {applied.length > 0 && (
        <div className="input-source__applied">
          上次续算已应用 {applied.length} 项：
          {applied.map((c) => `${c.key} ${c.from}→${c.to === '' ? '（删除）' : c.to}`).join('；')}
          （{input?.last_applied?.con}）
        </div>
      )}
      {history.length > 0 && <Collapse size="small" ghost items={[{
        key: 'parameter-history', label: `实际参数记录（最近 ${history.length} 次，最多 5 次，不含草稿）`,
        children: <>
          <p>上传或续算写入不代表运行中的 VASP 已重读参数；提交快照用于确认该次提交的输入。</p>
          {history.map((record) => <div key={record.id} className="input-source__applied">
            <div><Tag bordered={false}>{eventText[record.event]}</Tag>
              <code>{record.directory}</code> · {record.at.replace('T', ' ').slice(0, 19)}
              {record.job_id ? ` · 作业 ${record.job_id}` : ''}</div>
            {record.changes.length ? record.changes.map((change) => <div key={`${change.file}-${change.key}`}>
              <b>{change.file} · {change.key}</b>：
              {change.baseline_known ? valueText(change.before) : '旧值未采集'} → {valueText(change.after)}
            </div>) : <span>与已采集的原参数一致。</span>}
          </div>)}
        </>,
      }]} />}
    </Card>
  );
}
