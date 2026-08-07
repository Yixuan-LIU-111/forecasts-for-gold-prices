"""前端页面优化补丁 S3~S6：新闻标题可跳转、回测参数生效、数据源/模型配置改为后端驱动。

对应 docs/前端页面优化.docx 建议 3、4、5、6。
执行：python scripts/patch_frontend_s3_s6.py
"""
from pathlib import Path
import sys

HTML = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.html"

# ---------------- S3：仪表盘新闻流标题可点击 ----------------
OLD_FEED = """      '<div class="body"><div class="t">'+escapeHtml(n.title)+'</div>'+"""
NEW_FEED = """      '<div class="body"><div class="t">'+newsLink(n)+'</div>'+"""

# ---------------- S3：新闻中心表格标题可点击 ----------------
OLD_TABLE = """          return '<tr><td>'+escapeHtml(n.title)+'</td><td>'+escapeHtml(n.source||'')+'</td><td>'+escapeHtml(n.topic||'')+'</td>'+"""
NEW_TABLE = """          return '<tr><td>'+newsLink(n)+'</td><td>'+escapeHtml(n.source||'')+'</td><td>'+escapeHtml(n.topic||'')+'</td>'+"""

# ---------------- S2：新闻中心采集状态改为后端驱动 ----------------
OLD_NEWS_HEAD = """async function loadNews(){
  const [newsR, hawkR] = await Promise.allSettled([
    api('/api/v1/news?limit=50'),
    api('/api/v1/hawk-dove/events?days=30'),
  ]);
  // 采集状态
  const sb = document.getElementById('newsStatBox');
  const n = (newsR.status==='fulfilled' && newsR.value) ? newsR.value.length : 0;
  sb.innerHTML =
    '<div class="tile"><h4>数据源</h4><div class="metric" style="font-size:22px">NewsAPI</div><div class="sub">GNews 备选 · 100 请求/天</div></div>' +
    '<div class="tile"><h4>采集频率</h4><div class="metric" style="font-size:22px">每分钟</div><div class="sub">轮询 + 合并请求</div></div>' +
    '<div class="tile"><h4>今日采集</h4><div class="metric">'+n+'</div><div class="sub">去重率 11.3%</div></div>' +
    '<div class="tile"><h4>存储</h4><div class="metric" style="font-size:22px">news 表</div><div class="sub">PostgreSQL · URL 去重</div></div>';"""

NEW_NEWS_HEAD = """async function loadNews(){
  const [newsR, hawkR, dsR, sysR] = await Promise.allSettled([
    api('/api/v1/news?limit=50'),
    api('/api/v1/hawk-dove/events?days=30'),
    api('/api/v1/system/data-sources'),
    api('/api/v1/system/status'),
  ]);
  // 采集状态：数据源与存储信息取自后端，不再硬编码
  const sb = document.getElementById('newsStatBox');
  const n = (newsR.status==='fulfilled' && newsR.value) ? newsR.value.length : 0;
  const dsList = (dsR.status==='fulfilled' && dsR.value) ? dsR.value : [];
  const newsDs = dsList.find(x=>x.indicator_code==='news') || {};
  const sentDs = dsList.find(x=>x.indicator_code==='sentiment') || {};
  const sys = (sysR.status==='fulfilled' && sysR.value) ? sysR.value : {};
  sb.innerHTML =
    '<div class="tile"><h4>新闻数据源</h4><div class="metric" style="font-size:20px">'+escapeHtml(newsDs.source_name||'--')+'</div><div class="sub">'+escapeHtml(newsDs.description||'')+'</div></div>' +
    '<div class="tile"><h4>采集频率</h4><div class="metric" style="font-size:20px">'+escapeHtml(newsDs.update_frequency||'--')+'</div><div class="sub">'+(newsDs.realtime?'实时轮询':'定时批量')+'</div></div>' +
    '<div class="tile"><h4>当前样本量</h4><div class="metric">'+n+'</div><div class="sub">news 表 · URL 去重</div></div>' +
    '<div class="tile"><h4>情感分析</h4><div class="metric" style="font-size:20px">'+escapeHtml(sentDs.source_name||'--')+'</div><div class="sub">存储 '+escapeHtml(sys.db_type||'--')+'</div></div>';"""

