import { NavLink } from 'react-router-dom';
import {
  ApiOutlined,
  AppstoreOutlined,
  FolderOpenOutlined,
  FileTextOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import BrandLogo from './BrandLogo';

const NAV_ITEMS = [
  { to: '/', label: '总览', icon: <AppstoreOutlined />, end: true },
  { to: '/inspection', label: '巡检中心', icon: <SafetyCertificateOutlined /> },
  { to: '/jobs', label: '作业管理', icon: <FolderOpenOutlined /> },
  { to: '/report', label: '智能报告', icon: <FileTextOutlined /> },
];

interface Props {
  open: boolean;
  onNavigate: () => void;
}

export default function Sidebar({ open, onNavigate }: Props) {
  return (
    <aside className={`sidebar${open ? ' open' : ''}`}>
      <div className="sidebar__brand">
        <BrandLogo />
        <div>
          <div className="sidebar__brand-name">VASP 项目管理系统</div>
          <div className="sidebar__brand-sub">第一性原理计算</div>
        </div>
      </div>

      <nav className="sidebar__nav">
        <div className="nav-section-label">功能模块</div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          >
            <span className="nav-item__icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}

        <div className="nav-section-label">资源</div>
        <a
          className="nav-item"
          href="https://www.vasp.at"
          target="_blank"
          rel="noreferrer"
        >
          <span className="nav-item__icon">
            <ReadOutlined />
          </span>
          VASP 官方文档
        </a>

        <div className="nav-section-label">系统</div>
        <NavLink
          to="/ssh"
          onClick={onNavigate}
          className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
        >
          <span className="nav-item__icon">
            <ApiOutlined />
          </span>
          SSH 连接
        </NavLink>
      </nav>

      <div className="sidebar__footer">
        <div className="storage-badge">
          <div>存储方式：文件型存储（JSON）</div>
          <div style={{ marginTop: 4, color: 'var(--color-text-muted)', fontSize: 11 }}>
            v0.1.1
          </div>
        </div>
      </div>
    </aside>
  );
}
