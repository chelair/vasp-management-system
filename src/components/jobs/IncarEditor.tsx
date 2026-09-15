import { useMemo, useState } from 'react';
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
  buildIncarText,
  extraIncarParams,
} from '../../data/mock/incar';
import { saveTaskFile, uploadIncar } from '../../api/jobs';
import SciInput from './SciInput';

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
  /** 取消修改：回到快照值 */
  onResetToSnapshot: () => void;
}

const TRUE_SET = new Set(['1', 'true', 'TRUE', '.TRUE.', 'yes']);

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
  const extraParams = useMemo(() => extraIncarParams(params), [params]);
  const isChanged = (key: string) => {
    const base = String(snapshotParams[key] ?? '');
    const now = String(params[key] ?? '');
    return now !== base && (now !== '' || base !== '');
  };

  const setParam = (key: string, value: string) => {
    // 手动修改任意参数后，自动切换为「自定义」
    onParamsChange({ ...params, [key]: value }, 'custom');
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
      // 以当前表单参数为基础，后端基于远端旧 INCAR 做统一修改
      // 留空（空字符串/仅空白）的参数不参与写入：与「生成 INCAR」一致
      const merged = Object.fromEntries(
        Object.entries(workspace.incarParams).filter(
          ([, value]) => String(value ?? '').trim() !== '',
        ),
      );
      const r = await uploadIncar(task.task_id, { params: merged });
      message.success(
        `INCAR 已上传到远端${r.backup_file ? `，旧文件已备份为 ${r.backup_file}` : ''}`,
      );
      if (r.warnings.length > 0) {
        message.warning(r.warnings.join('；'));
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '上传 INCAR 失败');
    }
  };

  /** 其他参数（不在预设表单里的键）：改名 / 改值 / 新增 / 删除 */
  const renameExtraParam = (oldKey: string, nextKey: string) => {
    const next = { ...params };
    const value = next[oldKey] ?? '';
    delete next[oldKey];
    const key = nextKey.trim().toUpperCase();
    if (key) next[key] = value;
    onParamsChange(next, 'custom');
  };

  const addExtraParam = () => {
    let index = 1;
    while (params[`NEW_PARAM_${index}`] !== undefined) index += 1;
    onParamsChange({ ...params, [`NEW_PARAM_${index}`]: '' }, 'custom');
  };

  const removeExtraParam = (key: string) => {
    const next = { ...params };
    delete next[key];
    onParamsChange(next, 'custom');
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
      const checked = TRUE_SET.has(String(value).trim());
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
            上传到远端
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
                取消
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
            ? '留空的参数不会写入 INCAR；已修改的参数会高亮显示，可随时在顶部横幅里撤销。'
            : '点右上角「修改参数」解锁编辑；低/中/高精度会自动填充推荐参数。'
        }
      />

      <div className="job-incar-grid">
        {INCAR_CATEGORIES.map((cat) => (
          <Card
            key={cat.key}
            size="small"
            title={cat.label}
            className="job-card job-incar-cat"
          >
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
        ))}
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
          不在预设表单里的参数（本次计算实际使用，可编辑；留空即不写入 INCAR）
        </div>
        {Object.keys(extraParams).length === 0 && !editing ? (
          <div className="job-empty-hint">本次计算没有预设之外的参数</div>
        ) : (
          <div className="job-incar-extra">
            {Object.entries(extraParams).map(([key, value]) => (
              <div
                key={key}
                className={`job-incar-extra__row${pendingSet.has(key) ? ' is-pending' : ''}`}
              >
                <Input
                  value={key}
                  disabled={!editing}
                  className="job-incar-extra__key"
                  onChange={(e) => renameExtraParam(key, e.target.value)}
                />
                <span className="job-incar-extra__eq">=</span>
                <Input
                  value={String(value)}
                  disabled={!editing}
                  onChange={(e) => onParamsChange({ ...params, [key]: e.target.value }, 'custom')}
                />
                {editing && (
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeExtraParam(key)}
                  />
                )}
              </div>
            ))}
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
