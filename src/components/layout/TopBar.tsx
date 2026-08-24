import { useLocation, useNavigate } from 'react-router-dom';
import { Button, Tooltip } from 'antd';
import { ClockCircleOutlined, MenuOutlined } from '@ant-design/icons';
import { useClock } from '../../hooks/useClock';
import { useSSH } from '../../context/SSHContext';

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
  const title = TITLES[location.pathname] ?? 'VASP 计算项目管理系统';

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
            activeServer
              ? `当前连接：${activeServer.user}@${activeServer.host}:${activeServer.port}（点击管理）`
              : '未连接任何服务器，点击进行 SSH 配置'
          }
        >
          <div
            className={`ssh-chip${activeServer ? '' : ' ssh-chip--off'}`}
            onClick={() => navigate('/ssh')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter') navigate('/ssh');
            }}
          >
            <span className="ssh-dot" />
            {activeServer ? 'SSH 已连接' : 'SSH 未连接'}
            {activeServer && (
              <span className="ssh-chip__host">
                {activeServer.user}@{activeServer.host}:{activeServer.port}
              </span>
            )}
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
