import { Route, Routes } from 'react-router-dom';
import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, useLocation as useLocationRaw } from 'react-router-dom';
import { Spin } from 'antd';
import AppLayout from './components/layout/AppLayout';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/common/ErrorBoundary';
const Automation = lazy(() => import('./pages/Automation'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Inspection = lazy(() => import('./pages/Inspection'));
const Jobs = lazy(() => import('./pages/Jobs'));
const Login = lazy(() => import('./pages/Login'));
const Report = lazy(() => import('./pages/Report'));
const SSH = lazy(() => import('./pages/SSH'));
const AI = lazy(() => import('./pages/AI'));
const Settings = lazy(() => import('./pages/Settings'));

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

/** 管理员路由：非 admin（或未登录）访问直接跳首页（第 5 步） */
export function AdminRoute({ children }: { children: ReactNode }) {
  const { isAdmin, user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="app-loading">
        <Spin size="large" tip="正在校验登录状态…" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<div className="app-loading"><Spin size="large" tip="正在加载页面…" /></div>}>
      <Routes>
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
          <Route path="/settings" element={<Settings />} />
          <Route path="/ai" element={<ErrorBoundary title="AI 工作台加载失败"><AI /></ErrorBoundary>} />
          <Route path="/report" element={
            <ErrorBoundary title="报告加载失败" hint="可点击重试，或切换到其他页面。">
              <Report />
            </ErrorBoundary>
          } />
          <Route
            path="/automation"
            element={
              <AdminRoute>
                <Automation />
              </AdminRoute>
            }
          />
          <Route
            path="/ssh"
            element={
              <AdminRoute>
                <SSH />
              </AdminRoute>
            }
          />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
