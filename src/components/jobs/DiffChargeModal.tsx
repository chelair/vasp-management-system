/**
 * 差分电荷分块选择（2026-10-13）。
 *
 * 复用作业管理 POSCAR 页那套「点选 / Ctrl 多选 / Shift 框选」的原子选择逻辑
 * （同一个 `Structure3DFrame`），把主任务 POSCAR 的原子划成若干分块：
 *
 * - 默认两块（分块A / 分块B），可「＋ 添加分块」到 C/D…（目录顺延 3/4）；
 * - 每块一种颜色，选中的分块原子直接按该颜色着色预览；
 * - 选完 A 后可「选中其余原子」把还没分块的原子一次选中，再归入 B；
 * - 确认后后端按分块生成 POSCAR（只保留对应原子）+ 复制 KPOINTS/vasp.lsf +
 *   校验 INCAR（LCHARG=.TRUE. / IBRION=-1）+ pos2pot 生成 POTCAR。
 */

import { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Modal, Segmented, Tag, Tooltip } from 'antd';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { createDiffCharge } from '../../api/jobs';
import { parsePoscar } from '../../utils/poscar';
import Structure3DFrame, { type AtomRef } from './Structure3DFrame';

/** 分块配色：A/B/C/D…（与元素配色区分度足够） */
const BLOCK_COLORS = ['#5B8DEF', '#67C6B0', '#F0A020', '#B37FEB', '#EB6F8A', '#4EA1D3'];
const BLOCK_NAMES = ['分块A', '分块B', '分块C', '分块D', '分块E', '分块F'];

interface BlockState {
  key: string;
  label: string;
  atoms: Record<number, AtomRef>; // key = model index（0 起）
}

interface Props {
  open: boolean;
  taskId: string;
  /** 主任务的 POSCAR 文本（来自 POSCAR 页的编辑器内容） */
  poscarContent: string | null;
  /** 主任务 POSCAR 的 CIF（3D 视图用；没有就先在 POSCAR 页同步一次） */
  cif: string | null;
  taskLabel?: string;
  onClose: () => void;
  onCreated: () => void;
}

