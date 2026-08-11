/**
 * 演示模式开关 · 前端交互验证（jsdom 无头 DOM + 真实后端）
 *
 * 验证三点：
 *   1) 初始开关状态由后端 demo_mode 驱动（加载即同步）
 *   2) 用户切换关闭 → 后端改为实时模式（scheduler 挂载 collect/signal/news）、UI 回显"关闭"
 *   3) 用户再切换开启 → 后端回到演示模式、UI 回显"开启"
 *
 * 前置：后端运行于 http://127.0.0.1:8000
 * 执行：node scripts/demo_toggle_test.mjs
 */
import { JSDOM, VirtualConsole } from '/Users/echo/.workbuddy/binaries/node/workspace/node_modules/jsdom/lib/api.js';
import { readFileSync } from 'node:fs';

const HTML_PATH = 'frontend/dashboard.html';
const html = readFileSync(HTML_PATH, 'utf-8');

const errors = [];
const failures = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.detail?.stack || e.message || e)));

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'file:///dashboard.html',
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(window) {
    window.Plotly = { newPlot: () => Promise.resolve(), react: () => Promise.resolve(), purge: () => {} };
    window.fetch = globalThis.fetch;
    window.alert = m => errors.push('alert: ' + m);
    window.onerror = (msg, src, line, col, err) =>
      errors.push('onerror: ' + msg + ' @' + line + ':' + col + (err ? ' ' + (err.stack || err) : ''));
    window.addEventListener('unhandledrejection', e =>
      errors.push('unhandledrejection: ' + (e.reason?.stack || e.reason)));
  },
});

const { window } = dom;
const doc = window.document;
const wait = ms => new Promise(r => setTimeout(r, ms));
const txt = id => { const e = doc.getElementById(id); return e ? e.textContent.replace(/\s+/g, ' ').trim() : '<null>'; };
const checked = id => { const e = doc.getElementById(id); return e ? e.checked : null; };

function check(name, ok, detail = '') {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`);
  if (!ok) failures.push(name + (detail ? ' :: ' + detail : ''));
}

async function main() {
  await wait(2800); // 首屏 + 自动 loadDemoMode

  console.log('\n=== 演示模式开关 · 前端交互验证 ===');

  // 1) 顶栏运行模式标识：初始应为"演示模式"
  const initMode = txt('topbarMode');
  check('顶栏初始显示"演示模式"', initMode === '演示模式', 'mode=' + initMode);

  // 2) 进入系统设置，模型配置瓦片内应有开关
  window.eval("showView('settings')");
  await wait(2200);
  const initChecked = checked('demoToggle');
  const initState = txt('demoState');
  check('模型配置·开关初始勾选', initChecked === true, 'checked=' + initChecked);
  check('模型配置·状态显示"开启"', initState === '开启', 'state=' + initState);

  // 3) 模拟用户在模型配置瓦片切换"关闭"
  const tg = doc.getElementById('demoToggle');
  tg.checked = false;
  tg.dispatchEvent(new window.Event('change', { bubbles: true }));
  await wait(1800); // 等待 applyDemoMode 的 POST + refreshActive 完成

  const afterOffState = txt('demoState');
  const afterOffChecked = checked('demoToggle');
  const afterOffMode = txt('topbarMode');
  check('切换关闭后模型配置状态显示"关闭"', afterOffState === '关闭', 'state=' + afterOffState);
  check('切换关闭后开关未勾选', afterOffChecked === false, 'checked=' + afterOffChecked);
  check('切换关闭后顶栏显示"实时模式"', afterOffMode === '实时模式', 'mode=' + afterOffMode);

  // 后端真实状态核验
  const r1 = await globalThis.fetch('http://127.0.0.1:8000/api/v1/system/demo-mode').then(r => r.json());
  check('后端已切到实时模式（enabled=false）', r1.data.enabled === false, 'enabled=' + r1.data.enabled);
  check('实时模式已挂载采集/信号任务',
    ['collect', 'signal', 'news'].every(j => r1.data.scheduler_jobs.includes(j)),
    'jobs=' + JSON.stringify(r1.data.scheduler_jobs));

  // 4) 再切换"开启"
  const tg2 = doc.getElementById('demoToggle');
  tg2.checked = true;
  tg2.dispatchEvent(new window.Event('change', { bubbles: true }));
  await wait(1800);

  const afterOnState = txt('demoState');
  const afterOnChecked = checked('demoToggle');
  const afterOnMode = txt('topbarMode');
  check('切换开启后模型配置状态显示"开启"', afterOnState === '开启', 'state=' + afterOnState);
  check('切换开启后开关已勾选', afterOnChecked === true, 'checked=' + afterOnChecked);
  check('切换开启后顶栏显示"演示模式"', afterOnMode === '演示模式', 'mode=' + afterOnMode);

  const r2 = await globalThis.fetch('http://127.0.0.1:8000/api/v1/system/demo-mode').then(r => r.json());
  check('后端已切回演示模式（enabled=true）', r2.data.enabled === true, 'enabled=' + r2.data.enabled);
  check('演示模式仅保留新闻爬取任务',
    r2.data.scheduler_jobs.length === 1 && r2.data.scheduler_jobs[0] === 'news_scrape',
    'jobs=' + JSON.stringify(r2.data.scheduler_jobs));

  console.log('\n==== JS 运行时错误：' + errors.length + ' ====');
  errors.slice(0, 10).forEach(e => console.log('  ✗ ' + e));
  console.log('==== 断言失败：' + failures.length + ' ====');
  failures.forEach(f => console.log('  ✗ ' + f));

  const ok = errors.length === 0 && failures.length === 0;
  console.log('\n=> ' + (ok ? 'ALL GREEN ✅' : 'HAS ISSUES ❌'));
  process.exit(ok ? 0 : 1);
}

main().catch(e => { console.error('FATAL', e); process.exit(2); });
