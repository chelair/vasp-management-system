// PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/browser/report-ai-notes.cjs
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

(async () => {
  const bundle = await build({ stdin: { contents: `
    import React, {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {ReportAIProvider, ReportAIControls} from './src/components/reports/ReportAIContext';
    import ReportNotePanel from './src/components/reports/ReportNotePanel';
    const params=new URLSearchParams(location.search);
    const initial={manual:{analysis_note:'人工原文',paper_note:'',source:'manual',revision:'manual-rev'}};
    function Harness(){
      const [notes,setNotes]=useState(initial);const [connection,setConnection]=useState('');
      const [auto,setAuto]=useState(params.has('auto'));
      return <ReportAIProvider reportId="fixture" notes={notes} onSaved={setNotes}
        connectionId={connection} onConnectionChange={setConnection} autoGenerate={auto} onAutoStarted={()=>setAuto(false)}>
        <ReportAIControls/>
        {['manual','missing','broken'].map(key=><section id={key} key={key}>
          <ReportNotePanel reportId="fixture" noteKey={key} title={key}
            analysis={notes[key]?.analysis_note||''} paper={notes[key]?.paper_note||''} onSaved={setNotes}/>
        </section>)}
        <button onClick={()=>setNotes(old=>({...old,manual:{...old.manual,analysis_note:'外部新人工文本'}}))}>外部更新</button>
      </ReportAIProvider>;
    }
    createRoot(document.getElementById('root')).render(<Harness/>);
  `, loader: 'tsx', resolveDir: path.resolve('.') }, bundle: true, write: false, format: 'iife', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"' } });
  const fullBundle = await build({ stdin: { contents: `
    import React from 'react';import {createRoot} from 'react-dom/client';
    import {App} from 'antd';import {MemoryRouter} from 'react-router-dom';
    import Report from './src/pages/Report';
    createRoot(document.getElementById('root')).render(<MemoryRouter><App><Report/></App></MemoryRouter>);
  `, loader: 'tsx', resolveDir: path.resolve('.') }, bundle: true, write: false, format: 'iife', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"' } });
  let regenerated = false;
  const meta = (id = 'fixture') => ({ report_id: id, project_id: id, project_name: id,
    generated_at: regenerated ? '2026-10-19T13:00:00' : '2026-10-19T12:00:00', time_window: {}, schema_version: '1.2.0',
    project_status: 'normal', summary: id, risk_summary: {}, completion_percent: 100, chart_count: 0 });
  let notes, generateCalls, saves, delay, off, noModels, disconnected;
  const reset = () => {
    notes = { manual: { analysis_note: '人工原文', paper_note: '', source: 'manual', revision: 'manual-rev' } };
    generateCalls = []; saves = []; delay = 0; off = false; noModels = false; disconnected = false;
  };
  reset();
  const server = http.createServer(async (req, res) => {
    if (!req.url.startsWith('/api/')) {
      res.setHeader('Content-Type', req.url.endsWith('.js') ? 'text/javascript' : 'text/html');
      return res.end(req.url === '/app.js' ? bundle.outputFiles[0].text : req.url === '/full.js' ? fullBundle.outputFiles[0].text :
        `<div id="root"></div><script src="${req.url.startsWith('/full') ? '/full.js' : '/app.js'}"></script>`);
    }
    const send = (data, status = 200, message = '') => {
      res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ success: status === 200, data, message }));
    };
    if (req.url === '/api/projects') return send({ projects: ['fixture', 'fixtureOff'].map(id => ({ id, name: id, tasks: [], deadline: '2026-12-01', progress: 100 })) });
    if (req.url === '/api/reports/project/list') return send({ reports: [meta(), meta('fixtureOff')] });
    if (/^\/api\/reports\/project\/(fixture|fixtureOff)$/.test(req.url)) {
      const id = req.url.split('/').pop();
      const sections = [{ key: 'science', title: '重点科学结果分析', markdown: `### 结构优化\n#### Model\n实际能量 ${regenerated ? '-9.0' : '-10.0'} eV` }];
      return send({ meta: meta(id), markdown_sections: sections, sections, dialogs: [], notes,
        note_blocks: {}, edits: { hidden_elements: [] }, structured: { science: { opt: [{ task_id: 'manual', task_name: 'Model', converged: false }] } } });
    }
    if (req.url === '/api/reports/project/generate') { regenerated = true; req.resume(); return send({ reports: [meta()], failed: [] }); }
    if (req.url.endsWith('/ai-status')) return send({ enabled: !off && !req.url.includes('fixtureOff'), empty_revision: 'empty', notes,
      targets: ['manual', 'missing', 'broken'].map(key => ({ key, title: key })) });
    if (req.url.endsWith('/connections')) return send({ items: noModels ? [] : [{ id: 'mine', name: '我的连接', model: 'mock', key_configured: true }] });
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    if (req.url.endsWith('/ai-preview')) {
      generateCalls.push(body.key);
      res.on('close', () => { if (!res.writableEnded) disconnected = true; });
      if (delay) await new Promise(resolve => setTimeout(resolve, delay));
      if (res.destroyed) return;
      if (body.key === 'broken') return send({}, 400, 'Mock 模型 JSON 错误');
      return send({ key: body.key, analysis_note: 'AI 结果 -10.0 eV <script>window.XSS=1</script> [x](javascript:alert)\n![leak](https://example.invalid/leak)',
        paper_note: '**Results**：已计算。\n**Discussion**：需要额外证据。', draft_token: 'mock-receipt',
        base_revision: notes[body.key]?.revision || 'empty', model: 'mock', generated_at: '2026-10-19T12:00:00' });
    }
    if (req.method === 'PUT' && req.url.endsWith('/notes')) {
      saves.push(body);
      notes[body.key] = { analysis_note: body.analysis_note, paper_note: body.paper_note, source: 'manual', revision: 'saved' };
      return send({ notes });
    }
    send({}, 404, 'Unexpected mock request');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage(); const errors = [];
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    const base = 'http://127.0.0.1:' + server.address().port;
    const selectModel = async () => {
      await page.getByRole('combobox', { name: '报告模型连接' }).click();
      await page.getByText('我的连接 · mock', { exact: true }).click();
    };
    await page.goto(base); await selectModel();
    assert.equal(generateCalls.length, 0, 'opening report/choosing connection must not call model');
    await page.locator('#manual').getByRole('button', { name: /编\s*辑/ }).click();
    let dialog = page.locator('dialog[open]');
    await dialog.getByRole('button', { name: 'AI 重新生成', exact: true }).click();
    await dialog.getByText('AI 草稿预览 · 尚未保存').waitFor();
    assert.equal(await dialog.locator('textarea').first().inputValue(), '人工原文', 'preview cannot overwrite editor');
    assert.equal(saves.length, 0, 'generation cannot save automatically');
    assert.equal(await page.evaluate(() => window.XSS), undefined);
    assert.equal(await dialog.locator('script').count(), 0);
    assert.equal(await dialog.locator('img').count(), 0, 'draft cannot automatically load external images');
    assert.equal(await dialog.locator('a[href^="javascript:"]').count(), 0);
    await dialog.getByRole('button', { name: '采用草稿到编辑区' }).click();
    await dialog.getByRole('button', { name: '恢复本次生成前文本' }).click();
    assert.equal(await dialog.locator('textarea').first().inputValue(), '人工原文');
    await dialog.getByRole('button', { name: '采用草稿到编辑区' }).click();
    await dialog.locator('textarea').first().fill('人工修订 AI 文本');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await page.locator('#manual .notes-text').getByText('人工修订 AI 文本', { exact: true }).waitFor();
    assert.equal(saves[0].draft_token, 'mock-receipt');
    assert.equal(saves[0].analysis_note, '人工修订 AI 文本');

    generateCalls = []; saves = [];
    await page.getByRole('button', { name: '生成缺失注解', exact: true }).click();
    await page.getByText('Mock 模型 JSON 错误', { exact: true }).waitFor();
    assert.deepEqual(generateCalls, ['missing', 'broken'], 'batch skips all existing human notes and isolates partial failure');
    assert.equal(saves.length, 0);
    await page.getByRole('button', { name: '预览与编辑', exact: true }).click();
    dialog = page.locator('dialog[open]');
    await dialog.getByText('AI 草稿预览 · 尚未保存').waitFor();
    await dialog.getByRole('button', { name: '放弃草稿', exact: true }).click();
    await dialog.getByRole('button', { name: '取消', exact: true }).click();

    delay = 450;
    await page.locator('#manual').getByRole('button', { name: /编\s*辑/ }).click();
    dialog = page.locator('dialog[open]');
    await dialog.getByRole('button', { name: 'AI 重新生成', exact: true }).click();
    await dialog.locator('textarea').first().fill('模型等待期间的人工编辑');
    await dialog.getByText('AI 草稿预览 · 尚未保存').waitFor();
    assert.equal(await dialog.locator('textarea').first().inputValue(), '模型等待期间的人工编辑', 'late result cannot overwrite typing');
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    delay = 1500;
    await page.locator('#manual').getByRole('button', { name: /编\s*辑/ }).click();
    dialog = page.locator('dialog[open]');
    await dialog.getByRole('button', { name: 'AI 重新生成', exact: true }).click();
    await dialog.getByRole('button', { name: '取消生成', exact: true }).click();
    await dialog.getByRole('button', { name: '取消生成', exact: true }).waitFor({ state: 'hidden' });
    assert.equal(saves.length, 0, 'cancellation cannot persist a partial note');
    await dialog.getByRole('button', { name: '取消', exact: true }).click();

    reset(); off = true;
    await page.goto(base); await page.getByText('AI 撰写未开启', { exact: false }).waitFor();
    await page.locator('#manual').getByRole('button', { name: /编\s*辑/ }).click();
    dialog = page.locator('dialog[open]');
    assert.equal(await dialog.getByRole('button', { name: 'AI 重新生成', exact: true }).isDisabled(), true);
    await dialog.locator('textarea').first().fill('关闭 AI 后人工编辑');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    assert.equal(generateCalls.length, 0); assert.equal(saves[0].analysis_note, '关闭 AI 后人工编辑');

    reset(); noModels = true;
    await page.goto(base); await page.getByText('未配置模型，请先到 AI 工作台添加自己的连接。').waitFor();
    assert.equal(generateCalls.length, 0);
    reset();
    await page.goto(base + '?auto=1'); await selectModel();
    await page.getByText('Mock 模型 JSON 错误', { exact: true }).waitFor();
    assert.deepEqual(generateCalls, ['missing', 'broken'], 'fresh report auto drafting waits for explicit connection choice');
    assert.equal(saves.length, 0);

    reset();
    await page.goto(base + '/full');
    await page.locator('.report-note-anchor .notes-text').getByText('人工原文', { exact: true }).waitFor();
    await selectModel();
    await page.getByRole('button', { name: /生成报告$/ }).click();
    await page.getByText('Mock 模型 JSON 错误', { exact: true }).waitFor();
    await page.getByRole('button', { name: '返回报告', exact: true }).click();
    await page.locator('.report-markdown').getByText('实际能量 -9.0 eV', { exact: true }).waitFor();
    await page.locator('.report-note-anchor .notes-text').getByText('人工原文', { exact: true }).waitFor();
    await page.locator('.report-item').filter({ hasText: 'fixtureOff' }).click();
    await page.getByText('AI 撰写未开启', { exact: false }).waitFor();
    await page.locator('.report-item').filter({ hasText: 'fixture' }).filter({ hasNotText: 'fixtureOff' }).click();
    await page.locator('.report-note-anchor .notes-text').getByText('人工原文', { exact: true }).waitFor();

    const html = execFileSync('.venv/bin/python', ['-c', `
import os,sys,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='vasp-r1-pdf-') as data:
    os.environ['VASP_WEB_DATA_DIR']=data
    os.environ['VASP_AI_KEY_FILE']=str(Path(data)/'ai.key')
    sys.path[:0]=['backend','tests']
    from test_report_ai_notes import report
    from report_export import render_html
    doc=report()
    doc['note_blocks']={'Model':[{'analysis_note':'实际能量 -10.0 eV','paper_note':'Results：事实；Discussion：需证据。'}]}
    print(render_html(doc,doc['markdown_sections']))
`], { encoding: 'utf8' });
    const printPage = await browser.newPage();
    await printPage.setContent(html);
    await printPage.getByText('Results：事实；Discussion：需证据。').waitFor({ state: 'attached' });
    const pdf = await printPage.pdf({ format: 'A4' });
    assert.equal(pdf.subarray(0, 5).toString(), '%PDF-');
    assert.ok(pdf.length > 1000);
    await printPage.close();
    assert.deepEqual(errors, []);
    console.log('PASS R1 preview/adopt/edit/restore/save/discard, partial batch, manual priority, cancel, switch off, no model, auto draft, XSS, full report regenerate/switch, HTML/PDF');
  } finally {
    await browser.close(); await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
