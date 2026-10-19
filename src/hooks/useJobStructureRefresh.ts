import { useEffect, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { fetchTaskInput } from '../api/jobs';
import type { TaskInputState } from '../api/jobs';
import { INSPECTION_COMPLETED } from '../api/inspections';

/** 选中任务或巡检返回时，只读取巡检已落地的本地结构；无轮询或远端操作。 */
export function useJobStructureRefresh(
  taskIds: string[],
  states: Record<string, TaskInputState>,
  setStates: Dispatch<SetStateAction<Record<string, TaskInputState>>>,
) {
  const statesRef = useRef(states);
  statesRef.current = states;
  const taskKey = JSON.stringify([...new Set(taskIds)].sort());
  useEffect(() => {
    const ids: string[] = JSON.parse(taskKey);
    let disposed = false;
    let generation = 0;
    const refresh = async () => {
      const version = ++generation;
      await Promise.all(ids.map(async (id) => {
        const before = statesRef.current[id];
        if (!before) return; // 首次读取仍由 Jobs 初始化负责。
        try {
          const latest = await fetchTaskInput(id);
          if (disposed || version !== generation) return;
          setStates((prev) => {
            if (disposed || version !== generation || prev[id] !== before) return prev;
            const files = { ...before.files };
            for (const name of ['POSCAR', 'CONTCAR']) {
              if (latest.files[name]) files[name] = latest.files[name];
              else delete files[name];
            }
            const next = { ...before, files, poscar_cif: latest.poscar_cif, contcar_cif: latest.contcar_cif };
            return JSON.stringify(next) === JSON.stringify(before) ? prev : { ...prev, [id]: next };
          });
        } catch {
          // 读取失败保留已有展示，后续切换任务或巡检返回时可再读取。
        }
      }));
    };
    void refresh();
    window.addEventListener(INSPECTION_COMPLETED, refresh);
    return () => {
      disposed = true;
      window.removeEventListener(INSPECTION_COMPLETED, refresh);
    };
  }, [taskKey, setStates]);
}
