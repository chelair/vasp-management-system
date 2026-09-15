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
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
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
  parseCustomIncar,
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
}: Props) {
  const { message } = App.useApp();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [loadValue, setLoadValue] = useState<string | undefined>(undefined);
  const [customText, setCustomText] = useState('');

  const params = workspace.incarParams;
  const precision = workspace.precision;
  const incarText = useMemo(
    () => buildIncarText(params, undefined, customText),
    [params, customText],
  );

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
      // 以当前表单参数 + 自定义参数为基础，后端基于远端旧 INCAR 做统一修改
      // 留空（空字符串/仅空白）的参数不参与写入：与「生成 INCAR」一致
      const merged = Object.fromEntries(
        Object.entries({
          ...workspace.incarParams,
          ...parseCustomIncar(customText),
        }).filter(([, value]) => String(value ?? '').trim() !== ''),
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
          onChange={(v) => setParam(key, v)}
        />
      );
    }
    return (
      <Input
        value={String(value)}
        placeholder={def.placeholder ?? def.defaultValue}
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
            style={{ minWidth: 170 }}
            options={presetGroups}
          />
          <Button icon={<SaveOutlined />} onClick={() => setSaveOpen(true)}>
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
        </div>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message={`当前任务类型：${TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type}`}
        description="低/中/高精度会自动填充推荐参数；修改任一参数后自动切换为「自定义」模式。"
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
                  <div key={def.key} className="job-incar-field">
                    <div className="job-incar-field__label">
                      <Tooltip title={def.hint}>
                        <span>{def.label}</span>
                      </Tooltip>
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
        title="自定义参数"
        className="job-card job-incar-cat"
        style={{ marginTop: 14 }}
      >
        <div className="job-field-hint" style={{ marginBottom: 8 }}>
          手动添加表单之外的参数，每行一个，格式：KEY = value（# / ! 后为注释，会被忽略）
        </div>
        <Input.TextArea
          rows={4}
          value={customText}
          onChange={(e) => setCustomText(e.target.value)}
          placeholder={'例如：\nLVDW = .TRUE.\nVDW_RADIUS = 1.2\nNBANDS = 400'}
          style={{ fontFamily: 'monospace' }}
        />
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
