import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { App } from 'antd';
import { getToken, request } from '../../api/client';
import type { ProjectReportDetail } from '../../types';
import ReportLayoutShape from './ReportLayoutShape';
import {
  W,
  H,
  kinds,
  makeObject,
  newObjectId,
  emptyLayout,
  isLine,
  fit,
  clamp,
  textHeight,
  type Kind,
  type Layout,
  type LayoutObject,
  type LayoutStyle,
} from './reportLayoutModel';
import './ReportLayoutEditor.css';

export interface LayoutHandle {
  save: () => Promise<boolean>;
}
interface Props {
  detail: ProjectReportDetail;
  root: RefObject<HTMLDivElement>;
  version: unknown;
}
// Keep failed edits available when navigating away and back within the same login.
const drafts = new Map<string, LayoutObject[]>();

const ReportLayoutEditor = forwardRef<LayoutHandle, Props>(
  function ReportLayoutEditor({ detail, root, version }, ref) {
    const { message } = App.useApp();
    const reportId = detail.meta.report_id,
      key = `${getToken() ?? 'session'}:${reportId}`;
    const initial = detail.edits?.layout ?? emptyLayout();
    const [objects, setObjects] = useState<LayoutObject[]>(
      () => drafts.get(key) ?? initial.objects,
    );
    const current = useRef(objects);
    current.current = objects;
    const revision = useRef(initial.revision),
      saved = useRef(JSON.stringify(initial.objects));
    const [editing, setEditing] = useState(false),
      [selected, setSelected] = useState(''),
      [typing, setTyping] = useState(''),
      [text, setText] = useState('');
    const [region, setRegion] = useState(
      detail.markdown_sections[0]?.key ?? '',
    );
    const [hosts, setHosts] = useState<HTMLElement[]>([]),
      [preview, setPreview] = useState<LayoutObject | null>(null);
    const [status, setStatus] = useState(''),
      [saving, setSaving] = useState(false);
    const past = useRef<LayoutObject[][]>([]),
      future = useRef<LayoutObject[][]>([]);
    const busy = useRef<Promise<boolean> | null>(null);
    const active = objects.find((o) => o.id === selected),
      dirty = JSON.stringify(objects) !== saved.current;
    const drag = useRef<{
      object: LayoutObject;
      mode: string;
      px: number;
      py: number;
      svg: SVGSVGElement;
      pointer: number;
      target: Element;
    } | null>(null);
    const dirtyRef = useRef(dirty);
    dirtyRef.current = dirty;
    const pendingText = useRef<{ id: string; text: string } | null>(null);

    function commit(next: LayoutObject[]) {
      if (JSON.stringify(next) === JSON.stringify(current.current)) return;
      past.current = [...past.current.slice(-79), current.current];
      future.current = [];
      current.current = next;
      setObjects(next);
      drafts.set(key, next);
      setStatus('有修改待保存');
    }
    function change(id: string, patch: Partial<LayoutObject>, grow = false) {
      commit(
        current.current.map((o) => {
          if (o.id !== id) return o;
          let next = { ...o, ...patch };
          if (grow && !isLine(next))
            next = {
              ...next,
              height: Math.max(next.height, Math.min(H, textHeight(next))),
            };
          return fit(next);
        }),
      );
    }
    function finishText() {
      if (pendingText.current) {
        const value = pendingText.current;
        pendingText.current = null;
        change(value.id, { text: value.text }, true);
      }
      setTyping('');
    }
    const finishRef = useRef(finishText);
    finishRef.current = finishText;
    async function save(): Promise<boolean> {
      finishRef.current();
      if (busy.current) {
        const ok = await busy.current;
        if (!ok) return false;
        return save();
      }
      const snapshot = current.current,
        serialized = JSON.stringify(snapshot);
      if (serialized === saved.current) return true;
      setSaving(true);
      setStatus('正在保存…');
      const job = (async () => {
        try {
          const result = await request<Layout>(
            `/reports/project/${encodeURIComponent(reportId)}/layout`,
            {
              method: 'PUT',
              body: JSON.stringify({
                version: 1,
                revision: revision.current,
                objects: snapshot,
              }),
            },
          );
          revision.current = result.revision;
          saved.current = serialized;
          if (JSON.stringify(current.current) === serialized) {
            drafts.delete(key);
            dirtyRef.current = false;
            setStatus('已保存');
          } else setStatus('有新修改待保存');
          if (result.snapshot_warning) message.warning(result.snapshot_warning);
          return true;
        } catch (e) {
          const value = e instanceof Error ? e.message : '排版保存失败';
          setStatus(value);
          message.error(value);
          return false;
        } finally {
          busy.current = null;
          setSaving(false);
        }
      })();
      busy.current = job;
      return job;
    }
    const saveRef = useRef(save);
    saveRef.current = save;
    useImperativeHandle(ref, () => ({ save: () => saveRef.current() }));
    useEffect(() => {
      const list = Array.from(
        root.current?.querySelectorAll<HTMLElement>('[data-manual-host]') ?? [],
      );
      setHosts(list);
    }, [root, version]);
    useEffect(() => {
      if (!dirty) return;
      const timer = window.setTimeout(() => {
        if (!pendingText.current && !drag.current) void saveRef.current();
      }, 900);
      return () => window.clearTimeout(timer);
    }, [objects, dirty]);
    useEffect(() => {
      const warn = (e: BeforeUnloadEvent) => {
        if (dirtyRef.current || pendingText.current) {
          e.preventDefault();
          e.returnValue = '';
        }
      };
      window.addEventListener('beforeunload', warn);
      return () => {
        window.removeEventListener('beforeunload', warn);
        void saveRef.current();
      };
    }, []);
    useEffect(() => {
      const incoming = detail.edits?.layout ?? emptyLayout();
      if (
        incoming.revision > revision.current &&
        !dirtyRef.current &&
        !busy.current
      ) {
        revision.current = incoming.revision;
        saved.current = JSON.stringify(incoming.objects);
        current.current = incoming.objects;
        setObjects(incoming.objects);
        past.current = [];
        future.current = [];
      }
    }, [detail]);
    function history(redo = false) {
      finishText();
      const from = redo ? future : past,
        to = redo ? past : future;
      const next = from.current.pop();
      if (!next) return;
      to.current.push(current.current);
      current.current = next;
      setObjects(next);
      drafts.set(key, next);
      setStatus('有修改待保存');
      setSelected('');
    }
    function remove() {
      commit(current.current.filter((o) => o.id !== selected));
      setSelected('');
    }
    function duplicate() {
      if (!active || objects.length >= 500) return;
      const next = fit({
        ...active,
        id: newObjectId(),
        x: active.x + 20,
        y: active.y + 20,
        z: objects.length,
        created_at: '',
        updated_at: '',
      });
      commit([...objects, next]);
      setSelected(next.id);
    }
    function layer(action: string) {
      if (!active) return;
      const local = objects
          .filter((o) => o.region === active.region)
          .sort((a, b) => a.z - b.z),
        i = local.findIndex((o) => o.id === active.id);
      const target =
        action === 'top'
          ? local.length - 1
          : action === 'bottom'
            ? 0
            : clamp(i + (action === 'up' ? 1 : -1), 0, local.length - 1);
      local.splice(i, 1);
      local.splice(target, 0, active);
      const ranks = new Map(local.map((o, n) => [o.id, n]));
      commit(objects.map((o) => ({ ...o, z: ranks.get(o.id) ?? o.z })));
    }
    function add(kind: Kind) {
      finishText();
      if (objects.length >= 500) {
        message.info('每份报告最多添加500个排版对象');
        return;
      }
      const next = makeObject(
        kind,
        reportId,
        region,
        objects.filter((o) => o.region === region).length,
      );
      commit([...objects, next]);
      setSelected(next.id);
      root.current
        ?.querySelector(`[data-manual-host="${CSS.escape(region)}"]`)
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    function point(
      svg: SVGSVGElement,
      e: { clientX: number; clientY: number },
    ) {
      const m = svg.getScreenCTM();
      if (!m) return { x: 0, y: 0 };
      return new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    }
    function start(e: React.PointerEvent, object: LayoutObject, mode = 'move') {
      if (!editing || typing === object.id || e.button !== 0) return;
      finishText();
      e.preventDefault();
      e.stopPropagation();
      setSelected(object.id);
      setRegion(object.region);
      const svg = (e.target as Element).closest('svg')!;
      const p = point(svg, e);
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = {
        object,
        mode,
        px: p.x,
        py: p.y,
        svg,
        pointer: e.pointerId,
        target: e.currentTarget,
      };
      setPreview(object);
    }
    function move(e: React.PointerEvent) {
      const d = drag.current;
      if (!d) return;
      const p = point(d.svg, e),
        dx = p.x - d.px,
        dy = p.y - d.py,
        o = d.object;
      let next = { ...o };
      if (d.mode === 'move') next = fit({ ...o, x: o.x + dx, y: o.y + dy });
      else if (d.mode === 'start' || d.mode === 'end') {
        const ex = o.x + o.dx,
          ey = o.y + o.dy;
        if (d.mode === 'start') {
          next.x = clamp(o.x + dx, 0, W);
          next.y = clamp(o.y + dy, 0, H);
          next.dx = ex - next.x;
          next.dy = ey - next.y;
        } else {
          next.dx = clamp(ex + dx, 0, W) - o.x;
          next.dy = clamp(ey + dy, 0, H) - o.y;
        }
      } else {
        const r = (o.rotation * Math.PI) / 180,
          c = Math.cos(r),
          s = Math.sin(r),
          lx = dx * c + dy * s,
          ly = -dx * s + dy * c;
        let left = 0,
          right = o.width,
          top = 0,
          bottom = o.height;
        if (d.mode.includes('w')) left = Math.min(lx, o.width - 24);
        if (d.mode.includes('e')) right = Math.max(24, o.width + lx);
        if (d.mode.includes('n')) top = Math.min(ly, o.height - 24);
        if (d.mode.includes('s')) bottom = Math.max(24, o.height + ly);
        let w = right - left,
          h = bottom - top;
        if (o.kind === 'square' || o.kind === 'circle' || e.shiftKey) {
          const horizontal = d.mode.includes('w') || d.mode.includes('e');
          const vertical = d.mode.includes('n') || d.mode.includes('s');
          const ratio =
            o.kind === 'square' || o.kind === 'circle' ? 1 : o.width / o.height;
          if (
            !vertical ||
            (horizontal &&
              Math.abs(w / o.width - 1) > Math.abs(h / o.height - 1))
          )
            h = w / ratio;
          else w = h * ratio;
          const minimum = Math.max(1, 24 / w, 24 / h);
          w *= minimum;
          h *= minimum;
          if (!horizontal) {
            left = (o.width - w) / 2;
            right = left + w;
          } else if (d.mode.includes('w')) left = right - w;
          else right = left + w;
          if (!vertical) {
            top = (o.height - h) / 2;
            bottom = top + h;
          } else if (d.mode.includes('n')) top = bottom - h;
          else bottom = top + h;
        }
        const cx = (left + right - o.width) / 2,
          cy = (top + bottom - o.height) / 2;
        next = fit({
          ...o,
          width: w,
          height: h,
          x: o.x + o.width / 2 + cx * c - cy * s - w / 2,
          y: o.y + o.height / 2 + cx * s + cy * c - h / 2,
        });
      }
      setPreview(next);
    }
    function end(e: React.PointerEvent, cancel = false) {
      const d = drag.current;
      if (!d) return;
      if (d.target.hasPointerCapture(d.pointer))
        d.target.releasePointerCapture(d.pointer);
      if (!cancel && preview)
        commit(current.current.map((o) => (o.id === preview.id ? preview : o)));
      drag.current = null;
      setPreview(null);
      e.stopPropagation();
    }
    useEffect(() => {
      if (!editing) return;
      const down = (e: KeyboardEvent) => {
        const el = e.target as HTMLElement;
        if (e.key === 'Escape') {
          finishRef.current();
          setSelected('');
          return;
        }
        if (el.closest('input,textarea,select,[contenteditable="true"]'))
          return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
          e.preventDefault();
          history(e.shiftKey);
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
          e.preventDefault();
          history(true);
        } else if (selected && (e.key === 'Delete' || e.key === 'Backspace')) {
          e.preventDefault();
          remove();
        } else if (
          selected &&
          (e.ctrlKey || e.metaKey) &&
          e.key.toLowerCase() === 'd'
        ) {
          e.preventDefault();
          duplicate();
        }
      };
      const outside = (e: PointerEvent) => {
        if (
          !(e.target as Element).closest(
            '.report-layout-editor,.report-manual-region',
          )
        ) {
          finishRef.current();
          setSelected('');
        }
      };
      document.addEventListener('keydown', down);
      document.addEventListener('pointerdown', outside);
      return () => {
        document.removeEventListener('keydown', down);
        document.removeEventListener('pointerdown', outside);
      };
    });
    const style = (patch: Partial<LayoutStyle>) =>
      active &&
      change(active.id, { style: { ...active.style, ...patch } }, true);
    const num = (
      label: string,
      value: number,
      onChange: (n: number) => void,
      min: number,
      max: number,
      step = 1,
    ) => (
      <label>
        {label}
        <input
          aria-label={label}
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => {
            if (e.target.value !== '')
              onChange(clamp(Number(e.target.value), min, max));
          }}
        />
      </label>
    );
    const color = (
      label: string,
      value: string,
      onChange: (v: string) => void,
    ) => (
      <label>
        {label}
        <input
          aria-label={label}
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
    const regions = detail.markdown_sections;
    const missing = objects.filter(
      (o) => !regions.some((r) => r.key === o.region),
    );
    return (
      <>
        <div className={`report-layout-editor${editing ? ' is-editing' : ''}`}>
          <div className="report-layout-toolbar">
            <strong>自由排版</strong>
            <button
              type="button"
              aria-pressed={editing}
              onClick={() => {
                finishText();
                setEditing(!editing);
                setSelected('');
              }}
            >
              {editing ? '退出编辑' : '编辑排版'}
            </button>
            {(dirty || status) && (
              <span
                role="status"
                className={
                  status.includes('失败') || status.includes('未保存')
                    ? 'layout-error'
                    : ''
                }
              >
                {status || '有修改待保存'}
              </span>
            )}
            {(dirty || saving) && (
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
              >
                保存排版
              </button>
            )}
          </div>
          {editing && (
            <>
              <div className="report-layout-toolbar">
                <label>
                  所属章节
                  <select
                    aria-label="排版章节"
                    value={region}
                    onChange={(e) => {
                      setRegion(e.target.value);
                      setSelected('');
                    }}
                  >
                    {regions.map((r) => (
                      <option key={r.key} value={r.key}>
                        {r.title}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" onClick={() => add('text')}>
                  添加文本框
                </button>
                <label>
                  基本形状
                  <select
                    aria-label="添加基本形状"
                    value=""
                    onChange={(e) => {
                      if (e.target.value) add(e.target.value as Kind);
                    }}
                  >
                    <option value="">选择形状…</option>
                    {Object.entries(kinds)
                      .filter(([k]) => k !== 'text')
                      .map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={!past.current.length}
                  onClick={() => history()}
                >
                  撤销
                </button>
                <button
                  type="button"
                  disabled={!future.current.length}
                  onClick={() => history(true)}
                >
                  重做
                </button>
                <label>
                  选择对象
                  <select
                    aria-label="选择排版对象"
                    value={selected}
                    onChange={(e) => {
                      finishText();
                      setSelected(e.target.value);
                    }}
                  >
                    <option value="">未选中</option>
                    {objects.map((o, i) => (
                      <option key={o.id} value={o.id}>
                        {i + 1}. {kinds[o.kind]} {o.text.slice(0, 16)}
                        {missing.includes(o) ? '（原章节已移除）' : ''}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="report-layout-help">
                对象放在各章节末尾的独立排版区；双击写文字，拖动移动，拖动控制点缩放。Shift
                保持比例。修改会自动保存。
              </p>
              {missing.length > 0 && (
                <p role="alert">
                  {missing.length}{' '}
                  个对象的原章节已移除，数据仍保留。请在“选择对象”中选中，再更改所属章节。
                </p>
              )}
              {active && (
                <div className="report-layout-properties">
                  <div className="report-layout-toolbar">
                    <strong>{kinds[active.kind]}</strong>
                    <button type="button" onClick={duplicate}>
                      复制对象
                    </button>
                    <button type="button" onClick={remove}>
                      删除对象
                    </button>
                    {(['top', 'up', 'down', 'bottom'] as const).map((a, i) => (
                      <button type="button" key={a} onClick={() => layer(a)}>
                        {['置于顶层', '上移一层', '下移一层', '置于底层'][i]}
                      </button>
                    ))}
                    <label>
                      移至章节
                      <select
                        aria-label="对象所属章节"
                        value={active.region}
                        onChange={(e) => {
                          change(active.id, { region: e.target.value });
                          setRegion(e.target.value);
                        }}
                      >
                        {missing.includes(active) && (
                          <option value={active.region}>原章节已移除</option>
                        )}
                        {regions.map((r) => (
                          <option key={r.key} value={r.key}>
                            {r.title}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="report-layout-toolbar">
                    {!isLine(active) && (
                      <>
                        {color('填充颜色', active.style.fill, (v) =>
                          style({ fill: v }),
                        )}
                        {num(
                          '填充不透明度',
                          active.style.fill_opacity,
                          (v) => style({ fill_opacity: v }),
                          0,
                          1,
                          0.05,
                        )}
                        {num(
                          '旋转角度',
                          active.rotation,
                          (v) => change(active.id, { rotation: v }),
                          -180,
                          180,
                        )}
                      </>
                    )}
                    {color('边框颜色', active.style.stroke, (v) =>
                      style({ stroke: v }),
                    )}
                    {num(
                      '边框粗细',
                      active.style.stroke_width,
                      (v) => style({ stroke_width: v }),
                      0,
                      16,
                    )}
                    {num(
                      '边框不透明度',
                      active.style.stroke_opacity,
                      (v) => style({ stroke_opacity: v }),
                      0,
                      1,
                      0.05,
                    )}
                    <label>
                      线型
                      <select
                        aria-label="线型"
                        value={active.style.dash}
                        onChange={(e) =>
                          style({ dash: e.target.value as LayoutStyle['dash'] })
                        }
                      >
                        <option value="solid">实线</option>
                        <option value="dashed">虚线</option>
                        <option value="dotted">点线</option>
                      </select>
                    </label>
                    {isLine(active) && active.kind !== 'line' && (
                      <>
                        <label>
                          <input
                            aria-label="起点箭头"
                            type="checkbox"
                            checked={active.style.arrow_start}
                            onChange={(e) =>
                              style({ arrow_start: e.target.checked })
                            }
                          />
                          起点箭头
                        </label>
                        <label>
                          <input
                            aria-label="终点箭头"
                            type="checkbox"
                            checked={active.style.arrow_end}
                            onChange={(e) =>
                              style({ arrow_end: e.target.checked })
                            }
                          />
                          终点箭头
                        </label>
                      </>
                    )}
                  </div>
                  {!isLine(active) && (
                    <div className="report-layout-toolbar">
                      {num(
                        '字号',
                        active.style.font_size,
                        (v) => style({ font_size: v }),
                        8,
                        96,
                      )}
                      {color('文字颜色', active.style.color, (v) =>
                        style({ color: v }),
                      )}
                      <label>
                        字重
                        <select
                          aria-label="字重"
                          value={active.style.font_weight}
                          onChange={(e) =>
                            style({
                              font_weight: Number(
                                e.target.value,
                              ) as LayoutStyle['font_weight'],
                            })
                          }
                        >
                          {[400, 500, 600, 700, 800].map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        aria-pressed={active.style.font_weight >= 700}
                        onClick={() =>
                          style({
                            font_weight:
                              active.style.font_weight >= 700 ? 400 : 700,
                          })
                        }
                      >
                        粗体
                      </button>
                      <button
                        type="button"
                        aria-pressed={active.style.italic}
                        onClick={() => style({ italic: !active.style.italic })}
                      >
                        斜体
                      </button>
                      <label>
                        文字对齐
                        <select
                          aria-label="文字对齐"
                          value={active.style.align}
                          onChange={(e) =>
                            style({
                              align: e.target.value as LayoutStyle['align'],
                            })
                          }
                        >
                          <option value="left">左对齐</option>
                          <option value="center">居中</option>
                          <option value="right">右对齐</option>
                        </select>
                      </label>
                      <label>
                        垂直对齐
                        <select
                          aria-label="垂直对齐"
                          value={active.style.vertical}
                          onChange={(e) =>
                            style({
                              vertical: e.target
                                .value as LayoutStyle['vertical'],
                            })
                          }
                        >
                          <option value="start">顶部</option>
                          <option value="center">居中</option>
                          <option value="end">底部</option>
                        </select>
                      </label>
                      {num(
                        '内边距',
                        active.style.padding,
                        (v) => style({ padding: v }),
                        0,
                        40,
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setTyping(active.id);
                          setText(active.text);
                          pendingText.current = {
                            id: active.id,
                            text: active.text,
                          };
                        }}
                      >
                        编辑文字
                      </button>
                      {textHeight(active) > active.height + 2 && (
                        <span role="alert">
                          文字超出边界，请增大对象或减小字号
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
        {hosts.map((host) => {
          const id = host.dataset.manualHost!,
            items = objects
              .filter((o) => o.region === id)
              .sort((a, b) => a.z - b.z);
          if (!editing && !items.length) return null;
          return createPortal(
            <div
              className={`report-manual-region${editing ? ' is-editing' : ''}`}
              data-layout-region={id}
            >
              {editing && (
                <div className="report-layout-region-label">
                  {regions.find((r) => r.key === id)?.title} · 排版区
                </div>
              )}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox={`0 0 ${W} ${H}`}
                style={{
                  display: 'block',
                  width: '100%',
                  height: 'auto',
                  overflow: 'visible',
                }}
                onPointerDown={(e) => {
                  if (e.target === e.currentTarget) {
                    finishText();
                    setSelected('');
                    setRegion(id);
                  }
                }}
                onPointerMove={move}
                onPointerUp={(e) => end(e)}
                onPointerCancel={(e) => end(e, true)}
              >
                {items.map((item) => {
                  const o = preview?.id === item.id ? preview : item,
                    chosen = editing && selected === o.id;
                  const handles: [string, number, number][] = isLine(o)
                    ? [
                        ['start', 0, 0],
                        ['end', o.dx, o.dy],
                      ]
                    : [
                        ['nw', 0, 0],
                        ['n', o.width / 2, 0],
                        ['ne', o.width, 0],
                        ['e', o.width, o.height / 2],
                        ['se', o.width, o.height],
                        ['s', o.width / 2, o.height],
                        ['sw', 0, o.height],
                        ['w', 0, o.height / 2],
                      ];
                  return (
                    <g
                      key={o.id}
                      data-layout-object={o.id}
                      className={
                        editing ? 'layout-object is-editable' : 'layout-object'
                      }
                      transform={`translate(${o.x} ${o.y}) rotate(${o.rotation} ${o.width / 2} ${o.height / 2})`}
                      onPointerDown={(e) => start(e, o)}
                      onDoubleClick={(e) => {
                        if (editing && !isLine(o)) {
                          e.stopPropagation();
                          setSelected(o.id);
                          setTyping(o.id);
                          setText(o.text);
                          pendingText.current = { id: o.id, text: o.text };
                        }
                      }}
                    >
                      {editing && isLine(o) && (
                        <path
                          d={`M0 0 L${o.dx} ${o.dy}`}
                          fill="none"
                          stroke="transparent"
                          strokeWidth={Math.max(18, o.style.stroke_width)}
                        />
                      )}
                      <ReportLayoutShape o={o}>
                        {typing === o.id ? (
                          <textarea
                            autoFocus
                            aria-label="对象文字"
                            value={text}
                            maxLength={4000}
                            onPointerDown={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              setText(e.target.value);
                              pendingText.current = {
                                id: o.id,
                                text: e.target.value,
                              };
                            }}
                            onBlur={finishText}
                            style={{
                              width: '100%',
                              height: '100%',
                              minHeight: o.style.font_size * 1.5,
                              border: 'none',
                              padding: 0,
                              margin: 0,
                              resize: 'none',
                              font: 'inherit',
                              lineHeight: 'inherit',
                              textAlign: 'inherit',
                              color: 'inherit',
                              background: 'transparent',
                              outline: '1px dashed #3f6fe0',
                            }}
                          />
                        ) : undefined}
                      </ReportLayoutShape>
                      {chosen && typing !== o.id && (
                        <g className="layout-controls">
                          {!isLine(o) && (
                            <rect
                              width={o.width}
                              height={o.height}
                              fill="none"
                              stroke="#3f6fe0"
                              strokeWidth={1.5}
                              strokeDasharray="5 3"
                            />
                          )}
                          {handles.map(([name, x, y]) => (
                            <rect
                              key={name}
                              aria-label={`调整${name}`}
                              data-handle={name}
                              x={x - 6}
                              y={y - 6}
                              width={12}
                              height={12}
                              fill="white"
                              stroke="#3f6fe0"
                              strokeWidth={2}
                              style={{
                                cursor: isLine(o)
                                  ? 'crosshair'
                                  : `${name}-resize`,
                              }}
                              onPointerDown={(e) => start(e, o, name)}
                            />
                          ))}
                        </g>
                      )}
                    </g>
                  );
                })}
              </svg>
            </div>,
            host,
            id,
          );
        })}
      </>
    );
  },
);
export default ReportLayoutEditor;