# ---------------- S4：回测运行按钮直接使用 POST 返回 ----------------
OLD_BT = """function bindBacktest(){
  const run = document.getElementById('runBt');
  const exp = document.getElementById('exportBt');
  if(run && !run._bound){ run._bound=true; run.addEventListener('click', async ()=>{
    run.disabled=true; run.textContent='回测中…';
    try{
      const body = {
        initial_capital: parseFloat((document.getElementById('btCapital').value||'100000').replace(/,/g,'')),
        spread: parseFloat(document.getElementById('btSpread').value||'0.3'),
        commission_pct: parseFloat((document.getElementById('btCommission').value||'0.01').replace('%','')),
      };
      await api('/api/v1/backtest/run', {method:'POST', body:JSON.stringify(body)});
      const res = await apiSafe('/api/v1/backtest/results', loadBacktest);
      renderBacktest(res);
    }catch(e){ alert('回测失败：' + (e.message||e)); }
    finally{ run.disabled=false; run.textContent='运行回测'; }
  }); }
  if(exp && !exp._bound){ exp._bound=true; exp.addEventListener('click', ()=>{
    window.open(API_BASE + '/docs', '_blank'); // 文档入口；后端暂无导出端点
  }); }
}"""

NEW_BT = """function num(id, dflt){
  const el = document.getElementById(id);
  const raw = String((el && el.value) || '').replace(/[,%\\s]/g,'');
  const v = parseFloat(raw);
  return isFinite(v) ? v : dflt;
}
function readBacktestParams(){
  const range = (document.getElementById('btRange')||{}).value || '3m';
  const months = range==='1m' ? 1 : (range==='6m' ? 6 : 3);
  const end = new Date();
  const start = new Date(end.getTime());
  start.setMonth(start.getMonth() - months);
  const iso = d => d.toISOString().slice(0,10);
  return {
    start_date: iso(start),
    end_date: iso(end),
    initial_capital: num('btCapital', 10000),
    spread: num('btSpread', 0.3),
    commission_pct: num('btCommission', 0.01),
    signal_threshold: num('btThreshold', 0.55),
  };
}
function bindBacktest(){
  const run = document.getElementById('runBt');
  const exp = document.getElementById('exportBt');
  const hint = document.getElementById('btHint');
  if(run && !run._bound){ run._bound=true; run.addEventListener('click', async ()=>{
    run.disabled=true; run.textContent='回测中…';
    if(hint){ hint.textContent='正在按当前参数重新计算…'; hint.className='muted'; }
    try{
      const body = readBacktestParams();
      // 直接使用 POST 返回的结果，避免再次拉取历史快照导致「参数无响应」
      const bt = await api('/api/v1/backtest/run', {method:'POST', body:JSON.stringify(body)});
      renderBacktest({ok:true, d:bt});
      if(hint){
        const s = (bt && bt.summary) || {};
        hint.textContent = '已完成：共 '+(s.total_trades!=null?s.total_trades:0)+' 笔交易 · 阈值 '+body.signal_threshold+
          ' · 点差 '+body.spread+' · 手续费 '+body.commission_pct+'%';
      }
    }catch(e){
      const msg = (e && e.message) ? e.message : String(e);
      if(hint){ hint.textContent = '回测失败：' + msg; hint.className='muted c-bear'; }
    }
    finally{ run.disabled=false; run.textContent='运行回测'; }
  }); }
  if(exp && !exp._bound){ exp._bound=true; exp.addEventListener('click', ()=>{
    window.open(API_BASE + '/docs', '_blank'); // 文档入口；后端暂无导出端点
  }); }
}"""

# ---------------- S4：绩效指标按符号着色 + 展示数据模式 ----------------
OLD_SUM = """  sumBox.innerHTML =
    '<div class="tile"><h4>累计收益率</h4><div class="metric c-bull">'+fmt(s.total_return_pct)+'%</div><div class="sub">vs 买入持有 '+fmt(s.benchmark_return_pct!=null?s.benchmark_return_pct:'+4.1')+'%</div></div>' +
    '<div class="tile"><h4>夏普比率</h4><div class="metric">'+fmt(s.sharpe_ratio)+'</div><div class="sub">风险调整后收益</div></div>' +
    '<div class="tile"><h4>最大回撤</h4><div class="metric c-bear">'+fmt(s.max_drawdown_pct)+'%</div><div class="sub">区间最大亏损</div></div>' +
    '<div class="tile"><h4>胜率 / 盈亏比</h4><div class="metric">'+fmt(s.win_rate,0)+'<span class="u">/'+fmt(s.profit_loss_ratio)+'</span></div><div class="sub">盈利交易占比</div></div>';"""

