import type { ServerConfig } from '../../types';

/**
 * 默认 SSH 服务器配置（对齐现有后端 config/servers.json）。
 * 用户在前端新增/修改后保存在浏览器 localStorage，
 * 正式版将由后端统一读写网站同级 data/config/servers.json。
 */
export const mockServerConfigs: ServerConfig[] = [
  {
    id: 'server1',
    name: 'server1',
    host: 'hpc.xmu.edu.cn',
    port: 22,
    user: 'mdye',
    authType: 'key',
    keyPath: '~/.ssh/id_rsa',
    home: '/data/gpfs03/mdye',
    queueSystem: 'lsf',
    remoteBase: '/data/gpfs03/mdye/projects/test',
    connected: true,
    latencyMs: 96,
    lastTestAt: '2026-08-24 12:00',
  },
  {
    id: 'server2',
    name: 'server2',
    host: '192.168.1.150',
    port: 22,
    user: 'vasp',
    authType: 'password',
    password: 'demo-password',
    home: '/home/vasp',
    queueSystem: 'slurm',
    remoteBase: '/home/vasp/projects',
    connected: false,
    latencyMs: null,
    lastTestAt: null,
  },
];
