/**
 * OUTCAR 尾部弹窗（2026-10-13）：异常结束的任务，点错误信息看最后数行。
 *
 * - 原生 `<dialog>`（ESC / 遮罩 / × 关闭），≤720px 全屏；
 * - 数据来源三级兜底（归档摘要 → 本地镜像 → 远端 tail），界面标出来源与路径；
 * - 「重新读取」强制再去远端取一次（异常任务本地往往没有 OUTCAR）。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { App, Button } from 'antd';

import { fetchOutcarTail } from '../../api/jobs';

interface Props {
  open: boolean;
  taskId: string;
  title?: string;
  image?: string;
  onClose: () => void;
}

const SOURCE_LABEL: Record<string, string> = {
  'reports-tail': '归档摘要（reports/outcar_tail.txt）',
  'local-mirror': '本地镜像 files/OUTCAR',
  remote: '远端实时读取（tail）',
};

export default function OutcarTailDialog({ open, taskId, title, image, onClose }: Props) {
  const { message } = App.useApp();
  const ref = useRef<HTMLDialogElement | null>(null);
  const [text, setText] = useState('');
  const [source, setSource] = useState('');
  const [dir, setDir] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchOutcarTail(taskId, { lines: 60, image });
      setText(data.text || '');
      setSource(data.source || '');
      setDir(data.dir || '');
      if (!data.text) message.warning('该任务没有可读的 OUTCAR 尾部');
    } catch (e) {
      setText('');
      setSource('');
      setDir('');
      message.error(e instanceof Error ? e.message : '读取 OUTCAR 尾部失败');
    } finally {
      setLoading(false);
    }
  }, [taskId, image, message]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  return (
    <dialog
      ref={ref}
      className="outcar-tail-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <header>
        <h3>{title || 'OUTCAR 最后几行'}</h3>
        <button type="button" className="close" aria-label="关闭" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="body">
        <p className="hint">
          来源：{SOURCE_LABEL[source] ?? (source || '—')}
          {dir ? ` · ${dir}` : ''}
        </p>
        <pre className="outcar-tail">{loading ? '读取中…' : text || '（没有内容）'}</pre>
      </div>
      <footer>
        <Button size="small" onClick={() => void load()} loading={loading}>
          重新读取
        </Button>
        <Button
          size="small"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              message.success('已复制');
            } catch {
              message.warning('复制失败（浏览器未授权剪贴板）');
            }
          }}
        >
          复制
        </Button>
        <button type="button" className="btn btn--primary" onClick={onClose}>
          关闭
        </button>
      </footer>
    </dialog>
  );
}
