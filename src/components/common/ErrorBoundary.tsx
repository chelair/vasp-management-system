/**
 * 局部错误边界（2026-10-13）：某个子组件渲染抛错时，**只把那一块换成提示**，不再整页白屏。
 *
 * 起因：PDOS 弹窗里一个 hook 顺序写错（`useMemo` 在渲染期引用了定义在后面的 `useCallback`），
 * 点「自适应」触发 TDZ 的 `ReferenceError` → React 卸载整棵树 → 页面白屏。
 */

import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** 出错时显示的标题（默认"这块内容出错了"） */
  title?: string;
  /** 出错时的补充说明 */
  hint?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 控制台留一份，便于排查（生产构建里也在）
    console.error('[ErrorBoundary]', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="app-error-box">
        <p className="app-error-box__title">{this.props.title ?? '这块内容出错了'}</p>
        <p className="app-error-box__msg">{error.message || String(error)}</p>
        {this.props.hint ? <p className="preview-note">{this.props.hint}</p> : null}
        <button type="button" className="btn" onClick={() => this.setState({ error: null })}>
          重试
        </button>
      </div>
    );
  }
}
