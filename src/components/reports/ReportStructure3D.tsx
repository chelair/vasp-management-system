/**
 * 报告页的**结构 3D 视图**（2026-10-16 用户："html 中结构三视图现在全量转移到 3d 视图窗口
 * （直接加载，不要放弹窗里）；界面大部分和巡检中保持一致"）。
 *
 * 与巡检详情页同一套件：`Structure3DFrame`（3Dmol + VESTA 元素配色 + 共价半径成键 + 晶胞框），
 * 工具栏也是同一套（球棍/空间填充、原子缩放、自动旋转、a/b/c 视角、重置视角、Shift 框选），
 * 额外加一个「优化后（CONTCAR） / 初始（POSCAR）」切换（两个结构都有时才给）。
 *
 * 正文里原先那 6 张三视图 PNG **不删**（图片链路保留），只是被标成"仅打印"——
 * 屏幕上显示这个 3D 视图，打印 / PDF 时换成那几张 PNG（见 global.css 的 @media print）。
 */

import { useMemo, useState } from 'react';
import { Segmented, Empty } from 'antd';

import Structure3DFrame, { type AtomRef } from '../jobs/Structure3DFrame';

interface Props {
  /** 初始结构（POSCAR）CIF 文本 */
  poscarCif?: string | null;
  /** 优化后结构（CONTCAR）CIF 文本 */
  contcarCif?: string | null;
  taskName?: string;
  height?: number;
}

export default function ReportStructure3D({
  poscarCif,
  contcarCif,
  taskName,
  height = 420,
}: Props) {
  const hasPoscar = Boolean(poscarCif);
  const hasContcar = Boolean(contcarCif);
  const [view, setView] = useState<'contcar' | 'poscar'>('contcar');
  const [selected, setSelected] = useState<AtomRef[]>([]);

  const active: 'contcar' | 'poscar' = view === 'contcar' && !hasContcar ? 'poscar' : view;
  const cif = useMemo(
    () => (active === 'contcar' ? contcarCif : poscarCif) ?? null,
    [active, contcarCif, poscarCif],
  );

  if (!hasPoscar && !hasContcar) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="结构文件缺失，无法显示 3D 视图" />;
  }

  return (
    <div className="report-3d">
      <div className="report-3d__head">
        <span className="report-3d__title">结构 3D 视图</span>
        {taskName ? <span className="report-3d__task">{taskName}</span> : null}
        <span className="report-3d__hint">
          拖动旋转 · 滚轮缩放 · 点击原子高亮 · Shift + 拖拽框选（打印 / PDF 用三视图图片）
        </span>
      </div>
      <Structure3DFrame
        cif={cif}
        height={height}
        selected={selected}
        onClickAtom={(atom, additive) =>
          setSelected((prev) => {
            if (!additive) return [atom];
            const exists = prev.some((x) => x.index === atom.index);
            return exists ? prev.filter((x) => x.index !== atom.index) : [...prev, atom];
          })
        }
        onBoxSelect={(atoms, additive) =>
          setSelected((prev) => {
            if (!additive) return atoms;
            const map = new Map(prev.map((x) => [x.index, x]));
            atoms.forEach((a) => map.set(a.index, a));
            return [...map.values()];
          })
        }
        onClearSelection={() => setSelected([])}
        showSelectedCoords
        toolbarExtra={
          hasPoscar && hasContcar ? (
            <Segmented
              size="small"
              value={active}
              onChange={(v) => {
                setView(v as 'contcar' | 'poscar');
                setSelected([]);
              }}
              options={[
                { label: '优化后（CONTCAR）', value: 'contcar' },
                { label: '初始（POSCAR）', value: 'poscar' },
              ]}
            />
          ) : null
        }
      />
    </div>
  );
}
