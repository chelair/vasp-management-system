import { Alert, Tag, Typography } from 'antd';
import type { InspectionDetail } from '../../types';

type CheckError = NonNullable<InspectionDetail['check_errors']>[number];

interface Props {
  errors: CheckError[];
  /** 知识库未收录时报错原文（兜底提取） */
  errorText?: string | null;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
};

/**
 * OUTCAR 报错诊断面板（巡检详情页）。
 *
 * 数据来自巡检知识库（`data/config/check_errors.json`，随巡检脚本上传）：
 * - 命中条目 → 名称 / 分类 / 说明 / 解决方法 / 原文证据；
 * - 未命中但**像报错** → 兜底提取原文（`error_text`），方便补进知识库。
 * OUTCAR 的 WARNING 暂不处理。
 */
export default function CheckErrorsPanel({ errors, errorText }: Props) {
  return (
    <div className="check-errors">
      {errors.map((item, index) => (
        <div className="check-errors__item" key={`${item.id || 'err'}-${item.image ?? ''}-${index}`}>
          <div className="check-errors__head">
            <Tag color={SEVERITY_COLOR[item.severity ?? 'high'] ?? 'red'}>
              {(item.severity ?? 'high').toUpperCase()}
            </Tag>
            <span className="check-errors__name">{item.name || 'OUTCAR 报错'}</span>
            {item.image != null && <Tag>映像 {item.image}</Tag>}
            {item.category && <Tag color="default">{item.category}</Tag>}
            {item.id && <span className="check-errors__id">{item.id}</span>}
          </div>
          {item.message && <div className="check-errors__msg">{item.message}</div>}
          {(item.advice?.length ?? 0) > 0 && (
            <>
              <div className="check-errors__subtitle">解决方法</div>
              <ul className="check-errors__advice">
                {(item.advice ?? []).map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </>
          )}
          {item.evidence && (
            <div className="check-errors__evidence">
              <div className="check-errors__subtitle">
                OUTCAR 原文{item.matched ? `（命中「${item.matched}」）` : ''}
              </div>
              <pre>{item.evidence}</pre>
            </div>
          )}
        </div>
      ))}

      {errorText && (
        <Alert
          type="warning"
          showIcon
          message="OUTCAR 疑似报错，但知识库暂未收录"
          description={
            <>
              <Typography.Text type="secondary">
                下面是从 OUTCAR 提取到的报错原文；确认原因后可把它补进
                <code> data/config/check_errors.json </code>
                的 <code>errors</code> 列表，下一轮巡检即可自动识别并给出解决方法。
              </Typography.Text>
              <pre className="check-errors__raw">{errorText}</pre>
            </>
          }
        />
      )}
    </div>
  );
}
