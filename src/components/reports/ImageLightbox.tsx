/**
 * 报告里的图片查看器（2026-10-13）：点报告里任意一张结构图/图表 → 打开**原图**，可放大缩小。
 *
 * 多端支持：
 * - 桌面：滚轮缩放、鼠标拖拽平移、双击切换 100% ↔ 适应窗口、工具栏 −/＋/适应/1:1；
 * - 手机/平板：双指捏合缩放、单指拖动平移、双击放大、点击遮罩/× 关闭；
 * - 原生 `<dialog>` 自带 ESC 关闭与焦点管理，小屏（≤720px）全屏显示。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Tooltip } from 'antd';
import {
  CloseOutlined,
  ExpandOutlined,
  OneToOneOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons';

interface Props {
  open: boolean;
  /** 原图地址（报告页就是报告目录里的那张原图；导出 HTML 里是内联的 data URI） */
  src: string;
  caption?: string;
  onClose: () => void;
}

const MIN_SCALE = 0.2;
const MAX_SCALE = 10;
const STEP = 1.25;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function ImageLightbox({ open, src, caption, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  /** 当前缩放值的同步引用（捏合开始时需要立刻读到，等 setState 会慢一拍） */
  const scaleRef = useRef(1);
  /** 正在按下的指针（鼠标 1 个；触摸可能 2 个 → 捏合） */
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const pinchRef = useRef<{ distance: number; scale: number } | null>(null);

  useEffect(() => {
    scaleRef.current = scale;
  }, [scale]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // 换图 / 重新打开：回到「适应窗口」
  useEffect(() => {
    if (!open) return;
    setScale(1);
    setOffset({ x: 0, y: 0 });
    pointers.current.clear();
    dragRef.current = null;
    pinchRef.current = null;
  }, [open, src]);

  const zoomTo = useCallback((next: number) => {
    setScale(clamp(next, MIN_SCALE, MAX_SCALE));
  }, []);

  /** 双击/双击轻触：100% ↔ 200% */
  const toggleZoom = useCallback(() => {
    setScale((prev) => (prev > 1.2 ? 1 : 2));
    setOffset({ x: 0, y: 0 });
  }, []);

  const reset = useCallback(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      event.preventDefault();
      setScale((prev) => clamp(prev * (event.deltaY < 0 ? 1.12 : 1 / 1.12), MIN_SCALE, MAX_SCALE));
    },
    [],
  );

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const stage = event.currentTarget;
    stage.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinchRef.current = {
        distance: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        scale: scaleRef.current,
      };
      dragRef.current = null;
    } else {
      dragRef.current = { x: event.clientX, y: event.clientY };
    }
  }, []);

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size >= 2 && pinchRef.current) {
      const [a, b] = [...pointers.current.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      zoomTo(pinchRef.current.scale * (distance / pinchRef.current.distance));
      return;
    }
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    dragRef.current = { x: event.clientX, y: event.clientY };
    setOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
  }, [zoomTo]);

  const handlePointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (pointers.current.size < 2) pinchRef.current = null;
    if (pointers.current.size === 0) dragRef.current = null;
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="report-image-viewer"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="report-image-viewer__bar">
        <span className="report-image-viewer__caption" title={caption}>
          {caption || '结构图'}
        </span>
        <span className="report-image-viewer__tools">
          <Tooltip title="缩小">
            <Button
              size="small"
              icon={<ZoomOutOutlined />}
              onClick={() => zoomTo(scale / STEP)}
            />
          </Tooltip>
          <span className="report-image-viewer__percent">{Math.round(scale * 100)}%</span>
          <Tooltip title="放大">
            <Button
              size="small"
              icon={<ZoomInOutlined />}
              onClick={() => zoomTo(scale * STEP)}
            />
          </Tooltip>
          <Tooltip title="适应窗口">
            <Button size="small" icon={<ExpandOutlined />} onClick={reset} />
          </Tooltip>
          <Tooltip title="原始大小（100%）">
            <Button
              size="small"
              icon={<OneToOneOutlined />}
              onClick={() => {
                setScale(1);
                setOffset({ x: 0, y: 0 });
              }}
            />
          </Tooltip>
          <Button size="small" icon={<CloseOutlined />} onClick={onClose} aria-label="关闭" />
        </span>
      </div>
      <div
        className="report-image-viewer__stage"
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onDoubleClick={toggleZoom}
      >
        <img
          src={src}
          alt={caption || '结构图'}
          draggable={false}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
        />
      </div>
      <div className="report-image-viewer__hint">
        滚轮 / 双指捏合缩放 · 拖拽平移 · 双击切换 1:1 · ESC 关闭
      </div>
    </dialog>
  );
}
