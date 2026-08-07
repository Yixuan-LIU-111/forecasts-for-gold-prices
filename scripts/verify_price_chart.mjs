/**
 * 仪表盘实时行情图（priceChart）渲染验证（jsdom 无头 DOM，无需后端）
 *
 * 验证三项优化：
 *  1) 横轴时间标签不被截断/遮挡：type=date + tickformat=%H:%M + automargin + 倾斜标签
 *  2) 横轴随实时数据动态更新：使用真实数值时间戳（可随更新自动扩展范围、滚动）
 *  3) 纵坐标统一保留 1 位小数：yaxis.tickformat = '.1f'
 *
 * 执行：node scripts/verify_price_chart.mjs
 */
import { JSDOM, VirtualConsole } from '/Users/echo/.workbuddy/binaries/node/workspace/node_modules/jsdom/lib/api.js';
import { readFileSync } from 'node:fs';

const html = readFileSync('frontend/dashboard.html', 'utf-8');
const errors = [], failures = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.detail?.stack || e.message || e)));

const plots = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'file:///dashboard.html',
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(window) {
    window.Plotly = {
      newPlot: (id, data, layout) => { plots.push({ id, data, layout }); return Promise.resolve(); },
      react: () => Promise.resolve(),
      purge: () => {},
    };
    window.fetch = async (url) => {
      const u = String(url);
      const json = (data) => ({ ok: true, status: 200, json: async () => ({ code: 200, message: 'success', data }) });
      if (u.includes('/market/price')) {
        const now = Date.now();
        const prices = Array.from({ length: 49 }, (_, i) => {
          const t = new Date(now - (48 - i) * 5 * 60 * 1000); // 5 分钟一根，跨约 4 小时
          const iso = t.toISOString().slice(0, 19);            // 形如 2026-08-05T14:23:00
          return { time: iso, price: 2300 + Math.sin(i / 5) * 5 + i * 0.3 };
        });
        const last = prices[prices.length - 1];
        return json({ current_price: last.price, change: 1.2, change_pct: 0.05, timestamp: last.time, prices });
      }
      if (u.includes('/signals/latest')) return json({ direction: '看多', direction_en: 'bullish', probability: 0.6, strength: 60, position: '中仓', position_pct: 50, bull_bear_score: 62, confidence: '中', attribution: [] });
      if (u.includes('/factors')) return json({ factors: [{ name: 'DXY', value: 103.2, change: -0.1, change_pct: -0.1, trend_color: 'green' }, { name: 'VIX', value: 14.5, change: 0.2, trend_color: 'red' }, { name: 'TIPS', value: 1.8, change: 0.01, trend_color: 'green' }, { name: 'hawk_dove', value: 0.1, change: 0.1 }, { name: 'sentiment', value: 0.2, change: 0.1 }] });
      if (u.includes('/news')) return json([{ title: 't', url: 'https://reuters.com/markets', sentiment: 'bullish', sentiment_score: 0.5, topic: 'Fed', key_sentence: 'x', sentiment_label: '利多' }]);
      if (u.includes('/stats/accuracy')) return json({ overall_7d: 55, overall_30d: 57, bullish_accuracy: 60, bearish_accuracy: 50, neutral_accuracy: 0, data_mode: 'real', sample_7d: 10, sample_30d: 20, sample_bullish: 5, sample_bearish: 4 });
      if (u.includes('/backtest/results')) return json({ summary: { total_return_pct: 5.2, benchmark_return_pct: 3.1, max_drawdown_pct: -10, win_rate: 55, data_mode: 'real' }, equity_curve: [{ time: '2026-08-05T10:00:00', strategy: 100, benchmark: 100 }], trade_details: [] });
      return json({});
    };
    window.alert = m => errors.push('alert: ' + m);
    window.onerror = (msg, src, line, col, err) => errors.push('onerror: ' + msg + ' @' + line + ':' + col + (err ? ' ' + (err.stack || err) : ''));
    window.addEventListener('unhandledrejection', e => errors.push('unhandledrejection: ' + (e.reason?.stack || e.reason)));
  },
});

const { window } = dom;
const wait = ms => new Promise(r => setTimeout(r, ms));
const check = (n, ok, d = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' :: ' + d : ''}`);
  if (!ok) failures.push(n + (d ? ' :: ' + d : ''));
};

await wait(2500); // 等待首屏 loadDashboard 完成

console.log('\n=== 仪表盘实时行情图渲染验证 ===');
const price = plots.find(p => p.id === 'priceChart');
check('priceChart 已渲染', !!price);
if (price) {
  const x = price.layout.xaxis || {};
  const y = price.layout.yaxis || {};
  check('横轴为真实时间轴 (type=date)', x.type === 'date', 'type=' + x.type);
  check('横轴时间格式为 %H:%M', x.tickformat === '%H:%M', x.tickformat);
  check('横轴自动留白避免截断 (automargin)', x.automargin === true, 'automargin=' + x.automargin);
  check('横轴标签倾斜避免遮挡 (tickangle)', typeof x.tickangle === 'number' && x.tickangle !== 0, 'tickangle=' + x.tickangle);
  check('纵轴保留 1 位小数 (.1f)', y.tickformat === '.1f', y.tickformat);
  const xs = price.data[0].x;
  check('横轴为数值时间戳(可随实时数据滚动)', xs.length > 0 && typeof xs[0] === 'number', 'x0=' + xs[0]);
  let mono = true;
  for (let i = 1; i < xs.length; i++) if (xs[i] <= xs[i - 1]) mono = false;
  check('时间戳单调递增(动态更新前提)', mono);
}

check('无 JS 运行时错误', errors.length === 0, errors.join(' | ').slice(0, 300));

const okAll = failures.length === 0 && errors.length === 0;
console.log('\n结果: ' + (okAll ? 'ALL PASS ✅' : 'HAS FAILURES ❌'));
if (failures.length) console.log('失败项: ' + failures.join('; '));
process.exit(okAll ? 0 : 1);
