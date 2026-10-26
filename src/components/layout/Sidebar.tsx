import { NavLink } from 'react-router-dom';
import { Button, Tooltip } from 'antd';
import {
  ApiOutlined,
  AppstoreOutlined,
  FolderOpenOutlined,
  FileTextOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  RobotOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons';
import BrandLogo from './BrandLogo';
import { useAuth } from '../../context/AuthContext';

const NAV_ITEMS = [
  { to: '/', label: '总览', icon: <AppstoreOutlined />, end: true },
  { to: '/inspection', label: '巡检中心', icon: <SafetyCertificateOutlined /> },
  { to: '/jobs', label: '作业管理', icon: <FolderOpenOutlined /> },
  { to: '/report', label: '智能报告', icon: <FileTextOutlined /> },
  { to: '/ai', label: 'AI 工作台', icon: <RobotOutlined /> },
];

interface Props {
  open: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNavigate: () => void;
}

export default function Sidebar({ open, collapsed, onToggleCollapse, onNavigate }: Props) {
  const { isAdmin } = useAuth();
  const tooltip = (label: string) => collapsed && !open ? label : undefined;
  const navItem = (item: (typeof NAV_ITEMS)[number]) => <Tooltip key={item.to} title={tooltip(item.label)} placement="right" trigger={['hover', 'focus']}>
    <NavLink to={item.to} end={item.end} aria-label={item.label} onClick={onNavigate}
      className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
      <span className="nav-item__icon" aria-hidden="true">{item.icon}</span><span className="nav-item__label">{item.label}</span>
    </NavLink>
  </Tooltip>;
  return (
    <aside className={`sidebar${open ? ' open' : ''}${collapsed ? ' sidebar--collapsed' : ''}`} aria-label="总导航">
      <div className="sidebar__brand">
        <BrandLogo />
        <div className="sidebar__brand-text">
          <div className="sidebar__brand-name">VASP 项目管理系统</div>
          <div className="sidebar__brand-sub">第一性原理计算</div>
        </div>
      </div>

      <nav className="sidebar__nav">
        <div className="nav-section-label">功能模块</div>
        {NAV_ITEMS.map(navItem)}

        <div className="nav-section-label">资源</div>
        <Tooltip title={tooltip('VASP 官方文档')} placement="right" trigger={['hover', 'focus']}><a
          className="nav-item"
          aria-label="VASP 官方文档"
          href="https://www.vasp.at"
          target="_blank"
          rel="noreferrer"
        >
          <span className="nav-item__icon" aria-hidden="true">
            <ReadOutlined />
          </span>
          <span className="nav-item__label">VASP 官方文档</span>
        </a></Tooltip>

        {isAdmin && (
          <>
            <div className="nav-section-label">系统</div>
            {navItem({ to: '/automation', label: '自动化', icon: <ThunderboltOutlined /> })}
            {navItem({ to: '/ssh', label: 'SSH 连接', icon: <ApiOutlined /> })}
          </>
        )}
      </nav>

      <div className="sidebar__footer">
        <Tooltip title={tooltip('展开总导航')} placement="right" trigger={['hover', 'focus']}>
          <Button className="sidebar__collapse" type="text" aria-label={collapsed ? '展开总导航' : '收起总导航'} aria-expanded={!collapsed}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={onToggleCollapse}>
            <span className="nav-item__label">收起导航</span>
          </Button>
        </Tooltip>
        <div className="storage-badge">
          <div>本地存储：JSON / SQLite</div>
          <div style={{ marginTop: 4, color: 'var(--color-text-muted)', fontSize: 11 }}>
            v1.1.4
          </div>
        </div>
      </div>
    </aside>
  );
}
