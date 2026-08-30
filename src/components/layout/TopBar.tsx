import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button, Tooltip } from 'antd';
import { ClockCircleOutlined, MenuOutlined } from '@ant-design/icons';
import { useClock } from '../../hooks/useClock';
import { useSSH } from '../../context/SSHContext';
import { fetchSshStatus } from '../../api/ssh';
import type { SshStatus } from '../../api/ssh';

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
                }（点击管理）`
              : 'SSH 未连接，点击进行配置；系统会按需自动重连'
          }
        >
          <div
            className={`ssh-chip${connected ? '' : ' ssh-chip--off'}`}
            onClick={() => navigate('/ssh')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter') navigate('/ssh');
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
      </div>
    </header>
  );
}
