import { useEffect, useRef, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Alert } from 'antd';
import Sidebar from './Sidebar';
import TopBar from './TopBar';

/** 依赖提示条"已关闭"记录键：值为缺失依赖集合签名，集合不变则不再次弹出 */
const DEPS_DISMISS_KEY = 'vasp.deps.banner.dismissed';

export default function AppLayout() {
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [missingDeps, setMissingDeps] = useState<string[]>([]);
  const [depsSignature, setDepsSignature] = useState('');
  const contentRef = useRef<HTMLElement>(null);

  // 路由切换后内容区回到顶部
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [location.pathname]);

  // 运行时后台检查 Python 依赖：缺失时提示安装命令（后端不可用时静默跳过）；
  // 关闭后记录签名，刷新或切换页面不再重复弹出
  useEffect(() => {
    fetch('/api/deps')
      .then((res) => res.json())
      .then((body) => {
        if (body?.success) {
          const missing = (body.data.dependencies as Array<{
            name: string;
            purpose: string;
            installed: boolean;
          }>).filter((d) => !d.installed);
          if (missing.length) {
            const signature = missing.map((d) => d.name).sort().join(',');
            let dismissed = false;
            try {
              dismissed = localStorage.getItem(DEPS_DISMISS_KEY) === signature;
            } catch {
              // localStorage 不可用时每次都会显示
            }
            if (!dismissed) {
              setDepsSignature(signature);
              setMissingDeps(missing.map((d) => `${d.name}（${d.purpose}）`));
            }
          }
        }
      })
      .catch(() => {
        // 后端未启动时不提示
      });
  }, []);

  return (
    <div className="app-shell">
      <Sidebar open={navOpen} onNavigate={() => setNavOpen(false)} />
      {navOpen && (
        <div className="sidebar-overlay" onClick={() => setNavOpen(false)} />
      )}
      <div className="app-main">
        <TopBar onMenuClick={() => setNavOpen(true)} />
        <main className="app-content" ref={contentRef}>
          {missingDeps.length > 0 && (
            <Alert
              type="warning"
              showIcon
              closable
              onClose={() => {
                if (depsSignature) {
                  try {
                    localStorage.setItem(DEPS_DISMISS_KEY, depsSignature);
                  } catch {
                    // localStorage 不可用时静默忽略
                  }
                }
                setMissingDeps([]);
              }}
              style={{ marginBottom: 16 }}
              message="检测到未安装的 Python 依赖"
              description={`缺失：${missingDeps.join('、')}。请在后端目录执行：pip install -r requirements.txt（可选依赖不影响当前功能，后续功能将用到）`}
            />
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
