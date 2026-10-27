import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import 'antd/dist/reset.css';
import './styles/global.css';
import App from './App';
import { SSHProvider } from './context/SSHContext';
import { AuthProvider } from './context/AuthContext';
import { AppearanceProvider } from './context/AppearanceContext';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <AntdApp>
        <BrowserRouter>
          <AuthProvider>
            <SSHProvider>
            <App />
            </SSHProvider>
          </AuthProvider>
        </BrowserRouter>
      </AntdApp>
    </AppearanceProvider>
  </React.StrictMode>,
);
