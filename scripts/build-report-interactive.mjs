/**
 * 报告交互版运行时打包（2026-10-15，v0.9.62）。
 *
 * 把 `src/interactive/reportRuntime.ts`（含 ECharts 按需注册 + PDOS / 功函数原生组件）
 * 打成一个 IIFE，输出到 `dist/report/report-interactive.js`。
 * 后端导出单文件 HTML 时把这个文件**整段内联**（`backend/report_interactive.py`）；
 * 文件不存在时导出自动降级为纯静态版（只出 SVG），不影响主流程。
 *
 * 用 esbuild（vite 自带依赖）而不是 vite 的 library 模式：产物要的是"一段能直接塞进
 * <script> 的代码"，不需要 ESM 包装、不需要 hash 文件名，越简单越稳。
 */

import { mkdirSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as esbuild from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const outfile = resolve(root, 'dist/report/report-interactive.js');

mkdirSync(dirname(outfile), { recursive: true });

await esbuild.build({
  entryPoints: [resolve(root, 'src/interactive/reportRuntime.ts')],
  bundle: true,
  minify: true,
  format: 'iife',
  target: ['es2019'],
  platform: 'browser',
  outfile,
  logLevel: 'error',
});

const size = statSync(outfile).size;
console.log(
  `[report-interactive] ${outfile} · ${(size / 1024).toFixed(0)} KB（导出 HTML 时内联）`,
);
