/**
 * 自由能路径的**中间体 3D 视图**（2026-10-16 用户："自由能的结构还是之前的三视图"）。
 *
 * 与结构优化那段同一个件（`Structure3DFrame`，和巡检详情一致）：路径下面直接给一个 3D 窗口，
 * 上面一排「结构 1..N」按钮切换显示哪个中间体；**表格里的「结构 N」芯片也切换它**
 * （芯片点击由 Report.tsx 转成 `onSelect`，见 `register`）。
 *
 * CIF 由后端从每个中间体 opt 任务的 CONTCAR 转好放进报告数据（`science.free_energy[].structures[].cif`）；
 * 老的三视图 PNG / 弹窗仍然存在（PNG 留给打印，但不再从这张表里点开）。
 */

import { useEffect, useMemo, useState } from 'react';
import { Empty } from 'antd';

import Structure3DFrame, { type AtomRef } from '../jobs/Structure3DFrame';

export interface FreeEnergyStructure3D {
  structure_label?: string;
  cif?: string | null;
}

interface Props {
  groupName?: string;
  structures: FreeEnergyStructure3D[];
  height?: number;
  /** 把「切到第 index 个中间体」注册给父组件（表格里的芯片点击会用） */
  register?: (select: (index: number) => void) => () => void;
}

export default function ReportFreeEnergy3D({
  groupName,
  structures,
  height = 420,
  register,
}: Props) {
  const available = useMemo(
    () => structures.map((s, index) => ({ ...s, index })).filter((s) => Boolean(s.cif)),
    [structures],
  );
  const [index, setIndex] = useState<number>(available[0]?.index ?? 0);
  const [selected, setSelected] = useState<AtomRef[]>([]);

  useEffect(() => {
    if (!register) return undefined;
    return register((next: number) => {
      setIndex(next);
      setSelected([]);
    });
  }, [register]);

  const active = available.find((s) => s.index === index) ?? available[0];
  if (!active) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该路径的中间体结构缺失" />;
  }

  return (
    <div className="report-3d">
      <div className="report-3d__head">
        <span className="report-3d__title">中间体 3D 视图</span>
        {groupName ? <span className="report-3d__task">{groupName}</span> : null}
        <span className="report-3d__hint">
          点下面表格里的「结构 N」或这里的按钮切换中间体；拖动旋转 · 滚轮缩放 · Shift + 拖拽框选
        </span>
      </div>
      <div className="report-fe3d__switch">
        {available.map((item) => (
          <button
            key={item.index}
            type="button"
            className={`report-fe3d__btn${item.index === active.index ? ' is-on' : ''}`}
            onClick={() => {
              setIndex(item.index);
              setSelected([]);
            }}
          >
            结构 {item.structure_label ?? item.index + 1}
          </button>
        ))}
      </div>
      <Structure3DFrame
        cif={active.cif ?? null}
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
      />
    </div>
  );
}
