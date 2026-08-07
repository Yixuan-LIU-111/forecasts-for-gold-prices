/**
 * 前端联调回归测试（jsdom 无头 DOM + 真实后端）
 *
 * 覆盖 docs/前端页面优化.docx 的 6 条建议落地效果：
 *   S1 页面无 F 编号
 *   S2 无失实表述（yfinance / GPT-4o-mini / PostgreSQL 等）
 *   S3 新闻标题为可点击外链
 *   S4 回测参数生效（阈值改变 → 交易笔数变化）+ 参数非法时展示错误
 *   S5 数据源配置由后端 data_sources 驱动
 *   S6 模型配置由后端 model_info 驱动
 *
 * 前置：后端已运行于 http://127.0.0.1:8000
 * 执行：node scripts/frontend_integration_test.mjs
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

function check(name, ok, detail = '') {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`);
  if (!ok) failures.push(name + (detail ? ' :: ' + detail : ''));
}

async function show(view, ms = 1600) { window.eval(`showView('${view}')`); await wait(ms); }

await wait(2500); // 首屏自动加载

console.log('\n=== S1 页面无功能点编号 ===');
{
  const body = doc.body.textContent;
  const m = body.match(/\bF\d{2}\b/g);
  check('页面正文无 F 编号', !m, m ? m.join(',') : '');
}

console.log('\n=== 首屏渲染 ===');
check('信号卡片有内容', !/加载信号中|加载失败/.test(txt('signalBox')), txt('signalBox').slice(0, 60));
check('因子面板有内容', !/加载因子中|加载失败/.test(txt('factorBox')), txt('factorBox').slice(0, 60));
check('新闻流有内容', !/加载新闻中|加载失败/.test(txt('newsFeed')), txt('newsFeed').slice(0, 60));

console.log('\n=== S3 新闻标题可点击 ===');
{
  const links = doc.querySelectorAll('#newsFeed a.news-link');
  const first = links[0];
  check('仪表盘新闻标题为链接', links.length > 0, `${links.length} 条`);
  check('新闻标题展示中文概括（title_zh）',
    !!first && /[\u4e00-\u9fff]/.test(first.textContent),
    first ? first.textContent.slice(0, 40) : '无文本');
  check('链接为真实外链且带 noopener',
    !!first && /^https?:\/\//.test(first.getAttribute('href')) &&
    !/example\.com/.test(first.getAttribute('href')) &&
    first.getAttribute('rel') === 'noopener noreferrer' &&
    first.getAttribute('target') === '_blank',
    first ? first.getAttribute('href') : '无链接');
}

await show('news');
console.log('\n=== S2/S3 新闻中心 ===');
{
  const tblLinks = doc.querySelectorAll('#newsTableBox a.news-link');
  check('新闻表格标题为链接', tblLinks.length > 0, `${tblLinks.length} 条`);
  const stat = txt('newsStatBox');
  check('采集状态由后端驱动（含 SQLite）', /SQLite/.test(stat), stat.slice(0, 90));
  check('采集状态不再硬编码 PostgreSQL', !/PostgreSQL/.test(stat));
}

await show('settings');
console.log('\n=== S5 数据源配置 ===');
{
  const rows = doc.querySelectorAll('#dsBox tbody tr');
  const dsText = txt('dsBox');
  check('数据源表格有行', rows.length >= 5, `${rows.length} 行`);
  check('包含 VIX / CBOE', /VIX/.test(dsText) && /CBOE/.test(dsText));
  check('包含 FRED DFII10', /FRED/.test(dsText) && /DFII10/.test(dsText));
  check('不再出现 yfinance', !/yfinance/i.test(doc.body.textContent));
}

console.log('\n=== S6 模型配置 ===');
{
  const mText = txt('modelBox');
  check('模型配置由后端渲染', mText.length > 10 && !/加载模型配置中/.test(mText), mText.slice(0, 80));
  check('展示真实运行状态', /演示|真实|不可用/.test(mText));
  check('不再出现 GPT-4o-mini', !/GPT-4o/i.test(doc.body.textContent));
  const sigText = txt('sigParamBox');
  check('信号参数由后端阈值渲染', /后端/.test(sigText), sigText.slice(0, 70));
}

console.log('\n=== S2 系统监控数据库类型 ===');
{
  const sys = txt('sysBox');
  check('数据库显示 SQLite', /SQLite/.test(sys), sys.slice(-60));
  check('无 PostgreSQL 16 硬编码', !/PostgreSQL 16/.test(doc.body.textContent));
}

await show('backtest');
console.log('\n=== S4 回测参数生效 ===');
{
  const run = doc.getElementById('runBt');
  const setV = (id, v) => { doc.getElementById(id).value = String(v); };

  setV('btThreshold', 0.55);
  run.dispatchEvent(new window.Event('click'));
  await wait(2500);
  const hint1 = txt('btHint');
  const sum1 = txt('btSummaryBox');
  const t1 = (hint1.match(/共\s*(\d+)\s*笔/) || [])[1];

  setV('btThreshold', 0.85);
  run.dispatchEvent(new window.Event('click'));
  await wait(2500);
  const hint2 = txt('btHint');
  const t2 = (hint2.match(/共\s*(\d+)\s*笔/) || [])[1];

  check('运行回测有反馈', /已完成/.test(hint1), hint1.slice(0, 80));
  check('绩效指标已渲染', /累计收益率/.test(sum1), sum1.slice(0, 70));
  check('展示数据模式标签', /真实行情|演示数据/.test(sum1));
  check('阈值改变导致交易数变化', t1 !== undefined && t2 !== undefined && t1 !== t2, `0.55→${t1} 笔, 0.85→${t2} 笔`);

  // 非法参数 → 后端 422 → 前端提示
  setV('btThreshold', 0.55);
  setV('btCapital', -100);
  run.dispatchEvent(new window.Event('click'));
  await wait(2000);
  const hint3 = txt('btHint');
  check('非法参数展示后端校验信息', /失败|必须大于/.test(hint3), hint3.slice(0, 80));
  setV('btCapital', 10000);
}

await show('stats');
console.log('\n=== 准确率统计 ===');
{
  const bench = txt('benchBox');
  const dir = txt('dirFeed');
  check('基准对比已渲染', !/加载中|加载失败/.test(bench), bench.slice(0, 70));
  check('展示样本量', /样本\s*\d+\s*笔|暂无交易样本/.test(bench), bench.slice(0, 80));
  check('方向准确率带样本量', /样本\s*\d+\s*笔|暂无样本/.test(dir), dir.slice(0, 80));
}

console.log('\n==== JS 运行时错误：' + errors.length + ' ====');
errors.slice(0, 20).forEach(e => console.log(' -', String(e).slice(0, 300)));
console.log('==== 断言失败：' + failures.length + ' ====');
failures.forEach(f => console.log(' -', f));
process.exit(errors.length === 0 && failures.length === 0 ? 0 : 1);