NEW_SUM = """  const retCls = (s.total_return_pct||0) >= 0 ? 'c-bull' : 'c-bear';   // 国内习惯：红涨绿跌
  const modeTag = s.data_mode==='real' ? '真实行情' : '演示数据';
  sumBox.innerHTML =
    '<div class="tile"><h4>累计收益率 <span class="tag">'+modeTag+'</span></h4><div class="metric '+retCls+'">'+fmt(s.total_return_pct)+'%</div><div class="sub">vs 买入持有 '+(s.benchmark_return_pct!=null?fmt(s.benchmark_return_pct)+'%':'--')+'</div></div>' +
    '<div class="tile"><h4>夏普比率</h4><div class="metric">'+fmt(s.sharpe_ratio)+'</div><div class="sub">风险调整后收益</div></div>' +
    '<div class="tile"><h4>最大回撤</h4><div class="metric c-bear">'+fmt(s.max_drawdown_pct)+'%</div><div class="sub">区间最大亏损</div></div>' +
    '<div class="tile"><h4>胜率 / 盈亏比</h4><div class="metric">'+fmt(s.win_rate,0)+'<span class="u">/'+fmt(s.profit_loss_ratio)+'</span></div><div class="sub">共 '+(s.total_trades!=null?s.total_trades:0)+' 笔交易</div></div>';"""

# ---------------- S5 + S6：系统设置改为后端驱动 ----------------
OLD_SETTINGS = """async function loadSettings(){
  const [sysR, statR] = await Promise.allSettled([
    api('/api/v1/system/status'),
    api('/api/v1/stats/accuracy?window=30d'),
  ]);
  const box = document.getElementById('sysBox');
  if(sysR.status==='rejected'){ box.innerHTML = stateError(sysR.reason, loadSettings); return; }
  const s = sysR.value || {};
  const acc = (statR.status==='fulfilled' && statR.value) ? statR.value.overall_30d : null;
  const okCls = s.status==='ok' ? 'c-ok' : 'c-bear';
  box.innerHTML =
    '<div class="tile"><h4>数据采集状态</h4><div class="metric '+okCls+'" style="font-size:22px">'+(s.status==='ok'?'正常':'警告')+'</div><div class="sub">'+(s.data_collection||'')+'</div></div>' +
    '<div class="tile"><h4>API 调用量</h4><div class="metric" style="font-size:22px">$'+fmt(s.api_usage? s.api_usage.today:0,1)+'</div><div class="sub">上限 $'+(s.api_usage? s.api_usage.limit:5)+'</div></div>' +
    '<div class="tile"><h4>模型准确率</h4><div class="metric c-bull" style="font-size:22px">'+(acc!=null?fmt(acc)+'%':'--')+'</div><div class="sub">30 天滚动</div></div>' +
    '<div class="tile"><h4>数据库</h4><div class="metric c-ok" style="font-size:22px">'+(s.db_connection==='正常'?'已连接':'异常')+'</div><div class="sub">PostgreSQL 16</div></div>';
}"""

