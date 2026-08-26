import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Spin,
} from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { fetchReports, generateReport } from '../api/reports';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatusTag from '../components/common/StatusTag';
import type { ReportRecord, RiskItem } from '../types';

const LEVEL_META: Record<RiskItem['level'], { label: string; color: string; bg: string }> = {
  high: { label: '高风险', color: '#D9535B', bg: '#FDECED' },
  medium: { label: '中风险', color: '#D18A2B', bg: '#FEF3E0' },
  low: { label: '低风险', color: '#4A7BDD', bg: '#EAF1FF' },
};

export default function Report() {
  const { message } = App.useApp();
  const [history, setHistory] = useState<ReportRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [configForm] = Form.useForm();

  useEffect(() => {
    fetchReports().then((rs) => {
      setHistory(rs);
      setSelectedId(rs[0]?.id ?? null);
    }).finally(() => setLoading(false));
  }, []);

  const selected = useMemo(
    () => history.find((r) => r.id === selectedId) ?? null,
    [history, selectedId],
  );

  const handleGenerate = async () => {
    setGenerating(true);
    const record = await generateReport();
    setHistory((prev) => [record, ...prev]);
    setSelectedId(record.id);
    setGenerating(false);
    message.success('报告生成完成（演示数据）');
  };

  const saveConfig = async () => {
    await configForm.validateFields();
    setConfigOpen(false);
    message.info('API 配置已保存（演示，仅前端占位，不会真正调用大模型）');
  };

  return (
    <PageTransition>
      <PageHeader
        title="智能报告"
        subtitle="将项目进度、巡检结果与作业信息作为输入，生成固定格式的风险与建议报告"
        extra={
          <div className="header-actions">
            <Button icon={<ApiOutlined />} onClick={() => setConfigOpen(true)}>
              API 配置
            </Button>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={generating}
              onClick={handleGenerate}
            >
              生成报告
            </Button>
          </div>
        }
      />

      <div className="report-grid">
        <Card title="历史记录" loading={loading}>
          <div className="history-list">
            {history.map((r) => (
              <div
                key={r.id}
                className={`history-item${r.id === selectedId ? ' active' : ''}`}
                onClick={() => setSelectedId(r.id)}
              >
                <div className="history-item__title">{r.title}</div>
                <div className="history-item__meta">
                  <span>{r.generated_at}</span>
                  <StatusTag status={r.status} kind="report" />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="报告模板预览">
          <Spin spinning={generating} tip="正在生成报告...">
            {selected ? (
              <div className="report-template">
                <div className="report-template__title">{selected.title}</div>
                <div className="report-template__meta">
                  生成时间：{selected.generated_at} · 数据来源：项目进度 / 巡检结果 / 作业信息
                </div>

                <section className="report-section">
                  <h3>摘要</h3>
                  <p>{selected.summary}</p>
                </section>

                <section className="report-section">
                  <h3>风险项（{selected.risks.length}）</h3>
                  {selected.risks.map((risk, i) => {
                    const meta = LEVEL_META[risk.level];
                    return (
                      <div className="risk-item" key={i}>
                        <span className="level-tag" style={{ color: meta.color, background: meta.bg }}>
                          {meta.label}
                        </span>
                        <span>{risk.content}</span>
                      </div>
                    );
                  })}
                </section>

                <section className="report-section">
                  <h3>改进建议（{selected.suggestions.length}）</h3>
                  {selected.suggestions.map((s, i) => (
                    <div className="suggest-item" key={i}>
                      <CheckCircleOutlined />
                      <span>{s}</span>
                    </div>
                  ))}
                </section>

                <div className="report-template__footer">
                  本报告由 AI 助手根据项目数据自动生成 · 当前为前端演示模板
                </div>
              </div>
            ) : (
              <Empty description="暂无报告，点击右上角「生成报告」" />
            )}
          </Spin>
        </Card>
      </div>

      <Modal
        title="大模型 API 配置"
        open={configOpen}
        onOk={saveConfig}
        onCancel={() => setConfigOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={configForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            label="模型服务"
            name="provider"
            initialValue="gpt-4"
            rules={[{ required: true, message: '请选择模型服务' }]}
          >
            <Select
              options={[
                { value: 'gpt-4', label: 'OpenAI GPT-4' },
                { value: 'claude', label: 'Anthropic Claude' },
                { value: 'deepseek', label: 'DeepSeek' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="API Key"
            name="apiKey"
            rules={[{ required: true, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item label="Base URL（可选）" name="baseUrl">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
        </Form>
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.7 }}>
          演示阶段仅保存到前端状态，不会发起真实请求；正式版将把项目进度、巡检结果、作业信息组装为 Prompt 后调用。
        </div>
      </Modal>
    </PageTransition>
  );
}
