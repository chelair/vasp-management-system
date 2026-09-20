import { Route, Routes, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { Navigate, useLocation as useLocationRaw } from 'react-router-dom';
import { Spin } from 'antd';
import { AnimatePresence } from 'framer-motion';
import AppLayout from './components/layout/AppLayout';
import { useAuth } from './context/AuthContext';
import Dashboard from './pages/Dashboard';
import Inspection from './pages/Inspection';
import Jobs from './pages/Jobs';
import Login from './pages/Login';
import Report from './pages/Report';
import SSH from './pages/SSH';

/** 受保护路由：未登录（或本地 token 失效）时跳登录页，并记住原地址 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocationRaw();
  if (!ready) {
    return (
      <div className="app-loading">
        <Spin size="large" tip="正在校验登录状态…" />
      </div>
    );
  }
  if (!user) {
    const from = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?from=${from}`} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const location = useLocation();

  return (
    // key=location.pathname 让 AnimatePresence 感知路由变化，
    // 页面切换时先播放旧页面退场动画（250ms），再进入新页面
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="/inspection" element={<Inspection />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/report" element={<Report />} />
          <Route path="/ssh" element={<SSH />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </AnimatePresence>
  );
}