NEW_SETTINGS = """async function loadSettings(){
  const [sysR, statR, dsR] = await Promise.allSettled([
    api('/api/v1/system/status'),
    api('/api/v1/stats/accuracy?window=30d'),
    api('/api/v1/system/data-sources'),
  ]);
  const box = document.getElementById('sysBox');
  renderDataSources(dsR);
  renderModelConfig(sysR);
  renderSignalParams(sysR);
  if(sysR.status==='rejected'){ box.innerHTML = stateError(sysR.reason, loadSettings); return; }
  const s = sysR.value || {};
  const acc = (statR.status==='fulfilled' && statR.value) ? statR.value.overall_30d : null;
  const okCls = s.status==='ok' ? 'c-ok' : 'c-bear';
  box.innerHTML =
    '<div class="tile"><h4>数据采集状态</h4><div class="metric '+okCls+'" style="font-size:22px">'+(s.status==='ok'?'正常':'警告')+'</div><div class="sub">'+escapeHtml(s.data_collection||'')+'</div></div>' +
    '<div class="tile"><h4>API 调用量</h4><div class="metric" style="font-size:22px">$'+fmt(s.api_usage? s.api_usage.today:0,1)+'</div><div class="sub">上限 $'+(s.api_usage? s.api_usage.limit:5)+'</div></div>' +
    '<div class="tile"><h4>模型准确率</h4><div class="metric c-bull" style="font-size:22px">'+(acc!=null?fmt(acc)+'%':'--')+'</div><div class="sub">30 天滚动</div></div>' +
    '<div class="tile"><h4>数据库</h4><div class="metric c-ok" style="font-size:22px">'+(s.db_connection==='正常'?'已连接':'异常')+'</div><div class="sub">'+escapeHtml(s.db_type||'--')+'</div></div>';
}

/* 数据源配置：完全由 /api/v1/system/data-sources 渲染 */
function renderDataSources(dsR){
  const box = document.getElementById('dsBox');
  const note = document.getElementById('dsNote');
  if(!box) return;
  if(dsR.status==='rejected'){ box.innerHTML = stateError(dsR.reason, loadSettings); return; }
  const list = dsR.value || [];
  if(!list.length){ box.innerHTML = stateEmpty('暂无数据源配置'); return; }
  box.innerHTML = '<table><thead><tr><th>指标</th><th>代码</th><th>数据来源</th><th>更新频率</th><th>实时性</th><th>说明</th></tr></thead><tbody>' +
    list.map(d=>{
      const rt = d.realtime ? '<span class="pill bg-bull c-bull">实时</span>' : '<span class="pill bg-neutral c-neutral">非实时</span>';
      const src = d.source_url
        ? '<a href="'+escapeHtml(d.source_url)+'" target="_blank" rel="noopener noreferrer">'+escapeHtml(d.source_name||'')+'</a>'
        : escapeHtml(d.source_name||'');
      return '<tr><td>'+escapeHtml(d.indicator_name||'')+'</td><td><code>'+escapeHtml(d.indicator_code||'')+'</code></td>'+
        '<td>'+src+'</td><td>'+escapeHtml(d.update_frequency||'')+'</td><td>'+rt+'</td>'+
        '<td>'+escapeHtml(d.description||'')+'</td></tr>';
    }).join('') + '</tbody></table>';
  if(note) note.textContent = '共 '+list.length+' 个数据源，清单由后端 data_sources 表维护，页面不再硬编码。';
}

/* 模型配置：由 /api/v1/system/status 的 model_info 渲染真实状态 */
function renderModelConfig(sysR){
  const box = document.getElementById('modelBox');
  if(!box) return;
  if(sysR.status==='rejected'){ box.innerHTML = stateError(sysR.reason, loadSettings); return; }
  const mi = (sysR.value && sysR.value.model_info) || null;
  if(!mi){ box.innerHTML = stateEmpty('后端未返回模型信息'); return; }
  const stMap = {loaded:['已加载真实模型','c-bull'], synthetic_baseline:['合成基线模型（演示）','c-neutral'], unavailable:['模型不可用','c-bear']};
  const st = stMap[mi.status] || [mi.status||'--','c-neutral'];
  const inds = (mi.available_indicators||[]).map(x=>'<span class="pill bg-neutral c-neutral">'+escapeHtml(x)+'</span>').join(' ');
  box.innerHTML =
    '<div class="grid g-4">' +
      '<div class="tile"><h4>模型名称</h4><div class="metric" style="font-size:18px">'+escapeHtml(mi.name||'--')+'</div><div class="sub">推理组合</div></div>' +
      '<div class="tile"><h4>运行状态</h4><div class="metric '+st[1]+'" style="font-size:18px">'+escapeHtml(st[0])+'</div><div class="sub">'+(mi.is_real_model?'使用训练后的真实模型':'尚未接入训练模型')+'</div></div>' +
      '<div class="tile"><h4>演示模式</h4><div class="metric" style="font-size:18px">'+(mi.demo_mode?'开启':'关闭')+'</div><div class="sub">'+(mi.demo_mode?'数据与信号为演示种子':'使用线上真实数据')+'</div></div>' +
      '<div class="tile"><h4>默认信号阈值</h4><div class="metric" style="font-size:18px">'+fmt(mi.signal_threshold)+'</div><div class="sub">回测/信号生成共用</div></div>' +
    '</div>' +
    '<div class="muted" style="margin-top:var(--s3)">输入因子：'+(inds||'--')+'</div>';
}

/* 信号参数：阈值等取自后端 model_info，避免与实际不一致 */
function renderSignalParams(sysR){
  const box = document.getElementById('sigParamBox');
  if(!box) return;
  const mi = (sysR.status==='fulfilled' && sysR.value && sysR.value.model_info) || {};
  const th = (mi.signal_threshold!=null) ? fmt(mi.signal_threshold) : '--';
  box.innerHTML =
    '<div class="field-row">' +
      '<div><label>看涨触发阈值 P ≥</label><input value="'+th+'" disabled></div>' +
      '<div><label>看跌触发阈值 1-P ≥</label><input value="'+th+'" disabled></div>' +
      '<div><label>低于阈值</label><input value="观望（不开仓）" disabled></div>' +
      '<div><label>参数来源</label><input value="后端 /system/status" disabled></div>' +
    '</div>' +
    '<div class="muted" style="margin-top:var(--s3)">阈值由后端统一下发；在「回测分析」中可临时调整阈值查看敏感性，不会写回系统配置。</div>';
}"""