function newBlock(index: number): BlockState {
  return {
    key: `b${index}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    label: BLOCK_NAMES[index] ?? `分块${index + 1}`,
    atoms: {},
  };
}

export default function DiffChargeModal({
  open,
  taskId,
  poscarContent,
  cif,
  taskLabel,
  onClose,
  onCreated,
}: Props) {
  const { message } = App.useApp();
  const [blocks, setBlocks] = useState<BlockState[]>([newBlock(0), newBlock(1)]);
  const [activeKey, setActiveKey] = useState('');
  const [selected, setSelected] = useState<AtomRef[]>([]);
  const [busy, setBusy] = useState(false);

  const info = useMemo(
    () => (poscarContent ? parsePoscar(poscarContent) : null),
    [poscarContent],
  );
  const totalAtoms = info ? info.counts.reduce((a, b) => a + b, 0) : 0;

  useEffect(() => {
    if (!open) return;
    const fresh = [newBlock(0), newBlock(1)];
    setBlocks(fresh);
    setActiveKey(fresh[0].key);
    setSelected([]);
  }, [open]);

  const active = blocks.find((b) => b.key === activeKey) ?? blocks[0];
  const assigned = useMemo(() => {
    const map: Record<number, number> = {}; // model index → block 下标
    blocks.forEach((block, index) => {
      Object.keys(block.atoms).forEach((key) => {
        map[Number(key)] = index;
      });
    });
    return map;
  }, [blocks]);
  const colored = useMemo(() => {
    const map: Record<number, string> = {};
    blocks.forEach((block, index) => {
      const color = BLOCK_COLORS[index % BLOCK_COLORS.length];
      Object.keys(block.atoms).forEach((key) => {
        map[Number(key)] = color;
      });
    });
    return map;
  }, [blocks]);

  const assignedCount = Object.keys(assigned).length;
  const remaining = Math.max(totalAtoms - assignedCount, 0);

  const handleClickAtom = (atom: AtomRef, additive: boolean) => {
    setSelected((prev) => {
      if (!additive) return [atom];
      return prev.some((a) => a.index === atom.index)
        ? prev.filter((a) => a.index !== atom.index)
        : [...prev, atom];
    });
  };

  const handleBoxSelect = (atoms: AtomRef[], additive: boolean) => {
    setSelected((prev) => {
      if (!additive) return atoms;
      const merged = new Map(prev.map((a) => [a.index, a]));
      atoms.forEach((a) => merged.set(a.index, a));
      return [...merged.values()];
    });
    if (atoms.length > 0) message.success(`框选了 ${atoms.length} 个原子`);
  };

  /** 把当前选中的原子归入某个分块（会从其它分块里移除） */
  const assignSelectedTo = (targetKey: string) => {
    if (selected.length === 0) {
      message.warning('先在结构图上选中原子（点选 / Ctrl 多选 / Shift 框选）');
      return;
    }
    setBlocks((prev) => {
      const picked = new Set(selected.map((a) => a.index));
      return prev.map((block) => {
        const atoms = { ...block.atoms };
        if (block.key === targetKey) {
          selected.forEach((atom) => {
            atoms[atom.index] = atom;
          });
        } else {
          picked.forEach((index) => {
            delete atoms[index];
          });
        }
        return { ...block, atoms };
      });
    });
    const target = blocks.find((b) => b.key === targetKey);
    message.success(`已把 ${selected.length} 个原子归入「${target?.label ?? ''}」`);
    setSelected([]);
  };

  /** 快速选中「还没分到任何块」的原子（选完 A 再选 B 时用） */
  const selectRemaining = () => {
    const atoms: AtomRef[] = [];
    const elements = info?.elements ?? [];
    const counts = info?.counts ?? [];
    let poscarIndex = 1;
    elements.forEach((element, elementIndex) => {
      for (let i = 0; i < (counts[elementIndex] ?? 0); i += 1) {
        const index = poscarIndex - 1;
        if (assigned[index] === undefined) {
          atoms.push({ index, poscarIndex, element });
        }
        poscarIndex += 1;
      }
    });
    if (atoms.length === 0) {
      message.info('所有原子都已分块');
      return;
    }
    setSelected(atoms);
    message.success(`已选中其余 ${atoms.length} 个原子，点「归入分块X」即可`);
  };

  const addBlock = () => {
    if (blocks.length >= BLOCK_NAMES.length) {
      message.warning(`最多 ${BLOCK_NAMES.length} 个分块`);
      return;
    }
    const block = newBlock(blocks.length);
    setBlocks((prev) => [...prev, block]);
    setActiveKey(block.key);
  };

  const currentBlockAtoms = active ? Object.values(active.atoms) : [];

  const submit = async () => {
    const payloadBlocks = blocks
      .map((block) => ({
        label: block.label,
        atoms: Object.values(block.atoms)
          .map((a) => a.poscarIndex)
          .sort((a, b) => a - b),
      }))
      .filter((block) => block.atoms.length > 0);
    if (payloadBlocks.length < 2) {
      message.error('至少要有两个非空分块');
      return;
    }
    if (assignedCount !== totalAtoms) {
      message.error(
        `还有 ${remaining} 个原子没有分块（分块必须覆盖全部 ${totalAtoms} 个原子）`,
      );
      return;
    }
    setBusy(true);
    try {
      const res = await createDiffCharge(taskId, { blocks: payloadBlocks });
      const fixes = Object.entries(res.incar_fixes ?? {});
      message.success(
        `已创建 ${res.tasks.length} 个分块计算；归档时会在远端用 chgsum.pl + chgdiff.pl 算好差分并回传 CHGCAR_diff`,
      );
      if (fixes.length > 0) {
        message.info(
          `INCAR 关键参数已按差分电荷要求修正：${fixes
            .map(([key, value]) => `${key} ${value}`)
            .join('、')}`,
        );
      }
      (res.incar_warnings ?? []).forEach((text) => message.warning(text));
      onCreated();
      onClose();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '创建差分电荷计算失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={`差分电荷计算 · 划分分块${taskLabel ? `（${taskLabel}）` : ''}`}
      width={1080}
      onCancel={onClose}
      footer={[
        <span key="hint" className="preview-note" style={{ marginRight: 'auto' }}>
          结构图：点选原子 / Ctrl 多选 / Shift 拖拽框选；已分块原子按分块颜色显示
        </span>,
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={busy}
          disabled={!cif || totalAtoms === 0}
          onClick={submit}
        >
          创建各分块计算
        </Button>,
      ]}
    >
      {!cif ? (
        <Alert
          type="warning"
          showIcon
          message="还没有主任务的结构预览"
          description="先在 POSCAR 页同步一次（或点「生成到本地」）拿到结构，再回来划分分块。"
        />
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 10 }}
            message={
              <span>
                共 {totalAtoms} 个原子 · 已分块 {assignedCount} · 未分块 <b>{remaining}</b>
                <span className="preview-note" style={{ marginLeft: 12 }}>
                  各分块只保留自己那部分原子（晶胞不变）；KPOINTS / vasp.lsf 复制主任务，
                  INCAR 校验 LCHARG=.TRUE. / IBRION=-1 / NSW=0，POTCAR 由远端 pos2pot 生成
                </span>
              </span>
            }
          />
          <div className="diff-charge__layout">
            <div className="diff-charge__view">
              <Structure3DFrame
                cif={cif}
                height={520}
                selected={selected}
                onClickAtom={handleClickAtom}
                onBoxSelect={handleBoxSelect}
                onClearSelection={() => setSelected([])}
                atomColors={colored}
                showSelectedCoords
              />
            </div>
            <div className="diff-charge__side">
              <div className="diff-charge__tabs">
                <Segmented
                  block
                  value={active?.key}
                  onChange={(value) => setActiveKey(String(value))}
                  options={blocks.map((block, index) => ({
                    value: block.key,
                    label: (
                      <span style={{ color: BLOCK_COLORS[index % BLOCK_COLORS.length] }}>
                        {block.label}（{Object.keys(block.atoms).length}）
                      </span>
                    ),
                  }))}
                />
              </div>
              <div className="diff-charge__actions">
                <Button type="primary" onClick={() => active && assignSelectedTo(active.key)}>
                  归入 {active?.label ?? ''}
                </Button>
                <Tooltip title="把还没分到任何块的原子一次性选中，再点「归入分块X」">
                  <Button onClick={selectRemaining} disabled={remaining === 0}>
                    选中其余原子（{remaining}）
                  </Button>
                </Tooltip>
                <Button onClick={() => setSelected([])} disabled={selected.length === 0}>
                  清空选择
                </Button>
                <Button icon={<PlusOutlined />} onClick={addBlock}>
                  添加分块
                </Button>
              </div>
              <div className="diff-charge__blocks">
                {blocks.map((block, index) => (
                  <div
                    key={block.key}
                    className={`diff-charge__block${block.key === active?.key ? ' is-active' : ''}`}
                    onClick={() => setActiveKey(block.key)}
                  >
                    <Tag color={BLOCK_COLORS[index % BLOCK_COLORS.length]}>
                      {block.label}
                    </Tag>
                    <span>{Object.keys(block.atoms).length} 原子</span>
                    {blocks.length > 2 && (
                      <Button
                        size="small"
                        type="link"
                        danger
                        onClick={(event) => {
                          event.stopPropagation();
                          setBlocks((prev) => prev.filter((b) => b.key !== block.key));
                        }}
                      >
                        移除
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              <div className="preview-note">
                当前选中 {selected.length} 个原子
                {currentBlockAtoms.length > 0
                  ? ` · ${active?.label}共 ${currentBlockAtoms.length} 个`
                  : ''}
              </div>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
