import { Input, Tooltip } from 'antd';
import { CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons';

/**
 * 支持科学计数法的数值输入框。
 * 值为字符串，便于保留用户输入形式（如 1E-5）；失焦时自动规范化（1e-5 → 1E-5）。
 */
interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  suffix?: string;
  size?: 'small' | 'middle';
  disabled?: boolean;
}

/** 单个数值，或空格分隔的多个数值（如 DIPOL = 0.5 0.5 0.18、MAGMOM = 5*2.0） */
const NUM_RE = /^([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?|\d+\*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)(\s+([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?|\d+\*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?))*$/;

export default function SciInput({ value, onChange, placeholder, suffix, size, disabled }: Props) {
  const v = String(value ?? '');
  const invalid = v.trim() !== '' && !NUM_RE.test(v.trim());
  const normalize = () => {
    const t = v.trim();
    if (NUM_RE.test(t)) {
      onChange(
        t
          .split(/\s+/)
          .map((part) => part.replace(/^\+/, '').replace(/e([+-]?\d+)$/i, 'E$1'))
          .join(' '),
      );
    }
  };
  return (
    <Tooltip title={invalid ? '请输入合法数值，支持科学计数法（如 1E-5）' : ''}>
      <Input
        size={size ?? 'middle'}
        value={v}
        disabled={disabled}
        placeholder={placeholder ?? '数值'}
        status={invalid ? 'error' : undefined}
        suffix={
          suffix ? (
            <span className="sci-input__suffix">
              {suffix}
              {invalid ? (
                <ExclamationCircleOutlined style={{ color: 'var(--color-danger)', marginLeft: 6 }} />
              ) : (
                v.trim() !== '' && (
                  <CheckCircleOutlined style={{ color: 'var(--color-success)', marginLeft: 6 }} />
                )
              )}
            </span>
          ) : undefined
        }
        onChange={(e) => onChange(e.target.value)}
        onBlur={normalize}
      />
    </Tooltip>
  );
}
