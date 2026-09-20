import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { App, Button, Dropdown, Tooltip } from 'antd';
import { ClockCircleOutlined, LogoutOutlined, MenuOutlined, UserOutlined } from '@ant-design/icons';
import { useClock } from '../../hooks/useClock';
import { useSSH } from '../../context/SSHContext';
import { useAuth } from '../../context/AuthContext';
import { fetchSshStatus } from '../../api/ssh';
import type { SshStatus } from '../../api/ssh';

/** 角色展示名（第 5 步：顶栏显示用户名 + 角色） */
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  user: '普通用户',
  agent: '智能体',
};

const TITLES: Record<string, string> = {
  '/': '总览',
  '/inspection': '巡检中心',
  '/jobs': '作业管理',
  '/report': '智能报告',
  '/ssh': 'SSH 连接',
};

export default function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  const location = useLocation();
  const clock = useClock();
  const navigate = useNavigate();
  const { activeServer } = useSSH();
  const { user, isAdmin, logout } = useAuth();
  const roleLabel = ROLE_LABELS[String(user?.role ?? '')] ?? String(user?.role ?? '');
  const { modal } = App.useApp();
  const [backendStatus, setBackendStatus] = useState<SshStatus | null>(null);
  const title = TITLES[location.pathname] ?? 'VASP 计算项目管理系统';

  // 轮询后端常驻连接池状态（真实 SSH 连接），后端不可用时回退 UI 状态
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const status = await fetchSshStatus();
      if (alive) setBackendStatus(status);
    };
    void poll();
    const timer = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const connected = backendStatus
    ? backendStatus.connected || !!activeServer
    : !!activeServer;
  const hostLabel =
    backendStatus?.host && backendStatus.user
      ? `${backendStatus.user}@${backendStatus.host}`
      : activeServer
        ? `${activeServer.user}@${activeServer.host}:${activeServer.port}`
        : null;
  const statusText = backendStatus?.mock
    ? 'SSH 模拟模式'
    : connected
      ? `SSH 已连接${backendStatus?.latencyMs != null ? ` · ${backendStatus.latencyMs}ms` : ''}`
      : 'SSH 未连接';

  return (
    <header className="topbar">
      <Button
        className="topbar__menu"
        type="text"
        icon={<MenuOutlined />}
        onClick={onMenuClick}
        aria-label="打开导航"
      />
      <div className="topbar__title">{title}</div>

      <div className="topbar__right">
        <Tooltip
          title={
            connected
              ? `SSH 常驻连接：${hostLabel ?? '—'}${
                  backendStatus?.latencyMs != null
                    ? `，保活延迟 ${backendStatus.latencyMs}ms${
                        backendStatus.latencyAt
                          ? `（${backendStatus.latencyAt.replace('T', ' ').slice(5, 19)}）`
                          : ''
                      }`
                    : ''
                }${
                  backendStatus?.lastUsedAt
                    ? `，最近使用 ${backendStatus.lastUsedAt.replace('T', ' ').slice(5, 19)}`
                    : ''
                }${isAdmin ? '（点击管理）' : '（仅管理员可管理）'}`
              : 'SSH 未连接，点击进行配置；系统会按需自动重连'
          }
        >
          <div
            className={`ssh-chip${connected ? '' : ' ssh-chip--off'}`}
            onClick={() => isAdmin && navigate('/ssh')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && isAdmin) navigate('/ssh');
            }}
          >
            <span className="ssh-dot" />
            {statusText}
            {hostLabel && <span className="ssh-chip__host">{hostLabel}</span>}
          </div>
        </Tooltip>
        <div className="topbar__divider" />
        <div className="clock-chip">
          <ClockCircleOutlined />
          <span>{clock.date}</span>
          <strong>{clock.time}</strong>
        </div>
        <div className="topbar__divider" />
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              {
                key: 'who',
                label: `${user?.username ?? '未登录'}${roleLabel ? ` · ${roleLabel}` : ''}`,
                disabled: true,
              },
              { type: 'divider' },
              { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
            ],
            onClick: ({ key }) => {
              if (key !== 'logout') return;
              modal.confirm({
                title: '退出登录',
                content: '退出后当前 token 立即失效，需要重新输入账号密码。',
                okText: '退出',
                cancelText: '取消',
                onOk: async () => {
                  await logout();
                  navigate('/login', { replace: true });
                },
              });
            },
          }}
        >
          <div className="topbar__user" role="button" tabIndex={0}>
            <UserOutlined />
            <span>{user?.username ?? '未登录'}</span>
            {roleLabel && <span className="topbar__user-role">{roleLabel}</span>}
          </div>
        </Dropdown>
      </div>
    </header>
  );
}