# ---------------- 准确率统计：去掉硬编码 '+' 号 ----------------
OLD_STATS = """    '<div class="tile"><h4>买入持有基准</h4><div class="metric">50.0%</div><div class="sub">随机方向基准</div></div>' +
    '<div class="tile"><h4>超额</h4><div class="metric c-bull">+'+fmt(a.overall_30d-50)+'pct</div><div class="sub">滚动 30 天</div></div>';"""
NEW_STATS = """    '<div class="tile"><h4>随机方向基准</h4><div class="metric">50.0%</div><div class="sub">二分类理论基线</div></div>' +
    '<div class="tile"><h4>超额</h4><div class="metric '+((a.overall_30d-50)>=0?'c-bull':'c-bear')+'">'+((a.overall_30d-50)>=0?'+':'')+fmt(a.overall_30d-50)+'pct</div><div class="sub">滚动 30 天</div></div>';"""

# ---------------- 因子标签：情感均值单位不是 LLM ----------------
OLD_FACTOR = """    tile('VIX','VIX','恐慌') + tile('sentiment','情感均值','LLM');"""
NEW_FACTOR = """    tile('VIX','VIX','恐慌') + tile('sentiment','情感均值','情感');"""

# ---------------- 新增 newsLink 工具函数 ----------------
OLD_HELPER = """function arrow(v) { return v > 0 ? '▲' : (v < 0 ? '▼' : '—'); }"""
NEW_HELPER = """function arrow(v) { return v > 0 ? '▲' : (v < 0 ? '▼' : '—'); }
/* 新闻标题：有原文链接时渲染为可点击外链，否则退化为纯文本 */
function newsLink(n) {
  const title = escapeHtml(n.title || '');
  const url = n && n.url ? String(n.url) : '';
  if (!/^https?:\\/\\//i.test(url)) return title;
  return '<a class="news-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer" title="打开原文">' + title + '</a>';
}"""

# ---------------- 外链样式 ----------------
OLD_CSS_ANCHOR = """  .feed .body .t{font-size:14.5px;font-weight:600;line-height:1.45}"""
NEW_CSS_ANCHOR = """  .feed .body .t{font-size:14.5px;font-weight:600;line-height:1.45}
  .news-link{color:inherit;text-decoration:none;border-bottom:1px solid transparent;transition:color .15s,border-color .15s}
  .news-link:hover{color:var(--gold);border-bottom-color:var(--gold)}
  .news-link::after{content:'↗';font-size:.78em;margin-left:4px;opacity:.55}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;background:var(--bg-2,rgba(0,0,0,.04));padding:1px 5px;border-radius:4px}"""

REPLACEMENTS = [
    (OLD_HELPER, NEW_HELPER, 1),
    (OLD_FEED, NEW_FEED, 1),
    (OLD_TABLE, NEW_TABLE, 1),
    (OLD_NEWS_HEAD, NEW_NEWS_HEAD, 1),
    (OLD_BT, NEW_BT, 1),
    (OLD_SUM, NEW_SUM, 1),
    (OLD_SETTINGS, NEW_SETTINGS, 1),
    (OLD_STATS, NEW_STATS, 1),
    (OLD_FACTOR, NEW_FACTOR, 1),
    (OLD_CSS_ANCHOR, NEW_CSS_ANCHOR, 1),
]


def main() -> int:
    text = HTML.read_text(encoding="utf-8")
    failed = []
    for old, new, expect in REPLACEMENTS:
        cnt = text.count(old)
        if cnt != expect:
            failed.append((old.splitlines()[0][:70], cnt, expect))
            continue
        text = text.replace(old, new, expect)
    if failed:
        print("以下替换未命中预期次数，已中止：")
        for o, c, e in failed:
            print(f"  actual={c} expect={e} :: {o}")
        return 1
    HTML.write_text(text, encoding="utf-8")
    print(f"OK: 应用 {len(REPLACEMENTS)} 处替换 -> {HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
