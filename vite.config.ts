import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 项目未引入 @types/node，这里只声明用到的 process.env 形状
declare const process: { env: Record<string, string | undefined> };

// 后端地址可用 VITE_API_TARGET 覆盖（例如指向隔离测试后端 http://localhost:3002）
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:3001';

// host: true 表示监听 0.0.0.0，同一局域网内的其他电脑可通过
// http://<本机局域网IP>:5173 访问（如 http://192.168.1.100:5173）
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    proxy: {
      // 开发模式下把 /api 转发到 Express 后端（npm run server）
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: true,
    port: 4173,
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'antd-vendor': ['antd', '@ant-design/icons'],
          'motion-vendor': ['framer-motion'],
          // ECharts 只被总览页使用，单独成块便于缓存（按需注册见 components/dashboard/useEcharts.ts）
          'echarts-vendor': ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
        },
      },
    },
  },
});
