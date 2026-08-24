import { useMemo, useState } from 'react';
import { App, Button, Card, InputNumber, Radio, Tag } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { buildKpoints, parsePoscar, recommendKgrid } from '../../utils/poscar';

interface Props {
  taskName: string;
  poscarContent: string | null;
  kpointsContent: string | null;
  onGenerate: (content: string) => void;
}

export default function KpointsPanel({
  taskName,
  poscarContent,
  kpointsContent,
  onGenerate,
}: Props) {
  const { message } = App.useApp();
  const [density, setDensity] = useState(20);
  const [meshType, setMeshType] = useState<'Gamma' | 'Monkhorst-Pack'>('Gamma');

  const info = useMemo(() => (poscarContent ? parsePoscar(poscarContent) : null), [poscarContent]);
  const grid = useMemo(
    () => (info ? recommendKgrid(info.lengths, density) : null),
    [info, density],
  );

  const generate = () => {
    if (!grid || !info) {
      message.warning('请先在 POSCAR 页导入结构文件');
      return;
    }
    const content = buildKpoints(taskName, meshType, grid, density);
    onGenerate(content);
    message.success(
      `KPOINTS 已生成：${grid.join(' × ')}（${meshType}，密度 ${density}）`,
    );
  };

  return (
    <div className="job-panel">
      <Card size="small" title="K 点网格生成" className="job-card">
        {info && grid ? (
          <>
            <div className="job-kpoints-form">
              <div className="job-kpoints-field">
                <span className="job-kpoints-field__label">网格密度系数</span>
                <InputNumber
                  min={5}
                  max={200}
                  value={density}
                  onChange={(v) => setDensity(v ?? 20)}
                  style={{ width: 140 }}
                />
                <span className="preview-note">默认 20（约每埃 20 个 k 点）</span>
              </div>
              <div className="job-kpoints-field">
                <span className="job-kpoints-field__label">网格类型</span>
                <Radio.Group
                  value={meshType}
                  onChange={(e) => setMeshType(e.target.value)}
                  optionType="button"
                  buttonStyle="solid"
                  options={[
                    { value: 'Gamma', label: 'Gamma-centered' },
                    { value: 'Monkhorst-Pack', label: 'Monkhorst-Pack' },
                  ]}
                />
              </div>
            </div>

            <div className="job-kpoints-result">
              <div className="job-kpoints-result__label">
                推荐网格
                <span className="preview-note">
                  {' '}
                  ≈ 密度系数 / 晶格常数（四舍五入，最小 1）
                </span>
              </div>
              <div className="job-kpoints-grid">
                {(['a', 'b', 'c'] as const).map((axis, i) => (
                  <div key={axis} className="job-kpoints-grid__cell">
                    <div className="job-kpoints-grid__num">{grid[i]}</div>
                    <div className="job-kpoints-grid__lbl">
                      {axis} = {info.lengths[axis].toFixed(3)} Å
                    </div>
                  </div>
                ))}
                <div className="job-kpoints-grid__arrow">→</div>
                <div className="job-kpoints-grid__sum">
                  <div className="job-kpoints-grid__num">{grid.join(' ')}</div>
                  <div className="job-kpoints-grid__lbl">{meshType}</div>
                </div>
              </div>
              <Tag color="geekblue" style={{ marginTop: 12 }}>
                总 k 点数：{grid[0] * grid[1] * grid[2]}
              </Tag>
            </div>

            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={generate}
              style={{ marginTop: 16 }}
            >
              生成 KPOINTS 文件
            </Button>
          </>
        ) : (
          <div className="job-empty-hint">
            未检测到 POSCAR 结构，请先在「POSCAR」页导入文件。
          </div>
        )}
      </Card>

      <Card
        size="small"
        title="KPOINTS 预览"
        className="job-card mt-16"
        extra={
          kpointsContent && (
            <span className="preview-note">已生成 · 保存至 {taskName}/KPOINTS</span>
          )
        }
      >
        {kpointsContent ? (
          <pre className="file-preview">{kpointsContent}</pre>
        ) : (
          <div className="job-empty-hint">尚未生成 KPOINTS 文件。</div>
        )}
      </Card>
    </div>
  );
}
