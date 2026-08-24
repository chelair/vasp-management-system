import { Route, Routes, useLocation } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import AppLayout from './components/layout/AppLayout';
import Dashboard from './pages/Dashboard';
import Inspection from './pages/Inspection';
import Jobs from './pages/Jobs';
import Report from './pages/Report';
import SSH from './pages/SSH';

export default function App() {
  const location = useLocation();

  return (
    // key=location.pathname 让 AnimatePresence 感知路由变化，
    // 页面切换时先播放旧页面退场动画（250ms），再进入新页面
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route element={<AppLayout />}>
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
