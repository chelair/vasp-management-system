import { useEffect, useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/**
 * 登录页（v0.9.0 第 2 步）。
 *
 * 登录成功后 token 交 `AuthContext` 保存，并跳回 `?from=` 指定的原页面。
 */
export default function Login() {
  const { login, user, ready } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<{ username: string; password: string }>();

  const from = new URLSearchParams(location.search).get('from') || '/';

  useEffect(() => {
    form.setFieldsValue({ username: '' });
  }, [form]);

  if (ready && user) {
    return <Navigate to={from} replace />;
  }

  const submit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      setError(null);
      const logged = await login(values.username.trim(), values.password);
      navigate(from, { replace: true });
      // 提示（放在导航之后，避免被卸载打断）
      console.info(`已登录：${logged.username}（${logged.role}）`);
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return; // 表单校验失败
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="login-brand__title">VASP 计算项目管理系统</div>
          <div className="login-brand__subtitle">请登录后使用（账号由管理员创建）</div>
        </div>

        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 14 }}
            closable
            onClose={() => setError(null)}
          />
        )}

        <Form form={form} layout="vertical" onFinish={submit} autoComplete="on">
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="用户名"
              autoFocus
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="密码"
              autoComplete="current-password"
              onPressEnter={() => void submit()}
            />
          </Form.Item>
          <Button type="primary" size="large" block loading={submitting} onClick={() => void submit()}>
            登录
          </Button>
        </Form>

        <div className="login-footnote">
          忘记密码请联系管理员重置：<code>python scripts/set_password.py &lt;用户名&gt;</code>
        </div>
      </div>
    </div>
  );
}
