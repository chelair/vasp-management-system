import { useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Alert,
  Button,
  Card,
  Checkbox,
  Drawer,
  Input,
  Modal,
  Select,
  Segmented,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import {
  BookOutlined,
  CheckOutlined,
  CloseOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type {
  IncarPreset,
  JobWorkspace,
  PrecisionMode,
  Task,
  TaskType,
} from '../../types';
import { PRECISION_LABELS, TASK_TYPE_LABELS } from '../../types';
import {
  BUILTIN_PRESETS,
  INCAR_CATEGORIES,
  PRECISION_PRESETS,
  IDIPOL_OPTIONS,
  LDAUL_OPTIONS,
  LDAUTYPE_OPTIONS,
  PRESET_INCAR_KEYS,
  applyIncarGates,
  buildIncarText,
  defaultLdauRows,
  incarParamDef,
  incarValueEquals,
  isIncarTrue,
  joinDipol,
  ldauArrayParams,
  parseDipol,
  parseLdauRows,
  parsePoscarElements,
  type LdauRow,
} from '../../data/mock/incar';
import { saveTaskFile, uploadIncar, type TaskInputState } from '../../api/jobs';
import SciInput from './SciInput';

/** 「其他参数」卡片的一行；id 与键名解耦，改名时输入框不会被重建（不丢焦点） */
interface ExtraRow {
  id: string;
  key: string;
  value: string;
}

interface Props {
  task: Task;
  workspace: JobWorkspace;
  presets: IncarPreset[];
  onParamsChange: (params: Record<string, string>, precision: PrecisionMode) => void;
  onApplyPreset: (preset: IncarPreset) => void;
  onSavePreset: (name: string) => void;
  onDeletePreset: (id: string) => void;
  onCopyToOthers: () => void;
  /** 本次计算（远端同步）到的参数，用于"已修改"对比与取消回滚 */
  snapshotParams: Record<string, string>;
  /** 已提交但未生效（下一次续算应用）的参数键 */
  pendingKeys: string[];
  /** 确认修改：把与快照不同的参数写入草稿（下次续算生效） */
  onConfirmParams: (params: Record<string, string>) => void;
  /** 取消修改：回到「本次计算值 + 待生效修改」（只丢弃本次编辑过程中的改动） */
  onResetToSnapshot: () => void;
  /** 「同步到远端」成功后回传刷新过的输入状态（草稿/台账/本次计算值） */
  onStatePushed?: (state: TaskInputState) => void;
}

export default function IncarEditor({
  task,
  workspace,
  presets,
  onParamsChange,
  onApplyPreset,
  onSavePreset,
  onDeletePreset,
  onCopyToOthers,
  snapshotParams,
  pendingKeys,
  onConfirmParams,
  onResetToSnapshot,
  onStatePushed,
}: Props) {
  const { message } = App.useApp();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [loadValue, setLoadValue] = useState<string | undefined>(undefined);
  /** 参数编辑闸门：默认只读（灰色不可点），点「修改参数」后才可编辑 */
  const [editing, setEditing] = useState(false);

  const params = workspace.incarParams;
  const precision = workspace.precision;
  const incarText = useMemo(() => buildIncarText(params), [params]);
  const pendingSet = useMemo(() => new Set(pendingKeys), [pendingKeys]);
  const isChanged = (key: string) => {
    const base = String(snapshotParams[key] ?? '');
    const now = String(params[key] ?? '');
    if (now === '' && base === '') return false;
    // 语义比较：`.T.` 与 `.TRUE.`、`1E-6` 与 `1e-6` 不算改动
    return !incarValueEquals(incarParamDef(key), now, base);
  };

  const setParam = (key: string, value: string) => {
    // 手动修改任意参数后，自动切换为「自定义」
    onParamsChange({ ...params, [key]: value }, 'custom');
  };

  /** 一次改多个参数（主开关联动时用） */
  const setParams = (patch: Record<string, string>) => {
    onParamsChange({ ...params, ...patch }, 'custom');
  };

  const applyPrecision = (mode: Exclude<PrecisionMode, 'custom'>) => {
    onParamsChange({ ...params, ...PRECISION_PRESETS[mode] }, mode);
    message.success(`已应用${PRECISION_LABELS[mode]}推荐参数，可切换到「自定义」微调`);
  };

  const applyPreset = (id: string) => {
    const preset = [...BUILTIN_PRESETS, ...presets].find((p) => p.id === id);
    if (!preset) return;
    onApplyPreset(preset);
    setLoadValue(undefined);
    message.success(`已加载预设：${preset.name}`);
  };

  const copyPreview = async () => {
    try {
      await navigator.clipboard.writeText(incarText);
      message.success('INCAR 内容已复制到剪贴板');
    } catch {
      message.warning('复制失败，请手动选择文本复制');
    }
  };

  const handleUploadRemote = async () => {
    try {
      // 只有参数相对"本次计算实际使用的值"真的变了才提交修改
      const changed = Object.entries(workspace.incarParams).filter(
        ([key, value]) => String(value ?? '').trim() !== String(snapshotParams[key] ?? '').trim(),
      );
      if (changed.length === 0) {
        message.info('参数与本次计算一致，无需同步');
        return;
      }
      // 以当前表单参数为基础，后端基于远端旧 INCAR 做统一修改
      // 留空（空字符串/仅空白）的参数不参与写入：与「生成 INCAR」一致
      // 主开关关闭的整组参数（DFT+U / 偶极矩修正）也在这里被过滤掉
      const merged = Object.fromEntries(
        Object.entries(applyIncarGates(workspace.incarParams)).filter(
          ([, value]) => String(value ?? '').trim() !== '',
        ),
      );
      const r = await uploadIncar(task.task_id, { params: merged });
      onStatePushed?.(r.state);
      const appliedText =
        r.applied.length > 0 ? `，${r.applied.length} 项修改已生效` : '';
      message.success(
        `INCAR 已同步到远端${r.backup_file ? `（旧文件备份为 ${r.backup_file}）` : ''}${appliedText}`,
      );
      if (r.warnings.length > 0) {
        message.warning(r.warnings.join('；'));
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同步 INCAR 到远端失败');
    }
  };

  /**
   * 其他参数（不在预设表单里的键）：改名 / 改值 / 新增 / 删除。
   * 用「本地行 + 稳定 id」而不是直接用 params 的键渲染，原因是：
   *  1) 新增的行值还是空的，直接渲染 params 会因「空值不展示」而看不见；
   *  2) 行用键做 React key 时，改名会让输入框重建 → 焦点丢失、打不进字。
   * 行内容仍以 params 为准（变更时同步写回），外部变化（切换任务/同步/撤销）会自动重建。
   */
  const extraRowSeq = useRef(0);
  const makeExtraRowId = () => `extra-${(extraRowSeq.current += 1)}`;
  const [extraRows, setExtraRows] = useState<ExtraRow[]>(() =>
    Object.entries(params)
      .filter(([key]) => !PRESET_INCAR_KEYS.has(key))
      .map(([key, value]) => ({ id: `init-${key}`, key, value: String(value ?? '') })),
  );

  const extraSig = (rows: ExtraRow[]) =>
    rows
      .filter((row) => row.key.trim() !== '')
      .map((row) => JSON.stringify([row.key.trim().toUpperCase(), row.value]))
      .sort()
      .join('\n');

  // 把本地行写回参数（以行内容为准；预设键不动）
  const writeExtraRows = (rows: ExtraRow[]) => {
    const next: Record<string, string> = { ...params };
    for (const key of Object.keys(next)) {
      if (!PRESET_INCAR_KEYS.has(key)) delete next[key];
    }
    for (const row of rows) {
      const key = row.key.trim().toUpperCase();
      if (key && !PRESET_INCAR_KEYS.has(key)) next[key] = row.value;
    }
    onParamsChange(next, 'custom');
  };

  // 参数被外部改动（切换任务 / 同步最新参数 / 撤销）时重建行；自己编辑时签名一致 → 保留原行与焦点
  useEffect(() => {
    setExtraRows((prev) => {
      const entries = Object.entries(params).filter(([key]) => !PRESET_INCAR_KEYS.has(key));
      const fromParams = entries
        .map(([key, value]) => JSON.stringify([key, String(value ?? '')]))
        .sort()
        .join('\n');
      if (fromParams === extraSig(prev)) return prev;
      const idBySig = new Map(
        prev.map((row) => [JSON.stringify([row.key.trim().toUpperCase(), row.value]), row.id]),
      );
      const unfinished = prev.filter((row) => row.key.trim() === '');
      const rebuilt = entries.map(([key, value]) => {
        const sig = JSON.stringify([key, String(value ?? '')]);
        return { id: idBySig.get(sig) ?? makeExtraRowId(), key, value: String(value ?? '') };
      });
      return [...rebuilt, ...unfinished];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const applyExtraRows = (rows: ExtraRow[]) => {
    setExtraRows(rows);
    writeExtraRows(rows);
  };

  const addExtraParam = () => {
    let index = 1;
    const used = new Set(extraRows.map((row) => row.key.trim().toUpperCase()));
    while (used.has(`NEW_PARAM_${index}`) || params[`NEW_PARAM_${index}`] !== undefined) index += 1;
    applyExtraRows([...extraRows, { id: makeExtraRowId(), key: `NEW_PARAM_${index}`, value: '' }]);
  };

  const renameExtraParam = (id: string, nextKey: string) => {
    applyExtraRows(extraRows.map((row) => (row.id === id ? { ...row, key: nextKey } : row)));
  };

  const setExtraParamValue = (id: string, value: string) => {
    applyExtraRows(extraRows.map((row) => (row.id === id ? { ...row, value } : row)));
  };

  const removeExtraParam = (id: string) => {
    applyExtraRows(extraRows.filter((row) => row.id !== id));
  };

  const handleSaveLocal = async () => {
    try {
      const r = await saveTaskFile(task.task_id, 'INCAR', incarText);
      message.success(`INCAR 已保存到本地：${r.path}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存 INCAR 失败');
    }
  };

  const presetGroups = [
    {
      label: '内置模板',
      options: BUILTIN_PRESETS.map((p) => ({ value: p.id, label: p.name })),
    },
    ...(presets.length > 0
      ? [
          {
            label: '我的预设',
            options: presets.map((p) => ({
              value: p.id,
              label: (
                <div className="preset-option">
                  <span className="preset-option__name">{p.name}</span>
                  <Tooltip title="删除预设">
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeletePreset(p.id);
                        setLoadValue(undefined);
                      }}
                    />
                  </Tooltip>
                </div>
              ),
            })),
          },
        ]
      : []),
  ];

  const renderField = (def: (typeof INCAR_CATEGORIES)[number]['params'][number]) => {
    const value = params[def.key] ?? '';
    const key = def.key;
    if (def.type === 'bool') {
      const checked = isIncarTrue(value);
      return (
        <Checkbox
          checked={checked}
          disabled={!editing}
          onChange={(e) => setParam(key, e.target.checked ? '.TRUE.' : '.FALSE.')}
        >
          {checked ? '.TRUE.' : '.FALSE.'}
        </Checkbox>
      );
    }
    if (def.type === 'enum') {
      const selected = def.options?.find((o) => o.value === String(value));
      return (
        <div>
          <Select
            size="middle"
            style={{ width: '100%' }}
            value={String(value)}
            disabled={!editing}
            onChange={(v) => setParam(key, v)}
            options={def.options?.map((o) => ({ value: o.value, label: o.label }))}
          />
          {selected?.hint && <div className="job-field-hint">{selected.hint}</div>}
        </div>
      );
    }
    if (def.type === 'number') {
      return (
        <SciInput
          value={String(value)}
          suffix={def.unit}
          placeholder={def.placeholder ?? def.defaultValue}
          disabled={!editing}
          onChange={(v) => setParam(key, v)}
        />
      );
    }
    return (
      <Input
        value={String(value)}
        placeholder={def.placeholder ?? def.defaultValue}
        disabled={!editing}
        onChange={(e) => setParam(key, e.target.value)}
      />
    );
  };

  /* ---------- DFT+U 卡片：主开关 + 元素表（LDAUL / LDAUU / LDAUJ 一一对应） ---------- */

  const elementSymbols = useMemo(
    () => parsePoscarElements(workspace.poscarContent),
    [workspace.poscarContent],
  );
  const ldauEnabled = isIncarTrue(params.LDAU ?? '');
  const ldauRows = useMemo(() => parseLdauRows(params), [params]);
  // 关闭时展示"打开后会写入"的默认表（只读灰显），避免整块空白
  const ldauRowsView = ldauRows.length > 0 ? ldauRows : defaultLdauRows(elementSymbols.length);
  const ldauRowLabel = (index: number) => elementSymbols[index] ?? `元素 ${index + 1}`;
  const ldauLocked = !editing || !ldauEnabled;

  const toggleLdau = (on: boolean) => {
    if (!on) {
      // 关闭：清空整组参数 → 生成/上传的 INCAR 都不含任何 LDAU*
      setParams({ LDAU: '', LDAUTYPE: '', LMAXMIX: '', LDAUL: '', LDAUU: '', LDAUJ: '' });
      return;
    }
    const rows = ldauRows.length > 0 ? ldauRows : defaultLdauRows(elementSymbols.length);
    setParams({
      LDAU: '.TRUE.',
      LDAUTYPE: String(params.LDAUTYPE ?? '').trim() || '1',
      LMAXMIX: String(params.LMAXMIX ?? '').trim() || '4',
      ...ldauArrayParams(rows),
    });
  };

  const updateLdauRow = (index: number, patch: Partial<LdauRow>) => {
    const rows = ldauRowsView.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setParams(ldauArrayParams(rows));
  };

  const addLdauRow = () => {
    setParams(ldauArrayParams([...ldauRowsView, { ldaul: '-1', ldauu: '0.0', ldauj: '0.0' }]));
  };

  const removeLdauRow = (index: number) => {
    const rows = ldauRowsView.filter((_, i) => i !== index);
    setParams(ldauArrayParams(rows.length > 0 ? rows : []));
  };

  /* ---------- 偶极矩修正卡片：主开关 + IDIPOL + EFIELD（单值）+ DIPOL 三分量 ---------- */

  const dipoleEnabled = isIncarTrue(params.LDIPOL ?? '');
  const dipoleLocked = !editing || !dipoleEnabled;
  const [dipolParts, setDipolParts] = useState<[string, string, string]>(() =>
    parseDipol(params.DIPOL),
  );

  // 外部值（切换任务 / 远端同步）变化时同步三个输入框；输入过程中的中间态不覆盖
  useEffect(() => {
    setDipolParts((prev) => (joinDipol(prev) === String(params.DIPOL ?? '').trim() ? prev : parseDipol(params.DIPOL)));
  }, [params.DIPOL]);

  const toggleDipole = (on: boolean) => {
    if (!on) {
      setDipolParts(['', '', '']);
      // 关闭：清空整组参数 → 生成/上传的 INCAR 都不含 LDIPOL / IDIPOL / DIPOL / EFIELD
      setParams({ LDIPOL: '', IDIPOL: '', DIPOL: '', EFIELD: '' });
      return;
    }
    setParams({
      LDIPOL: '.TRUE.',
      IDIPOL: String(params.IDIPOL ?? '').trim() || '3',
      // EFIELD 只有一个数值（方向由 IDIPOL 决定），开关打开时保持已填的值
      EFIELD: String(params.EFIELD ?? '').trim(),
      DIPOL: joinDipol(dipolParts),
    });
  };

  const updateDipolPart = (index: number, value: string) => {
    const next = [...dipolParts] as [string, string, string];
    next[index] = value;
    setDipolParts(next);
    // 三个分量都非空才写入；否则置空（不写入 INCAR）
    setParams({ DIPOL: joinDipol(next) });
  };

  /* ---------- 卡片集合：通用分类 + DFT+U + 偶极矩修正 ---------- */

  const categoryCards = INCAR_CATEGORIES.map((cat) => (
    <Card key={cat.key} size="small" title={cat.label} className="job-card job-incar-cat">
      <div className="job-incar-fields">
        {cat.params
          .filter((def) => !def.fracOnly || task.task_type === 'frac')
          .map((def) => (
            <div
              key={def.key}
              className={`job-incar-field${
                pendingSet.has(def.key) ? ' is-pending' : isChanged(def.key) ? ' is-changed' : ''
              }`}
            >
              <div className="job-incar-field__label">
                <Tooltip title={def.hint}>
                  <span>{def.label}</span>
                </Tooltip>
                {pendingSet.has(def.key) && (
                  <Tooltip
                    title={`本次计算值：${snapshotParams[def.key] ?? '无'} · 待下次续算生效`}
                  >
                    <span className="job-incar-field__badge">待生效</span>
                  </Tooltip>
                )}
              </div>
              <div className="job-incar-field__control">{renderField(def)}</div>
            </div>
          ))}
      </div>
    </Card>
  ));

  const ldauCard = (
    <Card
      key="ldau"
      size="small"
      title="DFT+U"
      className="job-card job-incar-cat"
      extra={
        <Tooltip
          title={
            !editing
              ? '点右上角「修改参数」后可编辑'
              : ldauEnabled
                ? '关闭：不写入任何 LDAU* 参数'
                : '打开：写入 LDAU = .TRUE. 与下方元素表'
          }
        >
          <Switch size="small" checked={ldauEnabled} disabled={!editing} onChange={toggleLdau} />
        </Tooltip>
      }
    >
      <div className={`job-incar-fields${ldauEnabled ? '' : ' job-incar-off'}`}>
        <div className="job-incar-field">
          <div className="job-incar-field__label">
            <Tooltip title="DFT+U 类型（1 = Liechtenstein，2 = Dudarev，4 = 带交换分裂）">
              <span>LDAUTYPE</span>
            </Tooltip>
          </div>
          <div className="job-incar-field__control">
            <Select
              style={{ width: '100%' }}
              value={String(params.LDAUTYPE ?? '').trim() || '1'}
              disabled={ldauLocked}
              onChange={(value) => setParam('LDAUTYPE', value)}
              options={LDAUTYPE_OPTIONS.map((opt) => ({ value: opt.value, label: opt.label }))}
            />
          </div>
        </div>
        <div className="job-incar-field">
          <div className="job-incar-field__label">
            <Tooltip title="电荷混合的最高 l 量子数（d 体系 4，f 体系 6）">
              <span>LMAXMIX</span>
            </Tooltip>
          </div>
          <div className="job-incar-field__control">
            <SciInput
              value={String(params.LMAXMIX ?? '')}
              placeholder="4"
              disabled={ldauLocked}
              onChange={(value) => setParam('LMAXMIX', value)}
            />
          </div>
        </div>
        <div className="job-incar-ldau">
          <div className="job-incar-ldau__head">
            <span>元素</span>
            <span>LDAUL</span>
            <span>LDAUU</span>
            <span>LDAUJ</span>
            <span />
          </div>
          {ldauRowsView.map((row, index) => (
            <div className="job-incar-ldau__row" key={`ldau-${index}`}>
              <span className="job-incar-ldau__elem" title={ldauRowLabel(index)}>
                {ldauRowLabel(index)}
              </span>
              <Select
                size="small"
                value={row.ldaul || '-1'}
                disabled={ldauLocked}
                onChange={(value) => updateLdauRow(index, { ldaul: value })}
                options={LDAUL_OPTIONS.map((opt) => ({ value: opt.value, label: opt.label }))}
              />
              <Input
                size="small"
                value={row.ldauu}
                placeholder="4.0"
                disabled={ldauLocked}
                onChange={(event) => updateLdauRow(index, { ldauu: event.target.value })}
              />
              <Input
                size="small"
                value={row.ldauj}
                placeholder="0.0"
                disabled={ldauLocked}
                onChange={(event) => updateLdauRow(index, { ldauj: event.target.value })}
              />
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                disabled={ldauLocked || ldauRowsView.length <= 1}
                onClick={() => removeLdauRow(index)}
              />
            </div>
          ))}
          <div className="job-incar-ldau__actions">
            <Button
              size="small"
              type="dashed"
              icon={<PlusOutlined />}
              disabled={ldauLocked}
              onClick={addLdauRow}
            >
              添加元素
            </Button>
            <span className="job-field-hint">
              LDAUL / LDAUU / LDAUJ 一一对应，行数变化时三个数组同步更新；LDAUL = -1 表示不加 U
            </span>
          </div>
        </div>
      </div>
    </Card>
  );

  const dipoleCard = (
    <Card
      key="dipole"
      size="small"
      title="偶极矩修正"
      className="job-card job-incar-cat"
      extra={
        <Tooltip
          title={
            !editing
              ? '点右上角「修改参数」后可编辑'
              : dipoleEnabled
                ? '关闭：不写入 LDIPOL / IDIPOL / DIPOL / EFIELD'
                : '打开：写入 LDIPOL = .TRUE.；EFIELD 填了就加上（方向由 IDIPOL 决定）'
          }
        >
          <Switch size="small" checked={dipoleEnabled} disabled={!editing} onChange={toggleDipole} />
        </Tooltip>
      }
    >
      <div className={`job-incar-fields${dipoleEnabled ? '' : ' job-incar-off'}`}>
        <div className="job-incar-field">
          <div className="job-incar-field__label">
            <Tooltip title="偶极矩修正方向（3 = 沿 c 方向，表面/二维体系常用）">
              <span>IDIPOL</span>
            </Tooltip>
          </div>
          <div className="job-incar-field__control">
            <Select
              style={{ width: '100%' }}
              value={String(params.IDIPOL ?? '').trim() || '3'}
              disabled={dipoleLocked}
              onChange={(value) => setParam('IDIPOL', value)}
              options={IDIPOL_OPTIONS.map((opt) => ({ value: opt.value, label: opt.label }))}
            />
          </div>
        </div>
        <div className="job-incar-field">
          <div className="job-incar-field__label">
            <Tooltip title="外加静电场，单位 eV/Å；只填一个数值（正负号决定方向，VASP 的电场定义与常见约定相反：电子沿电场方向移动），方向由 IDIPOL 决定">
              <span>EFIELD</span>
            </Tooltip>
          </div>
          <div className="job-incar-field__control">
            <SciInput
              value={String(params.EFIELD ?? '')}
              placeholder="留空 = 不施加外场"
              disabled={dipoleLocked}
              onChange={(value) => setParam('EFIELD', value)}
            />
            <div className="job-field-hint">
              {!dipoleEnabled
                ? '开关关闭时不写入 EFIELD'
                : String(params.EFIELD ?? '').trim()
                  ? `将写入 EFIELD = ${String(params.EFIELD).trim()}（eV/Å，方向 = IDIPOL ${String(params.IDIPOL ?? '').trim() || '3'}）`
                  : '留空则不施加外场；填数值后按 IDIPOL 的方向施加'}
            </div>
          </div>
        </div>
        <div className="job-incar-field">
          <div className="job-incar-field__label">
            <Tooltip title="偶极矩参考点坐标；三个分量都填写才写入 INCAR">
              <span>DIPOL</span>
            </Tooltip>
          </div>
          <div className="job-incar-field__control">
            <div className="job-incar-dipol">
              {(['x', 'y', 'z'] as const).map((axis, index) => (
                <Input
                  key={axis}
                  size="small"
                  addonBefore={axis}
                  value={dipolParts[index]}
                  placeholder="0.5"
                  disabled={dipoleLocked}
                  onChange={(event) => updateDipolPart(index, event.target.value)}
                />
              ))}
            </div>
            <div className="job-field-hint">
              {!dipoleEnabled
                ? '开关关闭时不写入 DIPOL'
                : joinDipol(dipolParts)
                  ? `将写入 DIPOL = ${joinDipol(dipolParts)}`
                  : '三个分量都填写后才会写入 DIPOL'}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );

  // 两列流式布局：按顺序左右交替，卡片各自自然高度（不做行对齐）
  const incarCards = [...categoryCards, ldauCard, dipoleCard];
  const incarLeftCards = incarCards.filter((_, index) => index % 2 === 0);
  const incarRightCards = incarCards.filter((_, index) => index % 2 === 1);

  return (
    <div className="job-panel">
      <Card size="small" className="job-card job-incar-toolbar">
        <div className="job-incar-toolbar__row">
          <div className="job-incar-toolbar__label">
            精度
            <Tag color={precision === 'custom' ? 'default' : 'processing'} style={{ marginLeft: 8 }}>
              {PRECISION_LABELS[precision]}
            </Tag>
          </div>
          <Segmented
            value={precision}
            onChange={(v) => {
              const mode = v as PrecisionMode;
              if (mode === 'custom') onParamsChange(params, 'custom');
              else applyPrecision(mode);
            }}
            options={[
              { value: 'low', label: '低精度' },
              { value: 'medium', label: '中精度' },
              { value: 'high', label: '高精度' },
              { value: 'custom', label: '自定义' },
            ]}
          />
        </div>
        <div className="job-incar-toolbar__actions">
          <Select
            placeholder="加载预设"
            value={loadValue}
            onChange={applyPreset}
            disabled={!editing}
            style={{ minWidth: 170 }}
            options={presetGroups}
          />
          <Button icon={<SaveOutlined />} disabled={!editing} onClick={() => setSaveOpen(true)}>
            保存为预设
          </Button>
          <Button icon={<SendOutlined />} onClick={onCopyToOthers}>
            复制到其他作业
          </Button>
          <Button icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)}>
            预览 INCAR
          </Button>
          <Button icon={<DownloadOutlined />} onClick={() => void handleSaveLocal()}>
            生成到本地
          </Button>
          <Button icon={<UploadOutlined />} onClick={() => void handleUploadRemote()}>
            <Tooltip title="把当前参数（含未生效修改）写入远端最新目录，这些修改随即标记为已生效；不改动续算逻辑">
              <span>同步到远端</span>
            </Tooltip>
          </Button>
          {editing ? (
            <>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={() => {
                  onConfirmParams(params);
                  setEditing(false);
                }}
              >
                确认修改
              </Button>
              <Button
                icon={<CloseOutlined />}
                onClick={() => {
                  onResetToSnapshot();
                  setEditing(false);
                }}
              >
                <Tooltip title="放弃本次编辑，回到本次计算值 + 已有的待生效修改">
                  <span>取消</span>
                </Tooltip>
              </Button>
            </>
          ) : (
            <Tooltip title="参数默认只读；点击后才会解锁编辑，确认后记为待生效修改（下次续算应用）">
              <Button type="primary" ghost icon={<EditOutlined />} onClick={() => setEditing(true)}>
                修改参数
              </Button>
            </Tooltip>
          )}
        </div>
      </Card>

      <Alert
        type={editing ? 'warning' : 'info'}
        showIcon
        style={{ marginBottom: 14 }}
        message={
          editing
            ? '参数编辑中：改完点「确认修改」才会记为待生效修改（下一次续算时写入新目录）'
            : `当前任务类型：${TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type} · 参数来自本次计算（只读）`
        }
        description={
          editing
            ? '留空的参数不会写入 INCAR；已修改的参数会高亮显示，可在顶部横幅里逐项撤销（撤销主开关会连带撤销整组依赖参数）。'
            : '点右上角「修改参数」解锁编辑；低/中/高精度会自动填充推荐参数。'
        }
      />

      <div className="job-incar-grid">
        <div className="job-incar-col">{incarLeftCards}</div>
        <div className="job-incar-col">{incarRightCards}</div>
      </div>

      <Card
        size="small"
        title="其他参数"
        className="job-card job-incar-cat"
        style={{ marginTop: 14 }}
        extra={
          editing ? (
            <Button size="small" type="link" icon={<PlusOutlined />} onClick={addExtraParam}>
              添加参数
            </Button>
          ) : null
        }
      >
        <div className="job-field-hint" style={{ marginBottom: 8 }}>
          不在预设表单里的参数（本次计算实际使用；留空即不写入 INCAR）
        </div>
        {extraRows.length === 0 ? (
          <div className="job-incar-extra__empty">
            <span className="job-field-hint">
              {editing
                ? '还没有其他参数，点「添加参数」新增一行'
                : '本次计算没有预设之外的参数（点右上角「修改参数」后可添加）'}
            </span>
            {editing && (
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addExtraParam}>
                添加参数
              </Button>
            )}
          </div>
        ) : (
          <div className="job-incar-extra">
            {extraRows.map((row) => (
              <div
                key={row.id}
                className={`job-incar-extra__row${
                  pendingSet.has(row.key.trim().toUpperCase()) ? ' is-pending' : ''
                }`}
              >
                <Input
                  value={row.key}
                  disabled={!editing}
                  placeholder="参数名"
                  className="job-incar-extra__key"
                  onChange={(e) => renameExtraParam(row.id, e.target.value)}
                />
                <span className="job-incar-extra__eq">=</span>
                <Input
                  value={row.value}
                  disabled={!editing}
                  placeholder="值（留空不写入）"
                  onChange={(e) => setExtraParamValue(row.id, e.target.value)}
                />
                {editing && (
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeExtraParam(row.id)}
                  />
                )}
              </div>
            ))}
            {editing && (
              <Button
                size="small"
                type="dashed"
                icon={<PlusOutlined />}
                style={{ marginTop: 8 }}
                onClick={addExtraParam}
              >
                添加参数
              </Button>
            )}
          </div>
        )}
      </Card>

      <Modal
        title="保存为预设"
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={() => {
          if (!presetName.trim()) {
            message.warning('请输入预设名称');
            return;
          }
          onSavePreset(presetName.trim());
          setPresetName('');
          setSaveOpen(false);
        }}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginTop: 8 }}>
          <Input
            placeholder="如：Ag111 高精度结构优化"
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            onPressEnter={() => {
              if (presetName.trim()) {
                onSavePreset(presetName.trim());
                setPresetName('');
                setSaveOpen(false);
              }
            }}
          />
          <div className="preview-note" style={{ marginTop: 8 }}>
            预设保存在浏览器本地（localStorage），后续接入后端后迁移到服务器 JSON 文件。
          </div>
        </div>
      </Modal>

      <Drawer
        title={
          <span>
            <BookOutlined /> INCAR 预览
            <span className="preview-note" style={{ marginLeft: 10 }}>
              {task.model_name}
            </span>
          </span>
        }
        width="min(560px, calc(100vw - 32px))"
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        extra={
          <Button icon={<CopyOutlined />} onClick={copyPreview}>
            复制
          </Button>
        }
      >
        <div className="preview-note" style={{ marginBottom: 10 }}>
          随参数实时更新；「生成到本地」写入任务目录 files/INCAR
        </div>
        <pre className="file-preview" style={{ maxHeight: 'calc(100vh - 180px)' }}>
          {incarText || '（暂无参数）'}
        </pre>
      </Drawer>
    </div>
  );
}
