import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import {
  fetchServerConfigs,
  fetchSshStatus,
  persistUICache,
  readUICache,
  syncServerConfigs,
  testRemoteConnection,
} from '../api/ssh';
import type { ConnectionTestResult, ServerConfig } from '../types';
import { formatDateTime } from '../utils/format';

interface SSHContextValue {
  servers: ServerConfig[];
  loading: boolean;
  /** 当前已连接的服务器（同一时间最多一个）；未连接时为 null */
  activeServer: ServerConfig | null;
  addServer: (cfg: ServerConfig) => void;
  updateServer: (
    id: string,
    patch: Partial<ServerConfig>,
    opts?: { sync?: boolean },
  ) => void;
  removeServer: (id: string) => void;
  toggleConnection: (id: string) => void;
  testConnection: (id: string) => Promise<ConnectionTestResult>;
}

const SSHContext = createContext<SSHContextValue | null>(null);

export function useSSH(): SSHContextValue {
  const ctx = useContext(SSHContext);
  if (!ctx) {
    throw new Error('useSSH 必须在 <SSHProvider> 内使用');
  }
  return ctx;
}

/**
 * SSH 连接全局状态。
 * 配置（host/user/远程根目录等）以后端 data/config/servers.json 为准，
 * 连接/延迟等 UI 状态保存在 localStorage。
 */
export function SSHProvider({ children }: { children: ReactNode }) {
  const [servers, setServers] = useState<ServerConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const hydrated = useRef(false);

  useEffect(() => {
    fetchServerConfigs().then(({ servers: fetched, source }) => {
      if (source === 'backend') {
        // 配置以后端为准；从本地缓存恢复连接/延迟等 UI 状态
        const cached = readUICache() ?? [];
        setServers(
          fetched.map((server) => {
            const cachedServer = cached.find((s) => s.id === server.id);
            return cachedServer
              ? {
                  ...server,
                  connected: cachedServer.connected,
                  latencyMs: cachedServer.latencyMs,
                  lastTestAt: cachedServer.lastTestAt,
                }
              : server;
          }),
        );
      } else {
        setServers(fetched);
      }
      hydrated.current = true;
      setLoading(false);
    });
  }, []);

  // UI 状态（连接/延迟/测试时间）始终保存到 localStorage
  useEffect(() => {
    if (hydrated.current) persistUICache(servers);
  }, [servers]);

  // 轮询后端常驻连接池状态：后台保活实测的延迟会实时回填到对应服务器
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const status = await fetchSshStatus();
      if (!alive || !status || !status.connected || !status.server) return;
      if (status.latencyMs != null) {
        setServers((prev) =>
          prev.map((s) =>
            s.id === status.server ? { ...s, latencyMs: status.latencyMs } : s,
          ),
        );
      }
    };
    void poll();
    const timer = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const activeServer = useMemo(
    () => servers.find((s) => s.connected) ?? null,
    [servers],
  );

  const addServer = useCallback(
    (cfg: ServerConfig) => {
      const next = [...servers, cfg];
      setServers(next);
      void syncServerConfigs(next);
    },
    [servers],
  );

  const updateServer = useCallback(
    (id: string, patch: Partial<ServerConfig>, opts?: { sync?: boolean }) => {
      const next = servers.map((s) => (s.id === id ? { ...s, ...patch } : s));
      setServers(next);
      // 默认同步配置到后端；UI 状态更新（如延迟）可传入 { sync: false }
      if (opts?.sync !== false) void syncServerConfigs(next);
    },
    [servers],
  );

  const removeServer = useCallback(
    (id: string) => {
      const next = servers.filter((s) => s.id !== id);
      setServers(next);
      void syncServerConfigs(next);
    },
    [servers],
  );

  const toggleConnection = useCallback((id: string) => {
    setServers((prev) => {
      const target = prev.find((s) => s.id === id);
      const willConnect = !target?.connected;
      return prev.map((s) => ({ ...s, connected: willConnect ? s.id === id : false }));
    });
  }, []);

  const testConnection = useCallback(
    async (id: string): Promise<ConnectionTestResult> => {
      const target = servers.find((s) => s.id === id);
      if (!target) {
        return { ok: false, latencyMs: 0, message: '未找到服务器配置' };
      }
      const result = await testRemoteConnection(target);
      if (result.ok) {
        updateServer(
          id,
          {
            latencyMs: result.latencyMs,
            lastTestAt: formatDateTime(new Date()),
          },
          { sync: false },
        );
      }
      return result;
    },
    [servers, updateServer],
  );

  const value = useMemo<SSHContextValue>(
    () => ({
      servers,
      loading,
      activeServer,
      addServer,
      updateServer,
      removeServer,
      toggleConnection,
      testConnection,
    }),
    [
      servers,
      loading,
      activeServer,
      addServer,
      updateServer,
      removeServer,
      toggleConnection,
      testConnection,
    ],
  );

  return <SSHContext.Provider value={value}>{children}</SSHContext.Provider>;
}
