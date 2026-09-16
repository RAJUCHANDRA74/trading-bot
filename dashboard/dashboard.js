

/* ════════════════════════════════════════
   CONSTANTS
════════════════════════════════════════ */
const CASH_SYSTEMS = {
  ABCT:    { label: 'ABCT System-1',  stocks: ['RELIANCE','TCS','HDFCBANK','ICICIBANK','SBIN','KOTAKBANK','BAJFINANCE','HDFC','LT','SUNPHARMA'], category: 'CASH' },
  CUP:     { label: 'CUP Strategy',   stocks: ['RELIANCE','HDFCBANK','TCS','BAJFINANCE','HINDUNILVR','TITAN','MARUTI','M&M'], category: 'CASH' },
  TOPBTM:  { label: 'Top Bottom-1',   stocks: ['RELIANCE','TCS','HDFCBANK','ICICIBANK','SBIN','KOTAKBANK','BAJFINANCE','HDFC','LT','SUNPHARMA','AXISBANK','INDUSINDBK'], category: 'CASH' },
  TOPBTM2: { label: 'Top Bottom-2',   stocks: [], category: 'CASH' },
  VALUE:   { label: 'Value Buy',      stocks: ['RELIANCE','TCS','HDFCBANK','SBIN','TATASTEEL','JSWSTEEL','COALINDIA','ONGC','NTPC','POWERGRID'], category: 'CASH' },
  MONSTER: { label: 'Monster Move',   stocks: ['RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK','BAJFINANCE','HINDUNILVR'], category: 'CASH' },
};
const FUTURE_SYSTEMS = {
  IDXFUT:    { label: 'Index Futures',    stocks: ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY'], category: 'FUTURE', type: 'INDEX' },
  COMMOFUT:  { label: 'Commodity Futures', stocks: ['GOLD','SILVER','CRUDEOIL','NATURALGAS'], category: 'FUTURE', type: 'COMMO' },
  TOPBTM:    { label: 'Top Bottom-1',   stocks: [], category: 'FUTURE' },
  TOPBTM2:   { label: 'Top Bottom-2',   stocks: [], category: 'FUTURE' },
};
const FUT_SECTORS = {
  'Auto':              ['MARUTI','M&M','TATAMOTORS','BAJAJ-AUTO','HEROMOTOCO','EICHERMOT','TVSMOTOR','ASHOKLEY','BALKRISIND'],
  'PSU Bank':         ['SBI','BANK OF BARODA','CANBK','UNIONBANK','PNB','CENTRALBK','INDIANB','UCOBANK'],
  'PVT Bank':         ['HDFCBANK','ICICIBANK','KOTAKBANK','INDUSINDBK','AXISBANK','IDFCFIRSTB','BANDHANBNK','RBLBANK'],
  'Consumer Durable':  ['TITAN','HAVELLS','VOLTAS','CROMPTON','WHIRLPOOL','SYMPHONY','KAJARIA'],
  'Energy':           ['RELIANCE','ONGC','BPCL','IOC','HPCL','GAIL'],
  'FMCG':             ['HINDUNILVR','NESTLE','DABUR','COLPAL','BRITANNIA','MARICO','GODREJCP','TATACONSUM'],
  'Financial Services':['BAJFINANCE','BAJ FINSERV','MUTHOOTFIN','CHOLAFIN','SHRIRAMFIN','LICHSGFIN','PFC','RECLTD'],
  'IT':               ['INFY','TCS','HCLTECH','WIPRO','TECHM','LTIM','COFORGE'],
  'Infrastructure':    ['ADANI PORTS','DELHIVERY','CONCOR','CGCL','KALPATPOWR'],
  'Defence':          ['HAL','BEL','BEML','GRSE','MAZAGON','BDL'],
  'Metal':            ['TATASTEEL','JSWSTEEL','HINDALCO','JSPL','NMDC','SAIL','VEDANTA'],
  'Pharma':           ['SUNPHARMA','CIPLA','DRREDDY','APOLLOPHARMA','ZYDUSLIFE','BIOCON','TORNTPHARMA','GLENMARK'],
  'PSE':              ['NTPC','POWERGRID','ONGC','COALINDIA','NMDC','BEL','HAL','GAIL','IOC','BPCL'],
  'Realty':           ['DLF','GODREJPROP','SOBHA','BRIGADE','PRESTIGE','OBEROIRLTY'],
  'Miscellaneous':     ['ADANIENT','ADANIGREEN','ADANIPORTS','ADANITRANS','ADANIPOWER'],
};
const OPTION_SYSTEMS = {
  IDXOPT:   { label: 'Index Options',   stocks: ['NIFTY','BANKNIFTY'], category: 'OPTION' },
  STOCKOPT: { label: 'Stock Options',  stocks: [], category: 'OPTION' },
  COMMOOPT: { label: 'Commodity Options', stocks: [], category: 'OPTION' },
};

/* ════════════════════════════════════════
   PERSISTENT STATE
════════════════════════════════════════ */
let STRAT_STOCKS = {};
function loadStratStocks() {
  try {
    const s = localStorage.getItem('stratStocks');
    if (s) { STRAT_STOCKS = JSON.parse(s); }
    else {
      Object.keys(CASH_SYSTEMS).forEach(k => STRAT_STOCKS[k] = [...(CASH_SYSTEMS[k].stocks||[])]);
      Object.keys(FUTURE_SYSTEMS).forEach(k => STRAT_STOCKS[k] = [...(FUTURE_SYSTEMS[k].stocks||[])]);
      Object.keys(FUT_SECTORS).forEach(k => STRAT_STOCKS['SEC_'+k] = [...(FUT_SECTORS[k]||[])]);
    }
  } catch(e) { STRAT_STOCKS = {}; }
}
function saveStratStocks() {
  try { localStorage.setItem('stratStocks', JSON.stringify(STRAT_STOCKS)); } catch(e){}
}

// selectedInstruments: inst -> sysId (used by strategy chips)
let selectedInstruments = {};

/*
  WATCHLIST: Each tab has an array of items.
  Item shape: { inst, sysId, entryPrice: '', sl: '', mode: 'PAPER' }
*/
const WATCHLISTS = { CASH: [], FUTURE: [], OPTION: [] };
let activeWlTab = 'FUTURE';  // Default to Futures watchlist (Cash segment has no strategy)

function loadWatchlists() {
  try {
    const s = localStorage.getItem('watchlists');
    if (s) {
      const parsed = JSON.parse(s);
      Object.keys(parsed).forEach(k => {
        if (WATCHLISTS[k]) WATCHLISTS[k] = parsed[k] || [];
      });
    }
  } catch(e) {}
  // CASH segment has no strategy — clear it on every load to avoid stale entries
  WATCHLISTS['CASH'] = [];
  saveWatchlists();
}
function saveWatchlists() {
  try { localStorage.setItem('watchlists', JSON.stringify(WATCHLISTS)); } catch(e){}
}

/* ════════════════════════════════════════
   LOGIN
════════════════════════════════════════ */
const DASHBOARD_PASSWORD = 'sartrader2026';
function attemptLogin() {
  const pw = document.getElementById('loginPassword').value;
  const err = document.getElementById('loginError');
  if (pw === DASHBOARD_PASSWORD) {
    document.getElementById('loginOverlay').style.display = 'none';
    document.querySelector('.layout').style.display = 'flex';
    init(); // Initialize dashboard (watchlist, WebSocket, clocks)
  } else {
    err.style.display = 'block';
    document.getElementById('loginPassword').value = '';
  }
}
function logout() {
  // Stop all refresh timers
  if (window._chartTimer) { clearInterval(window._chartTimer); window._chartTimer = null; }
  // Close WebSocket
  if (ws && ws.readyState === WebSocket.OPEN) { ws.close(); ws = null; }
  // Clear cached state
  window._positions = {};
  window._quotes = {};
  window._state = null;
  // Return to login screen
  document.querySelector('.layout').style.display = 'none';
  document.getElementById('loginOverlay').style.display = 'flex';
  document.getElementById('loginPassword').value = '';
  document.getElementById('loginError').style.display = 'none';
  // Stop any chart refresh intervals
  try { clearInterval(window._chartTimer); } catch(e) {}
}
function initParticles() {
  const c = document.getElementById('loginParticles');
  if (!c) return;
  const colors=['#00c896','#3b82f6','#a78bfa','#f5c842','#ff4d6a','#22d3ee'];
  for (let i=0;i<18;i++) {
    const p=document.createElement('div'); p.className='login-particle';
    const sz=Math.random()*6+2;
    p.style.cssText=`width:${sz}px;height:${sz}px;background:${colors[i%colors.length]};left:${Math.random()*100}%;animation-duration:${Math.random()*12+8}s;animation-delay:${Math.random()*10}s`;
    c.appendChild(p);
  }
}
function initClock() {
  setInterval(()=>{
    const el=document.getElementById('liveClock');
    if(el) el.textContent=new Date().toLocaleTimeString('en-IN',{hour12:true});
  },1000);
}

/* ════════════════════════════════════════
   NAVIGATION
════════════════════════════════════════ */
const VIEWS={
  Dashboard:{nav:'navDashboard',id:'viewDashboard'},
  Strategies:{nav:'navStrategies',id:'viewStrategies'},
  Watchlist:{nav:'navWatchlist',id:'viewWatchlist'},
  Orders:{nav:'navOrders',id:'viewOrders'},
  Portfolio:{nav:'navPortfolio',id:'viewPortfolio'},
  Brokers:{nav:'navBrokers',id:'viewBrokers'},
};
function switchView(name){
  Object.values(VIEWS).forEach(v=>{
    const el=document.getElementById(v.id); if(el) el.classList.remove('active');
    const nav=document.getElementById(v.nav); if(nav) nav.classList.remove('active');
  });
  const v=VIEWS[name]; if(v){
    const el=document.getElementById(v.id); if(el) el.classList.add('active');
    const nav=document.getElementById(v.nav); if(nav) nav.classList.add('active');
  }
}

/* ════════════════════════════════════════
   WEBSOCKET
════════════════════════════════════════ */
let ws=null;

/* ════════════════════════════════════════
   BROKER CONNECTION
════════════════════════════════════════ */
function connectBroker(name){
  if(!ws||ws.readyState!==WebSocket.OPEN){
    showToast('Engine not connected','var(--red)'); return;
  }
  ws.send(JSON.stringify({command:'connect_broker',broker:name}));
  showToast(`Connecting ${name}...`, 'var(--blue)');
}

function disconnectBroker(name){
  if(!ws||ws.readyState!==WebSocket.OPEN){
    showToast('Engine not connected','var(--red)'); return;
  }
  ws.send(JSON.stringify({command:'disconnect_broker',broker:name}));
}

function renderBrokerStatus(brokers){
  const ms = brokers && brokers['MSTOCK'];
  const connected = ms && ms.connected;

  const badge = document.getElementById('mstockStatusBadge');
  const form = document.getElementById('mstockConnectForm');
  const connSec = document.getElementById('mstockConnectedSection');
  const posSec = document.getElementById('mstockPositionsList');

  if(connected && ms.account){
    badge.textContent = 'Connected';
    badge.style.background = 'rgba(0,200,100,0.15)';
    badge.style.color = 'var(--green)';
    form.style.display = 'none';
    connSec.style.display = 'block';

    document.getElementById('mstockClient').textContent = ms.account.client_id || '—';
    const bal = ms.account.balance || 0;
    document.getElementById('mstockBalance').textContent = 'Rs.' + Number(bal).toLocaleString('en-IN',{minimumFractionDigits:2});

    // Show positions
    if(ms.positions && ms.positions.length){
      posSec.innerHTML = '<table style="width:100%;font-size:12px"><tr style="color:var(--text-muted)"><td>Instrument</td><td>Side</td><td>Qty</td><td>Avg Price</td></tr>' +
        ms.positions.map(p=>`<tr style="border-top:1px solid var(--border)">
          <td style="padding:6px 4px">${p.instrument||'—'}</td>
          <td style="padding:6px 4px;color:${p.side==='LONG'?'var(--green)':'var(--red)'}">${p.side||'—'}</td>
          <td style="padding:6px 4px">${p.quantity||0}</td>
          <td style="padding:6px 4px">Rs.${Number(p.avg_price||0).toLocaleString('en-IN',{minimumFractionDigits:2})}</td>
        </tr>`).join('') + '</table>';
    } else {
      posSec.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px">No open positions</div>';
    }
  } else {
    badge.textContent = 'Disconnected';
    badge.style.background = 'rgba(255,80,80,0.12)';
    badge.style.color = 'var(--red)';
    form.style.display = 'block';
    connSec.style.display = 'none';
    posSec.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px">Connect broker to see positions</div>';
  }
}

function connectWS(){
  // Always use localhost for WebSocket (engine runs on same machine as browser)
  const httpHost=location.host||'localhost:8765';
  const [host,port]=httpHost.includes(':')?httpHost.split(':'):[httpHost,'8765'];
  // Fallback to localhost if host looks like an IP (avoids cross-origin WS issues)
  const wsHost = (host === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(host)) ? host : 'localhost';
  const wsUrl = `ws://${wsHost}:${Number(port)+1}`;
  console.log('[WS] Connecting to:', wsUrl, '| httpHost:', httpHost, '| host:', host, '| port:', port);
  ws=new WebSocket(wsUrl);
  ws.onopen=()=>{ console.log('[WS] Connected!'); const f=document.getElementById('footerMode'); if(f) f.textContent='CONNECTED ✓'; ws.send(JSON.stringify({command:'get_state'})); };
  ws.onmessage=(evt)=>{
    try{
      const msg=JSON.parse(evt.data);
      if(msg.type==='state'){
        // Populate WATCHLISTS from engine state (engine is source of truth)
        updateAll(msg.data);
      } else if(msg.type==='notification'){
        // Show engine notifications (trade results, errors, etc.)
        const n=msg;
        const color=n.success?'var(--green)':'var(--red)';
        showToast(n.message||'Done',color);
        // Play sound for trade events
        if(n.message&&n.message.includes('PAPER')&&n.success) playBuyAlert();
        if(n.message&&n.message.includes('LIVE')&&n.success) playSellAlert();
      } else if(msg.type==='trade_event'){
        // Real-time trade event toast
        const e=msg;
        const icon=e.event==='ENTRY'?'📋':e.event==='EXIT'?'✅':e.event==='REVERSAL'?'🔄':'📊';
        showToast(`${icon} ${e.event}: ${e.instrument} — ${e.signal_type||''}`, e.event==='ENTRY'?'var(--blue)':e.event==='EXIT'?'var(--green)':'var(--orange)');
        if(e.event==='ENTRY') playBuyAlert();
        if(e.event==='EXIT') playSellAlert();
      } else if(msg.type==='candles'){
        // OHLC candle data for chart
        if(msg.error){
          showToast('Chart error: '+msg.error,'var(--red)');
        } else {
          const tf=msg.interval||'1d';
          const range=msg.range||'60d';
          showToast('📊 '+msg.symbol+' '+tf+' chart loaded ('+((msg.candles||[]).length)+' bars)','var(--green)');
          renderTlChart(msg.instrument, msg.symbol, msg.candles||[], tf, range);
        }
      }
      // Force refresh when server signals state change
      if(n&&n.forceRefresh&&ws&&ws.readyState===WebSocket.OPEN){
        ws.send(JSON.stringify({command:'get_state'}));
      }
    }catch(e){}
  };
  ws.onerror=()=>{ const f=document.getElementById('footerMode'); if(f) f.textContent='WS ERROR'; console.warn('[WS] Connection error — reconnecting...'); };
  ws.onclose=()=>{ console.warn('[WS] Connection closed — reconnecting in 2s...'); setTimeout(connectWS,2000); };
}

/* ════════════════════════════════════════
   STATE UPDATE
════════════════════════════════════════ */
function updateAll(state){
  window._quotes=state.quotes||{};
  window._positions=state.positions||{};
  // Keep LTP, Total P&L reactive on every engine tick (no table rebuild)
  if(document.getElementById('ordersPanelTrades')?.style.display!=='none'){
    refreshTlCells();
  }
  window._segmentPnl=state.segment_pnl||{CASH:0,FUTURES:0,OPTIONS:0};
  const prevSignalCount=window._prevSignalCount||0;
  window._prevSignalCount=state.signals?.length||0;
  document.getElementById('topModeBadge').textContent=`● ${state.mode||'PAPER'}`;
  document.getElementById('topModeBadge').className=`live-badge ${(state.mode||'PAPER').toLowerCase()}`;
  const fmode=document.getElementById('footerMode'); if(fmode) fmode.textContent=`${state.mode||'PAPER'} MODE`;
  updateTicker('tkNifty',state.quotes['NIFTY']);
  updateTicker('tkBankNifty',state.quotes['BANKNIFTY']);
  updateTicker('tkGold',state.quotes['GOLD']);
  updateTicker('tkSilver',state.quotes['SILVER']);
  updateTrades(state.trades||[]);
  window._allTrades=state.trades||[];
  updateSignals(state.signals||[],prevSignalCount);
  // Sync WATCHLISTS from engine state — engine is source of truth for watchlist data
  // This ensures watchlist instruments have live LTP from the engine's quote cache
  if(state.watchlist_data){
    const wd = state.watchlist_data;
    // Merge engine watchlist into local WATCHLISTS (engine has base symbols as keys)
    Object.entries(wd).forEach(([inst, data])=>{
      const cat = data.strategy?.startsWith('SEC_') ? 'FUTURE' : (data.strategy?.category || 'CASH');
      if(!WATCHLISTS[cat]) WATCHLISTS[cat]=[];
      if(!WATCHLISTS[cat].find(x=>x.inst===inst)){
        WATCHLISTS[cat].push({
          inst,
          sysId: data.strategy || cat,
          mode: 'PAPER',
          entryPrice: '',
          sl: ''
        });
      }
    });
  }
  refreshAllChips();
  renderAllWatchlists();
  // Render broker status
  renderBrokerStatus(state.brokers||{});
  // Render Trade Log (18-column open positions)
  renderTradeLog();
}
function updateTicker(id,q){
  const el=document.getElementById(id); if(!el)return;
  const pe=el.querySelector('.tk-price');const ae=el.querySelector('.tk-arrow');const ce=el.querySelector('.tk-change');
  if(!pe)return;
  if(!q || (!q.last_price && !q.price)){
    // No quote available yet — show placeholder
    pe.textContent='—'; if(ae)ae.textContent='—'; if(ce)ce.textContent='—';
    el.className='ticker-item';
    return;
  }
  const curr=Number(q.last_price||q.price||0);const chg=Number(q.change||0);const pct=Number(q.change_pct||0);
  pe.textContent=curr>0?curr.toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
  if(ae) ae.textContent=chg>=0?'▲':'▼';
  if(ce) ce.textContent=`${chg>=0?'+':''}${pct.toFixed(2)}%`;
  el.className=`ticker-item ${chg>=0?'up':'down'}`;
}
function updateTrades(trades){
  const tb=document.getElementById('tradesBody');
  if(!tb)return;
  if(!trades.length){ tb.innerHTML='<tr><td colspan="8" class="empty-state">No trades yet...</td></tr>'; return; }
  tb.innerHTML=trades.slice(-10).reverse().map((t,i)=>{
    const pnl=t.pnl||0;const cls=pnl>=0?'badge-green':'badge-red';
    const status=t.exit_price?'Closed':'Open';
    return`<tr>
      <td>${trades.length-i}</td>
      <td>${(t.entry_date||'').split('T')[0]||'—'}</td>
      <td>${t.instrument||'—'}</td>
      <td><span class="${t.direction==='LONG'?'badge-green':'badge-red'}">${t.direction||'—'}</span></td>
      <td>₹${(t.entry_price||0).toLocaleString('en-IN',{minimumFractionDigits:2})}</td>
      <td>${t.exit_price?'₹'+Number(t.exit_price).toLocaleString('en-IN',{minimumFractionDigits:2}):'—'}</td>
      <td><span class="${cls}">${pnl>=0?'+':''}₹${pnl.toFixed(0)}</span></td>
      <td>${status}</td>
    </tr>`;
  }).join('');

  // ── Portfolio box calculations ──────────────────────────────────
  const today=new Date().toISOString().split('T')[0];
  const closedTrades=trades.filter(t=>t.exit_price!=null);
  const runningTrades=trades.filter(t=>!t.exit_price);
  const longs=runningTrades.filter(t=>t.direction==='LONG').length;
  const shorts=runningTrades.filter(t=>t.direction==='SHORT').length;

  // Win rate (closed trades only)
  const wins=closedTrades.filter(t=>t.pnl>0).length;
  const winRate=closedTrades.length>0?Math.round((wins/closedTrades.length)*100):null;

  // Closed P&L (only closed trades)
  const closedPnl=closedTrades.reduce((s,t)=>s+(t.pnl||0),0);

  // Today P&L (closed trades today)
  const todayPnl=closedTrades
    .filter(t=>(t.exit_date||'').startsWith(today))
    .reduce((s,t)=>s+(t.pnl||0),0);

  // Total P&L (running + closed)
  const runningPnl=runningTrades.reduce((s,t)=>{
    const q=getQuote(t.instrument);
    if(!q)return s;
    const ltp=q.last_price||q.price||0;
    const mult=(t.direction==='LONG')?1:-1;
    return s+mult*(ltp-t.entry_price)*t.quantity;
  },0);
  const totalPnl=closedPnl+runningPnl;

  // Segment P&L from engine state
  const segPnl=window._segmentPnl||{CASH:0,FUTURES:0,OPTIONS:0};

  // ── Update boxes ───────────────────────────────────────────────
  const setPnl=(id,val,subId)=>{
    const el=document.getElementById(id);
    if(!el)return;
    el.textContent=`${val>=0?'+':''}₹${Math.abs(val).toLocaleString('en-IN')}`;
    el.style.color=val>=0?'var(--green)':'var(--red)';
    if(subId){const s=document.getElementById(subId);if(s)s.style.color=val>=0?'var(--green)':'var(--red)';}
  };
  const setNum=(id,val,color)=>{
    const el=document.getElementById(id);if(el){el.textContent=val;if(color)el.style.color=color;}
  };
  const setWinRate=(val)=>{
    const el=document.getElementById('snapWinRate');
    if(el)el.textContent=val!=null?`${val}%`:'—';
  };

  setPnl('snapTotalPnl',totalPnl);
  setPnl('snapTodayPnl',todayPnl);
  setNum('snapLongs',longs,'var(--green)');
  setNum('snapShorts',shorts,'var(--red)');
  setPnl('snapFutPnl',segPnl.FUTURES||0);
  setPnl('snapCashPnl',segPnl.CASH||0);
  setPnl('snapOptPnl',segPnl.OPTIONS||0);
  setWinRate(winRate);
  setPnl('snapClosedPnl',closedPnl);

  // Also update full trade log in Orders view
  updateFullTradeLog(trades);
  updateDailySummary(trades);
}

/* ════════════════════════════════════════
   FULL TRADE LOG
════════════════════════════════════════ */
function updateFullTradeLog(trades){
  const tb=document.getElementById('fullTradesBody');
  if(!tb)return;
  if(!trades.length){tb.innerHTML='<tr><td colspan="11" class="empty-state">No trades yet...</td></tr>';return;}
  tb.innerHTML=trades.slice().reverse().map((t,i)=>{
    const pnl=t.pnl||0;
    const cls=pnl>=0?'badge-green':'badge-red';
    const status=t.exit_price?'Closed':'Open';
    const seg=t.segment||'FUTURES';
    const jn=loadJournalEntry(t.trade_id);
    return`<tr>
      <td>${trades.length-i}</td>
      <td>${(t.entry_date||'').split('T')[0]||'—'}</td>
      <td>${t.instrument||'—'}</td>
      <td><span style="font-size:11px;padding:2px 6px;background:var(--bg-card2);border-radius:4px">${seg}</span></td>
      <td><span class="${t.direction==='LONG'?'badge-green':'badge-red'}">${t.direction||'—'}</span></td>
      <td>₹${(t.entry_price||0).toLocaleString('en-IN',{minimumFractionDigits:2})}</td>
      <td>${t.exit_price?'₹'+Number(t.exit_price).toLocaleString('en-IN',{minimumFractionDigits:2}):'—'}</td>
      <td>${t.quantity||'—'}</td>
      <td><span class="${cls}">${pnl>=0?'+':''}₹${pnl.toFixed(0)}</span></td>
      <td><span class="badge-gold">${status}</span></td>
      <td>
        ${t.exit_price?'<button onclick="openJournal(\''+t.trade_id+'\',\''+t.instrument+'\','+pnl+',\''+(t.entry_date||'')+'\')" style="background:var(--bg-card2);border:1px solid var(--border);color:var(--text-secondary);border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer">'+(jn?'📝':'📒 Add')+'</button>':'—'}
      </td>
    </tr>`;
  }).join('');
}

/* ════════════════════════════════════════
   DAILY SUMMARY
════════════════════════════════════════ */
function calcPeriod(trades,startDate,endDate){
  const ct=trades.filter(t=>{const d=(t.exit_date||'').split('T')[0];return d>=startDate&&d<=endDate&&t.exit_price!=null;});
  const wins=ct.filter(t=>t.pnl>0).length;
  const loss=ct.filter(t=>t.pnl<0).length;
  const pnl=ct.reduce((s,t)=>s+(t.pnl||0),0);
  const wr=ct.length>0?Math.round((wins/ct.length)*100):null;
  return{count:ct.length,wins,loss,wr,pnl};
}
function updateDailySummary(trades){
  const today=new Date();
  const fmt=d=>d.toISOString().split('T')[0];
  const todayStr=fmt(today);
  const weekStart=new Date(today);weekStart.setDate(today.getDate()-today.getDay());
  const monthStart=new Date(today.getFullYear(),today.getMonth(),1);
  const allStart='2020-01-01';

  const periods=[
    {ids:['sumToday'],start:todayStr,end:todayStr},
    {ids:['sumWeek'],start:fmt(weekStart),end:todayStr},
    {ids:['sumMonth'],start:fmt(monthStart),end:todayStr},
    {ids:['sumAll'],start:allStart,end:todayStr},
  ];
  periods.forEach(p=>{
    const r=calcPeriod(trades,p.start,p.end);
    const set=(id,val,pnl=false)=>{
      const el=document.getElementById(p.ids[0]+id);
      if(!el)return;
      if(pnl){el.textContent=`${val>=0?'+':''}₹${Math.abs(val).toLocaleString('en-IN')}`;el.style.color=val>=0?'var(--green)':'var(--red)';}
      else{el.textContent=val!=null?val:'—';el.style.color='';}
    };
    set('Count',r.count);
    set('Wins',r.wins);
    set('Loss',r.loss);
    set('Wr',r.wr!=null?`${r.wr}%`:'—');
    set('Pnl',r.pnl,true);
  });
}

/* ════════════════════════════════════════
   TRADE JOURNAL
════════════════════════════════════════ */
let _journalDraft={};
function loadJournal(){
  try{return JSON.parse(localStorage.getItem('tradeJournal')||'{}');}catch(e){return{};}
}
function saveJournal(data){
  try{localStorage.setItem('tradeJournal',JSON.stringify(data));}catch(e){}
}
function loadJournalEntry(tid){
  const j=loadJournal();return j[tid]||'';
}
function openJournal(tid,inst,pnl,entryDate){
  const existing=loadJournalEntry(tid);
  _journalDraft[tid]={tid,inst,pnl,entryDate,note:existing};
  const note=prompt(`Trade Journal — ${inst}\n\nP&L: ${pnl>=0?'+':''}₹${pnl.toFixed(0)}\n\nEnter your trade notes (what went right/wrong, lessons learned):`,existing||'');
  if(note!==null){
    const j=loadJournal();j[tid]=note;saveJournal(j);
    showToast('Journal saved for '+inst,'var(--green)');
  }
  renderJournal();
}
function renderJournal(){
  const el=document.getElementById('journalEntries');
  const empty=document.getElementById('journalEmpty');
  if(!el)return;
  const j=loadJournal();
  const entries=Object.entries(j).filter(([k,v])=>v&&v.trim()).reverse();
  if(!entries.length){if(empty)empty.style.display='';el.innerHTML='';return;}
  if(empty)empty.style.display='none';
  el.innerHTML=entries.map(([tid,note])=>{
    const parts=tid.split('_');
    const inst=parts[0]||tid;
    return`<div class="journal-card">
      <div class="journal-card-header">
        <div>
          <div class="journal-inst">${inst}</div>
          <div class="journal-date">${parts[1]||''}</div>
        </div>
      </div>
      <div class="journal-note"><div style="margin-bottom:6px;font-size:11px;color:var(--text-muted)">Notes:</div>${note.replace(/\n/g,'<br>')}</div>
      <div class="journal-actions">
        <button class="journal-del" onclick="deleteJournalEntry('${tid}')">🗑 Delete</button>
      </div>
    </div>`;
  }).join('');
}
function deleteJournalEntry(tid){
  if(!confirm('Delete this journal entry?'))return;
  const j=loadJournal();delete j[tid];saveJournal(j);renderJournal();
  showToast('Journal entry deleted','var(--orange)');
}

/* ════════════════════════════════════════
   EXPORT CSV
════════════════════════════════════════ */
function exportTradesCSV(){
  const trades=window._allTrades||[];
  if(!trades.length){showToast('No trades to export','var(--orange)');return;}
  const headers=['TradeID','Date','Instrument','Segment','Direction','Entry Price','Exit Price','Qty','P&L','Reason'];
  const rows=trades.map(t=>[
    t.trade_id||'',
    (t.entry_date||'').split('T')[0],
    t.instrument||'',
    t.segment||'FUTURES',
    t.direction||'',
    t.entry_price||0,
    t.exit_price||'',
    t.quantity||'',
    t.pnl||0,
    (t.reason||'').replace(/,/g,';')
  ]);
  const csv=[headers.join(','),...rows.map(r=>r.join(','))].join('\n');
  const blob=new Blob([csv],{type:'text/csv'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download=`sartrader_trades_${new Date().toISOString().split('T')[0]}.csv`;
  a.click();showToast('CSV exported!','var(--green)');
}



/* ════════════════════════════════════════
   ORDERS TAB SWITCHER
════════════════════════════════════════ */
let _ordersTab='Trades';  // Default to Trade Log (open positions with all 20 columns)
let _tradeMode='ALL';  // ALL/PAPER/LIVE filter for Trade Log
let _thMode='ALL';     // ALL/PAPER/LIVE filter for Trade History
let _thSeg='ALL';        // Segment filter for Trade History

function switchTradeMode(mode){
  _tradeMode=mode;
  document.getElementById('tlModeALL')?.classList.toggle('active',mode==='ALL');
  document.getElementById('tlModePAPER')?.classList.toggle('active',mode==='PAPER');
  document.getElementById('tlModeLIVE')?.classList.toggle('active',mode==='LIVE');
  renderTradeLog();
}
function switchThMode(mode){
  _thMode=mode;
  document.getElementById('thModeALL')?.classList.toggle('active',mode==='ALL');
  document.getElementById('thModePAPER')?.classList.toggle('active',mode==='PAPER');
  document.getElementById('thModeLIVE')?.classList.toggle('active',mode==='LIVE');
  renderTradeHistory();
}
function switchThSeg(seg){
  _thSeg=seg;
  ['ALL','FUTURES','CASH','OPTIONS'].forEach(s=>{
    document.getElementById('thSeg'+s)?.classList.toggle('active',s===seg);
  });
  renderTradeHistory();
}
function switchOrdersTab(tab){
  _ordersTab=tab;
  ['Summary','Journal','History','Trades'].forEach(t=>{
    const te=document.getElementById('ordersTab'+t);
    const pe=document.getElementById('ordersPanel'+t);
    if(te){
      const isActive=t===tab;
      te.style.background=isActive?'var(--accent)':'var(--bg-card2)';
      te.style.borderColor=isActive?'var(--accent)':'var(--border)';
      te.style.color=isActive?'#fff':'var(--text-primary)';
    }
    if(pe)pe.style.display=t===tab?'':'none';
  });
  if(tab==='Journal')renderJournal();
  if(tab==='Summary')renderSummary();
  if(tab==='History')renderTradeHistory();
  if(tab==='Trades')renderTradeLog();
}

/* ════════════════════════════════════════
   TRADE LOG (open positions)
════════════════════════════════════════ */
let _tradeSeg='ALL';
function switchTlSeg(seg){
  _tradeSeg=seg;
  ['ALL','FUTURES','CASH','OPTIONS'].forEach(s=>{
    const el=document.getElementById('tlSeg'+s);
    if(el)el.classList.toggle('active',s===seg);
  });
  renderTradeLog();
}
// Extract base symbol from contract name: M&MSEPFUT26 → M&M, NIFTY26SEPFUT → NIFTY, TATAMOTORS26SEPF26 → TATAMOTORS
function getBaseSymbol(inst){
  if(!inst)return'';
  const u=inst.toUpperCase();
  let base=u;
  // Step 1: strip month+year expiry (SEP26, 26SEP, SEPFUT26, etc.) — do FIRST before FUT
  base=base.replace(/(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{0,2}\d{2}$/,'');
  base=base.replace(/^\d+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)/,'');
  // Step 2: strip FUT / FUTFUTURES suffix
  base=base.replace(/FUT(FUTURES)?$/,'');
  // Step 3: strip trailing digits (for indices like NIFTY26)
  base=base.replace(/\d+$/,'');
  // Step 4: strip any remaining partial month codes (e.g. SEP26 left after step 1 failed)
  base=base.replace(/(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d*$/,'');
  return base.trim()||inst;
}
// Global quote lookup: try base symbol first (watchlist), then full contract name (engine state)
function getQuote(inst){
  const base=getBaseSymbol(inst||'');
  return window._quotes?.[base] || window._quotes?.[inst] || null;
}
function _tlFiltered(){
  // Returns positions matching current PAPER/LIVE + segment filter, sorted by status
  const positions=window._positions||{};
  const segMap={FUTURES:['FUTURES','STOCK_FUTURES','INDEX_FUTURES','COMMODITY_FUTURES']};
  return Object.entries(positions).filter(([inst,p])=>{
    if(p.status==='REMOVED')return false;
    const posMode=p.mode||'PAPER';
    if(_tradeMode!=='ALL'&&posMode!==_tradeMode)return false;
    const seg=p.segment_type||'STOCK_FUTURES';
    if(_tradeSeg!=='ALL'){
      if(_tradeSeg==='CASH'&&seg!=='CASH')return false;
      if(_tradeSeg==='OPTIONS'&&seg!=='OPTIONS')return false;
      if(_tradeSeg==='FUTURES'&&!segMap.FUTURES.includes(seg))return false;
    }
    return true;
  }).sort((a,b)=>{const o={ACTIVE:0,WAITING:1,STOPPED:2};return(o[a[1].status]||9)-(o[b[1].status]||9);});
}
function renderTradeLog(){
  const positions=window._positions||{};
  const tb=document.getElementById('tlBody');
  if(!tb)return;

  // Friendly sector name map — keys must match engine's _infer_sector output
  const sectorMap={
    'AUTO':'Auto','PVT_BANK':'PVT Bank','PSU_BANK':'PSU Bank',
    'IT':'IT','PHARMA':'Pharma','METAL':'Metal','FMCG':'FMCG',
    'REAL_ESTATE':'Real Estate','INDEX_FUTURES':'Idx Futures',
    'STOCK_FUTURES':'Stock','COMMODITY_FUTURES':'Commodity',
    'ENERGY':'Energy','CONSUMER':'Consumer','FINANCIAL_SERVICES':'Financial Services',
    'PSE':'PSE','DEFENCE':'Defence','REALTY':'Realty','INFRASTRUCTURE':'Infrastructure',
    'MISC':'Misc','OTHER':'Other','INFRA':'Infra',
  };

  // Count active/waiting
  let ac=0,wc=0;
  Object.values(positions).forEach(p=>{
    if(p.status==='ACTIVE')ac++;
    else if(p.status==='WAITING')wc++;
  });
  const ae=document.getElementById('tlActiveCount');
  const we=document.getElementById('tlWaitingCount');
  if(ae)ae.textContent=ac;
  if(we)we.textContent=wc;

  const list=_tlFiltered();
  if(!list.length){
    tb.innerHTML='<tr><td colspan="21" class="empty-state">No positions. Use the form below or go to Watchlist → GO.</td></tr>';
    return;
  }

  let html='';
  list.forEach(([inst,p],i)=>{
    // Show LONG/SHORT/WAITING — engine sets side="WAITING" for WAITING positions
    // Fallback: if both null, show status-based label
    const rawDir=p.direction||p.side||null;
    const dir=(rawDir&&rawDir!=='null'&&rawDir!=='undefined')?rawDir:(p.status==='WAITING'?'WAITING':'—');
    const dirCls=dir==='LONG'?'badge-green':dir==='SHORT'?'badge-red':'badge-gold';
    const status=p.status||'—';
    const segType=p.segment_type||'STOCK_FUTURES';
    const segLabel=segType==='INDEX_FUTURES'?'Idx':segType==='STOCK_FUTURES'?'Stock':segType==='OPTIONS'?'Opt':'Cash';
    const isWaiting=status==='WAITING';
    const isStopped=status==='STOPPED';
    const rowBg=isWaiting?'rgba(200,160,0,0.04)':isStopped?'rgba(255,60,60,0.04)':'transparent';
    // Support both DB field (initial_lots) and engine field (qty)
    const lots=p.initial_lots||p.qty||1;
    const ep=p.entry_price?'₹'+Number(p.entry_price).toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
    const reason=p.entry_reason||'—';
    const base=getBaseSymbol(inst);
    const q=getQuote(inst);
    const ltp=q?(q.last_price||q.price||0):null;
    const ltpStr=ltp?'₹'+Number(ltp).toLocaleString('en-IN',{minimumFractionDigits:2}):'<span style="color:var(--text-muted)">—</span>';
    const pnl=(ltp&&p.entry_price&&dir!=='—')?(dir==='LONG'?(ltp-p.entry_price)*lots:(p.entry_price-ltp)*lots):null;
    const pnlStr=pnl!==null?(pnl>=0?'+₹':'₹')+Math.abs(pnl).toFixed(0):'—';
    const pnlCls=pnl===null?'':(pnl>=0?'var(--green)':'var(--red)');
    const slVal=p.current_sl?'₹'+Number(p.current_sl).toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
    const prevT=p.prev_top>0?'₹'+Number(p.prev_top).toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
    const prevB=p.prev_bottom>0?'₹'+Number(p.prev_bottom).toLocaleString('en-IN',{minimumFractionDigits:2}):'—';
    const pyOn=p.pyramiding_mode==='on'||p.pyramiding_mode==='auto';
    const canStop=!isWaiting&&!isStopped;
    const canRestart=isStopped||isWaiting;
    const canRemove=!isStopped;
    const stratLabel=p.strategy==='SAR_TOP_BOTTOM'?'TB':p.strategy||'—';
    const gapRule=p.gap_rule||'inactive';
    const gapActive=gapRule==='active';
    const rollVal=p.rollover?'Yes':'No';
    // Friendly sector label — null/undefined → '—', unknown code → 'Other'
    const rawSector=p.sector;
    const sectorLabel=!rawSector?'—':(sectorMap[rawSector]||'Other');
    // Pyramiding lots: DB uses pyramid_lots, engine uses pyramids
    const pyrLots=p.pyramiding_lots||p.pyramids||1;

    html+=`<tr data-inst="${inst}" style="background:${rowBg}">
      <td style="text-align:center;color:var(--text-muted)">${i+1}</td>
      <td style="font-size:11px">${p.entry_date?(p.entry_date.includes('T')?p.entry_date.split('T')[0]+' '+p.entry_date.split('T')[1]?.substring(0,5):p.entry_date):'—'}</td>
      <td style="text-align:center">
        <span style="cursor:pointer;color:var(--text-muted)" onclick="tlAdjLots('${inst}',${i},-1)">−</span>
        <span id="tlLots_${i}" style="font-weight:700;color:var(--accent);padding:0 4px">${lots}</span>
        <span style="cursor:pointer;color:var(--text-muted)" onclick="tlAdjLots('${inst}',${i},1)">+</span>
      </td>
      <td style="font-size:11px;color:var(--accent)">${stratLabel}</td>
      <td><span class="wl-name">${base}</span><span style="font-size:9px;color:var(--text-muted)">${segLabel}</span></td>
      <td style="font-size:11px">${sectorLabel}</td>
      <td><span class="${dirCls}" style="font-size:11px">${dir}</span></td>
      <td><div style="font-size:11px">${ep}</div><div style="font-size:10px;color:var(--text-muted)">${reason}</div></td>
      <td id="tlLTP_${i}" style="font-weight:700;font-size:12px;color:var(--text-primary)">${ltpStr}</td>
      <td id="tlSL_${i}" style="cursor:pointer;font-size:11px" title="Click to override" onclick="tlEditSL(${i},'${inst}')">${p.sl_mode==='manual'&&p.current_sl?'<span style="color:var(--blue)">₹'+Number(p.current_sl).toLocaleString('en-IN',{minimumFractionDigits:2})+'</span>':'<span style="color:var(--gold)">'+(p.current_sl?'₹'+Number(p.current_sl).toLocaleString('en-IN',{minimumFractionDigits:2}):'—')+'</span>'}</td>
      <td id="tlGap_${i}" style="cursor:pointer;font-size:11px;color:${gapActive?'var(--orange)':'var(--text-muted)'}" onclick="tlToggle('${inst}','gap_rule',${i})">${gapRule}</td>
      <td style="font-size:11px;color:var(--text-muted)">${prevT}</td>
      <td style="font-size:11px;color:var(--text-muted)">${prevB}</td>
      <td style="text-align:center">
        <span style="cursor:pointer;color:var(--text-muted);font-size:10px" onclick="tlAdjPyr('${inst}',${i},-1)">−</span>
        <span id="tlPyr_${i}" style="font-size:11px;font-weight:700;color:var(--accent)">${pyrLots}</span>
        <span style="cursor:pointer;color:var(--text-muted);font-size:10px" onclick="tlAdjPyr('${inst}',${i},1)">+</span>
      </td>
      <td id="tlRoll_${i}" style="cursor:pointer;font-size:11px" onclick="tlToggleRoll('${inst}',${i})">${rollVal}</td>
      <td style="font-size:12px;font-weight:600;color:${pnlCls}">${pnlStr}</td>
      <td id="tlTPnl_${i}" style="font-weight:700;font-size:13px;color:var(--text-muted)">—</td>
      <td><button class="btn-chart" onclick="openTlChart('${inst}','${base}')" style="padding:3px 8px;font-size:11px;background:var(--blue-dim);color:var(--blue);border:1px solid rgba(59,130,246,0.3);border-radius:6px;cursor:pointer">📊</button></td>
      <td>${canStop?`<button class="btn-stop" onclick="onTlStop('${inst}')" style="padding:3px 8px;font-size:11px">Stop</button>`:'<span style="color:var(--text-muted);font-size:11px">—</span>'}</td>
      <td>${canRestart?`<button class="btn-restart" onclick="onTlRestart('${inst}')" style="padding:3px 8px;font-size:11px">Restart</button>`:'<span style="color:var(--text-muted);font-size:11px">—</span>'}</td>
      <td>${canRemove?`<button class="btn-remove-tl" onclick="onTlRemove('${inst}')" style="padding:3px 8px;font-size:11px">Remove</button>`:'<span style="color:var(--text-muted);font-size:11px">—</span>'}</td>
    </tr>`;
  });
  tb.innerHTML=html;
  refreshTlCells();
}
// ── Reactive column refresh (LTP, SL, Total P&L) called on every engine tick
function refreshTlCells(){
  const list=_tlFiltered();
  let totalPnl=0;
  list.forEach(([inst,p],i)=>{
    const q=getQuote(inst);
    const ltp=q?(q.last_price||q.price||0):null;

    // LTP
    const ltpEl=document.getElementById('tlLTP_'+i);
    if(ltpEl&&ltp)ltpEl.textContent='₹'+Number(ltp).toLocaleString('en-IN',{minimumFractionDigits:2});

    // SL (auto-computed by engine)
    const slEl=document.getElementById('tlSL_'+i);
    if(slEl&&p.current_sl){
      const slTxt='₹'+Number(p.current_sl).toLocaleString('en-IN',{minimumFractionDigits:2});
      const cls=p.sl_mode==='manual'?'var(--blue)':'var(--gold)';
      slEl.innerHTML=`<span style="color:${cls};cursor:pointer">${slTxt}</span>`;
    }

    // P&L + Total
    const dir2=p.direction||p.side||'—';
    if(p.status==='ACTIVE'&&p.entry_price&&dir2!=='—'){
      const l=dir2==='LONG'?(ltp||0)-p.entry_price:p.entry_price-(ltp||0);
      const lots2=p.initial_lots||p.qty||1;
      const rowPnl=l*lots2;
      totalPnl+=rowPnl;
      const el=document.getElementById('tlTPnl_'+i);
      if(el){el.textContent=(rowPnl>=0?'+₹':'−₹')+Math.abs(rowPnl).toFixed(0);el.style.color=rowPnl>=0?'var(--green)':'var(--red)';}
    }

    // Lots (in case changed elsewhere)
    const lotsEl=document.getElementById('tlLots_'+i);
    if(lotsEl)lotsEl.textContent=p.initial_lots||p.qty||1;

    // Pyramiding lots
    const pyrEl=document.getElementById('tlPyr_'+i);
    if(pyrEl)pyrEl.textContent=p.pyramiding_lots||p.pyramids||1;
  });
  const el=document.getElementById('tlTotalPnl');
  if(el){
    el.textContent='Total P&L: '+(totalPnl>=0?'+':'−')+'₹'+Math.abs(totalPnl).toFixed(0);
    el.style.color=totalPnl>=0?'var(--green)':'var(--red)';
    el.style.fontWeight='700';
  }
}
// ── Toggle gap_rule / pyramiding_on
function tlToggle(inst,field,i){
  if(!ws||ws.readyState!==WebSocket.OPEN){showToast('Engine not connected','var(--red)');return;}
  const positions=window._positions||{};
  const p=positions[inst];
  if(!p)return;
  let newVal;
  if(field==='gap_rule'){
    newVal=p.gap_rule==='active'?'inactive':'active';
  } else if(field==='pyramiding_on'){
    newVal=!p.pyramiding_on;
  }
  const payload={command:'update_strategy_params',instrument:inst};
  payload[field]=newVal;
  ws.send(JSON.stringify(payload));
}
// ── Toggle rollover (yes/no)
function tlToggleRoll(inst,i){
  if(!ws||ws.readyState!==WebSocket.OPEN){showToast('Engine not connected','var(--red)');return;}
  const positions=window._positions||{};
  const p=positions[inst];
  if(!p)return;
  ws.send(JSON.stringify({command:'update_strategy_params',instrument:inst,rollover:!p.rollover}));
}
// ── Edit SL: click shows inline input
function tlEditSL(i,inst){
  const positions=window._positions||{};
  const p=positions[inst];
  if(!p)return;
  const el=document.getElementById('tlSL_'+i);
  if(!el)return;
  const current=p.current_sl||p.entry_price||0;
  el.innerHTML=`<input id="tlSLInp_${i}" type="number" step="0.5" value="${current}"
    style="width:70px;background:var(--bg-card);border:1px solid var(--accent);color:var(--text-primary);
    border-radius:4px;padding:2px 5px;font-size:11px"
    onkeydown="if(event.key==='Enter')tlSaveSL(${i},'${inst}')"
    onclick="event.stopPropagation()">`;
  const inp=document.getElementById('tlSLInp_'+i);
  if(inp){inp.focus();inp.select();}
}
function tlSaveSL(i,inst){
  const inp=document.getElementById('tlSLInp_'+i);
  if(!inp||!ws||ws.readyState!==WebSocket.OPEN){showToast('Engine not connected','var(--red)');return;}
  const val=parseFloat(inp.value);
  if(isNaN(val)||val<=0){showToast('Enter a valid price','var(--orange)');return;}
  ws.send(JSON.stringify({command:'update_strategy_params',instrument:inst,sl_manual_price:val,sl_mode:'manual'}));
}
// ── Adjust lots (1–10)
function tlAdjLots(inst,i,delta){
  if(!ws||ws.readyState!==WebSocket.OPEN){showToast('Engine not connected','var(--red)');return;}
  const p=(window._positions||{})[inst];
  if(!p)return;
  const newLots=Math.max(1,Math.min(10,(p.initial_lots||1)+delta));
  ws.send(JSON.stringify({command:'update_strategy_params',instrument:inst,initial_lots:newLots}));
}
// ── Adjust pyramiding lots (1–10)
function tlAdjPyr(inst,i,delta){
  if(!ws||ws.readyState!==WebSocket.OPEN){showToast('Engine not connected','var(--red)');return;}
  const p=(window._positions||{})[inst];
  if(!p)return;
  const newPyr=Math.max(1,Math.min(10,(p.pyramiding_lots||1)+delta));
  ws.send(JSON.stringify({command:'update_strategy_params',instrument:inst,pyramiding_lots:newPyr}));
}
function onTlStop(inst){if(!confirm('Stop '+inst+'?'))return;if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({command:'stop_position',instrument:inst,mode:'PAPER'}));}
// ── Quick Add Instrument from Trade Log form (bypasses Watchlist)
function tlQuickAdd(){
  const input=document.getElementById('tlAddInst');
  const modeSel=document.getElementById('tlAddMode');
  const stratSel=document.getElementById('tlAddStrat');
  const sectorSel=document.getElementById('tlAddSector');
  if(!input||!modeSel)return;
  const val=input.value.trim().toUpperCase();
  if(!val){showToast('Enter an instrument name','var(--orange)');return;}
  if(!(ws&&ws.readyState===WebSocket.OPEN)){showToast('Engine not connected','var(--red)');return;}
  const mode=modeSel.value;
  const strategy=stratSel?stratSel.value:'SAR_TOP_BOTTOM';
  const sector=sectorSel&&sectorSel.value?sectorSel.value:_inferSector(val);
  ws.send(JSON.stringify({
    command:'add_position',
    instrument:val,
    mode:mode,
    strategy:strategy,
    segment:'STOCK_FUTURES',
    sector:sector,
  }));
  showToast('📋 '+val+' added ('+mode+', '+strategy.split('_')[0]+')',mode==='LIVE'?'var(--orange)':'var(--blue)');
  input.value='';
}
function onTlRestart(inst){if(!confirm('Restart '+inst+'?'))return;if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({command:'restart_position',instrument:inst,mode:'PAPER'}));}
function onTlRemove(inst){
  if(!confirm('Remove '+inst+' from log?'))return;
  // Remove from local state immediately for instant UI feedback
  if(window._positions&&window._positions[inst]){
    delete window._positions[inst];
    renderTradeLog();
  }
  if(ws&&ws.readyState===WebSocket.OPEN){
    ws.send(JSON.stringify({command:'remove_position',instrument:inst}));
  }
}
// ── Chart modal — requests candle data from engine and renders OHLC chart
window._chartCache = {};   // { interval: { candles, interval, range } }
window._chartCfg  = { inst: '', symbol: '', interval: '1d', range: '60d', chartType: 'candle' };
window._chartTimer = null;  // auto-refresh interval handle

function openTlChart(inst, base){
  console.log('[Chart] openTlChart called — inst:', inst, 'base:', base);
  if(!ws||ws.readyState!==WebSocket.OPEN){
    showToast('Engine not connected','var(--red)');return;
  }
  // Default: 60-day daily candles (TB strategy uses daily line chart)
  window._chartCfg = { inst, symbol: base, interval: '1d', range: '60d', chartType: 'candle' };
  window._chartCache = {};
  // Clear any existing refresh timer
  if(window._chartTimer){ clearInterval(window._chartTimer); window._chartTimer=null; }
  ws.send(JSON.stringify({command:'get_candles',instrument:inst,symbol:base,interval:'1d',range:'60d'}));
  showToast('📊 '+base+' daily chart — loading...','var(--blue)');
}

function _drawChart(canvas, ohlc, chartType, interval){
  const W=700,H=340,padL=60,padR=20,padT=20,padB=40;
  const chartW=W-padL-padR,chartH=H-padT-padB;
  const prices=ohlc.flatMap(c=>[c.h,c.l]);
  const minP=Math.min(...prices),maxP=Math.max(...prices);
  const rng=maxP-minP||1;
  const xStep=chartW/(ohlc.length-1||1);
  function px(p){return padT+chartH-(p-minP)/rng*chartH;}
  function py(i){return padL+i*xStep;}
  const candleW=Math.max(1,xStep*0.65);

  const ctx=canvas.getContext('2d');
  const dpr=window.devicePixelRatio||1;
  canvas.width=W*dpr;canvas.height=H*dpr;
  canvas.style.width=W+'px';canvas.style.height=H+'px';
  ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,W,H);

  // Grid
  ctx.strokeStyle='rgba(255,255,255,0.06)';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){
    const y=padT+i*chartH/4;
    ctx.beginPath();ctx.moveTo(padL,y);ctx.lineTo(padL+chartW,y);ctx.stroke();
    const p=minP+rng*(1-i/4);
    ctx.fillStyle='rgba(255,255,255,0.3)';ctx.font='10px monospace';ctx.textAlign='right';
    ctx.fillText('₹'+p.toFixed(0),padL-4,y+3);
  }
  ctx.fillStyle='rgba(255,255,255,0.3)';ctx.font='10px monospace';ctx.textAlign='left';
  ctx.fillText('₹'+maxP.toFixed(0),padL+chartW+4,padT+10);
  ctx.fillText('₹'+minP.toFixed(0),padL+chartW+4,padT+chartH);

  if(chartType==='line'){
    // Line chart — single polyline of closes
    ctx.beginPath();
    ohlc.forEach((c,i)=>{
      const y=px(c.c);
      i===0?ctx.moveTo(py(i),y):ctx.lineTo(py(i),y);
    });
    ctx.strokeStyle='#00c896';ctx.lineWidth=1.5;ctx.stroke();
    // Filled area below line
    ctx.lineTo(py(ohlc.length-1),padT+chartH);
    ctx.lineTo(py(0),padT+chartH);
    ctx.closePath();
    ctx.fillStyle='rgba(0,200,150,0.08)';ctx.fill();
  } else {
    // Candlestick chart
    ohlc.forEach((c,i)=>{
      const cx=py(i);
      const bodyTop=px(Math.max(c.o,c.c)),bodyBot=px(Math.min(c.o,c.c));
      const isGreen=c.c>=c.o;
      const col=isGreen?'#00c896':'#ff4d6a';
      const bodyH=Math.max(1,bodyBot-bodyTop);
      ctx.strokeStyle=col;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(cx,px(c.h));ctx.lineTo(cx,px(c.l));ctx.stroke();
      ctx.fillStyle=col;
      ctx.fillRect(cx-candleW/2,bodyTop,candleW,bodyH);
    });
  }

  // Last price label
  const lastP=ohlc[ohlc.length-1]?.c||0;
  const lastY=px(lastP);
  ctx.strokeStyle='rgba(255,200,0,0.4)';ctx.lineWidth=1;ctx.setLineDash([4,4]);
  ctx.beginPath();ctx.moveTo(padL,lastY);ctx.lineTo(padL+chartW,lastY);ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle='rgba(255,200,0,0.9)';ctx.font='bold 10px monospace';ctx.textAlign='left';
  ctx.fillText('₹'+lastP.toFixed(2),padL+chartW+4,lastY+3);

  // Interval label bottom-right
  const label=interval==='1d'?'Daily':interval==='60m'?'1 Hour':interval==='15m'?'15 Min':'5 Min';
  ctx.fillStyle='rgba(255,255,255,0.25)';ctx.font='10px monospace';ctx.textAlign='right';
  ctx.fillText(label,padL+chartW,padT+chartH+14);
}

function _startChartRefresh(){
  // Auto-refresh the current interval's candles every 30 seconds
  if(window._chartTimer){ clearInterval(window._chartTimer); }
  window._chartTimer = setInterval(()=>{
    if(!document.getElementById('chartModal')){
      clearInterval(window._chartTimer); window._chartTimer=null;
      return;
    }
    const cfg=window._chartCfg;
    if(!cfg.inst) return;
    const rangeMap={'1d':'60d','60m':'5d','15m':'5d'};
    const range=rangeMap[cfg.interval]||'60d';
    console.log('[Chart] Auto-refresh: '+cfg.symbol+' '+cfg.interval);
    ws.send(JSON.stringify({command:'get_candles',instrument:cfg.inst,symbol:cfg.symbol,interval:cfg.interval,range:range}));
  },1000);
}

function closeChartModal(){
  const modal=document.getElementById('chartModal');
  if(modal){ modal.remove(); }
  if(window._chartTimer){ clearInterval(window._chartTimer); window._chartTimer=null; }
  // Destroy Lightweight Charts instance to free memory
  try { if(window._lcChart){ window._lcChart.remove(); window._lcChart=null; window._lcSeries=null; } } catch(e){}
}

function renderTlChart(inst, symbol, candles, interval, range){
  // ── Render mutex: block concurrent executions ──────────────────────────────
  // This is the single most important fix. Without it, the 1-second auto-refresh
  // timer can fire while renderTlChart is still running (e.g. between chart creation
  // and setData), leaving LC's internal state in a half-initialized state that
  // throws "Value is undefined" from inside the time-scale updater.
  if (window._chartRendering) return;
  window._chartRendering = true;
  try {

  interval = interval || window._chartCfg?.interval || '1d';
  range = range || window._chartCfg?.range || '60d';
  const chartType = window._chartCfg?.chartType || 'candle';

  // Update cache
  window._chartCache[interval] = { candles, interval, range };

  // Only create the modal shell once — subsequent calls update content without rebuilding
  let modal = document.getElementById('chartModal');
  const isFirstOpen = !modal;

  if (isFirstOpen) {
    modal = document.createElement('div');
    modal.id = 'chartModal';
    modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center';
    modal.onclick = function(e) { if (e.target === modal) closeChartModal(); };
    document.body.appendChild(modal);
  }

  if (!candles || !candles.length) {
    if (isFirstOpen) {
      modal.innerHTML = `<div style="background:var(--bg-card);border-radius:12px;padding:30px;text-align:center;max-width:380px">
        <div style="font-size:18px;margin-bottom:10px">📊 ${symbol}</div>
        <div style="color:var(--text-muted)">Loading candles...</div>
        <button onclick="closeChartModal()" style="margin-top:16px;padding:8px 20px;background:var(--bg-card2);border:1px solid var(--border);color:var(--text-primary);border-radius:8px;cursor:pointer">Close</button>
      </div>`;
    }
    window._chartRendering = false;
    return;
  }

  // ─── normalizeTime: convert any timestamp to Unix seconds for LC v4 ───
  // Accepts: number (seconds or ms), ISO string, or BusinessDay {year,month,day}
  // Returns: Unix seconds (integer), or null if invalid
  function normalizeTime(val) {
    if (val === null || val === undefined) return null;
    // Already a number → treat as Unix seconds (if < 10B) or ms (if ≥ 10B)
    if (typeof val === 'number' && Number.isFinite(val)) {
      return val < 1e10 ? Math.floor(val) : Math.floor(val / 1000);
    }
    // ISO string like "2024-01-15" or "2024-01-15T00:00:00"
    if (typeof val === 'string' && val.length >= 10) {
      const d = new Date(val.slice(0, 10) + 'T00:00:00Z');
      return isNaN(d.getTime()) ? null : Math.floor(d.getTime() / 1000);
    }
    // BusinessDay object {year,month,day} (LC v4 native format)
    if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
      const { year, month, day } = val;
      if (Number.isFinite(year) && Number.isFinite(month) && Number.isFinite(day)) {
        const d = new Date(Date.UTC(year, month - 1, day));
        return isNaN(d.getTime()) ? null : Math.floor(d.getTime() / 1000);
      }
    }
    return null;
  }

  // Early exit if chart is not yet ready (guards against auto-refresh firing before first render)
  if (!isFirstOpen && (!window._lcChart || !window._lcSeries)) {
    console.warn('[Chart] Chart not ready, skipping data update');
    window._chartRendering = false;
    return;
  }

  // Parse and filter out candles with missing/invalid price data or timestamps
  const ohlc = candles
    .map(c => {
      const rawT = c[0];
      const normT = normalizeTime(rawT);
      return {
        t: normT,                                    // Unix seconds for LC v4
        rawT: rawT,                                 // keep original for debug
        o: parseFloat(c[1]), h: parseFloat(c[2]),
        l: parseFloat(c[3]), c: parseFloat(c[4]),
      };
    })
    .filter(d =>
      d.t !== null &&
      Number.isFinite(d.t) &&
      Number.isFinite(d.o) && Number.isFinite(d.h) &&
      Number.isFinite(d.l) && Number.isFinite(d.c)
    );

  if (!ohlc.length) {
    console.warn('[Chart] No valid candles after normalization for', symbol, '| raw sample:', JSON.stringify(candles?.[0]));
    window._chartRendering = false;
    return;
  }

  // Debug: log first candle raw vs normalized
  console.log('[Chart] Candles OK:', symbol, '| raw[0]:', JSON.stringify(candles[0]), '| norm t:', ohlc[0]?.t, '| count:', ohlc.length);

  // ─── Sanitize data for Lightweight Charts ───
  // Ensures every item has integer time + finite numeric prices; drops anything LC would reject
  function sanitizeLC(items) {
    return items.map(d => ({
      time: Math.floor(d.t),   // LC v4 requires integer Unix seconds
      open:   +d.o.toFixed(2),
      high:   +d.h.toFixed(2),
      low:    +d.l.toFixed(2),
      close:  +d.c.toFixed(2),
    })).filter(d =>
      d.time > 0 &&
      isFinite(d.open) && isFinite(d.high) &&
      isFinite(d.low)  && isFinite(d.close)
    );
  }
  const lcData = sanitizeLC(ohlc);
  if (!lcData.length) {
    console.warn('[Chart] sanitizeLC dropped all candles for', symbol);
    return;
  }

  const firstTs = ohlc[0].t;
  const lastTs = ohlc[ohlc.length - 1].t;
  const tfLabel = interval === '1d' ? 'Daily' : interval === '60m' ? '1 Hour' : interval === '15m' ? '15 Min' : '5 Min';

  if (isFirstOpen) {
    // Build full modal shell using DOM
    const shell = document.createElement('div');
    shell.style.cssText = 'background:var(--bg-card);border-radius:12px;padding:16px;max-width:740px;width:95vw;user-select:none';
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px;flex-wrap:wrap';
    const titleDiv = document.createElement('div');
    titleDiv.style.cssText = 'font-size:16px;font-weight:700;color:var(--text-primary)';
    titleDiv.innerHTML = '<span style="font-size:18px;margin-right:6px">&#x1F4CA;</span> ' + symbol;
    const labelSpan = document.createElement('span');
    labelSpan.id = 'tlTfLabel';
    labelSpan.style.cssText = 'font-size:12px;font-weight:400;color:var(--green);margin-left:4px';
    labelSpan.textContent = tfLabel;
    titleDiv.appendChild(labelSpan);
    const liveSpan = document.createElement('span');
    liveSpan.style.cssText = 'font-size:11px;color:var(--green);font-weight:400;margin-left:6px';
    liveSpan.textContent = '\u25CF LIVE';
    titleDiv.appendChild(liveSpan);
    hdr.appendChild(titleDiv);
    const tfDiv = document.createElement('div');
    tfDiv.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap';
    ['1d', '60m', '15m'].forEach(tf => {
      const btn = document.createElement('button');
      const isActive = tf === interval;
      btn.className = 'tl-tf-btn' + (isActive ? ' tl-tf-active' : '');
      btn.dataset.tf = tf;
      btn.style.cssText = 'padding:4px 10px;font-size:11px;border-radius:6px;border:1px solid;cursor:pointer;font-weight:600;background:' + (isActive ? 'var(--accent)' : 'var(--bg-card2)') + ';color:' + (isActive ? '#fff' : 'var(--text-muted)') + ';border-color:' + (isActive ? 'var(--accent)' : 'var(--border)');
      btn.textContent = tf === '1d' ? '1D' : tf === '60m' ? '1H' : '15m';
      tfDiv.appendChild(btn);
    });
    const div2 = document.createElement('div');
    div2.style.cssText = 'width:1px;height:20px;background:var(--border)';
    tfDiv.appendChild(div2);
    ['candle', 'line'].forEach(ct => {
      const btn = document.createElement('button');
      const isActive = ct === chartType;
      btn.className = 'tl-ct-btn' + (isActive ? ' tl-ct-active' : '');
      btn.dataset.ct = ct;
      btn.style.cssText = 'padding:4px 10px;font-size:11px;border-radius:6px;border:1px solid;cursor:pointer;font-weight:600;color:' + (isActive ? '#fff' : 'var(--text-muted)') + ';background:' + (isActive ? 'var(--accent)' : 'var(--bg-card2)') + ';border-color:' + (isActive ? 'var(--accent)' : 'var(--border)');
      btn.textContent = ct === 'candle' ? 'Candle' : 'Line';
      tfDiv.appendChild(btn);
    });
    hdr.appendChild(tfDiv);
    shell.appendChild(hdr);

    // Canvas container for Lightweight Charts
    const chartContainer = document.createElement('div');
    chartContainer.id = 'tlChartContainer';
    chartContainer.style.cssText = 'width:100%;height:340px;border-radius:8px;overflow:hidden;background:var(--bg-card2)';
    shell.appendChild(chartContainer);

    const stats = document.createElement('div');
    stats.id = 'tlChartStats';
    stats.style.cssText = 'margin-top:8px;display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted)';
    stats.innerHTML = '<span>' + new Date(firstTs * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) + '</span><span style="color:var(--green)">Auto-refreshes every 1s</span><span>' + ohlc.length + ' bars</span><span>' + new Date(lastTs * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) + '</span>';
    shell.appendChild(stats);

    const closeBtn = document.createElement('button');
    closeBtn.onclick = closeChartModal;
    closeBtn.style.cssText = 'margin-top:10px;width:100%;padding:8px;background:var(--bg-card2);border:1px solid var(--border);color:var(--text-primary);border-radius:8px;cursor:pointer;font-size:13px';
    closeBtn.textContent = 'Close';
    shell.appendChild(closeBtn);
    modal.innerHTML = '';
    modal.appendChild(shell);

    // ─── Initialize Lightweight Charts ───
    // Destroy any previous instance first to avoid stale state
    if (window._lcChart) {
      try { window._lcChart.remove(); } catch(e) {}
      window._lcChart = null;
      window._lcSeries = null;
    }

    try {
      const container = document.getElementById('tlChartContainer');
      // Force a reflow so container has pixel dimensions before LC reads them
      void container.offsetWidth;

      window._lcChart = LightweightCharts.createChart(container, {
        width: container.clientWidth || 700,
        height: 340,
        layout: { background: { color: 'transparent' }, textColor: '#9ca3af' },
        grid: { vertLines: { color: '#1f2937' }, horzLines: { color: '#1f2937' } },
        crosshair: { mode: 1 },
        rightPriceScale: { borderColor: '#374151' },
        timeScale: { borderColor: '#374151', timeVisible: true },
      });

      if (chartType === 'line') {
        window._lcSeries = window._lcChart.addLineSeries({ color: '#22c55e', lineWidth: 2 });
        window._lcSeries.setData(lcData.map(d => ({ time: d.time, value: d.close })));
      } else {
        window._lcSeries = window._lcChart.addCandlestickSeries({
          upColor: '#22c55e', downColor: '#ef4444',
          borderUpColor: '#22c55e', borderDownColor: '#ef4444',
          wickUpColor: '#22c55e', wickDownColor: '#ef4444',
        });
        window._lcSeries.setData(lcData);
      }

      // Defer fitContent by one animation frame so LC's layout engine settles first.
      // Calling it synchronously can trigger a time-scale recalc on an incomplete series.
      requestAnimationFrame(() => {
        if (window._lcChart) {
          try { window._lcChart.timeScale().fitContent(); } catch(e) {}
        }
      });
    } catch (e) {
      console.error('[Chart] Lightweight Charts init error:', e);
      window._lcChart = null;
      window._lcSeries = null;
    }

    // Timeframe pill clicks
    modal.querySelectorAll('.tl-tf-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tf = btn.dataset.tf;
        if (tf === window._chartCfg?.interval) return;
        if (window._chartCfg) {
          window._chartCfg.interval = tf;
          const cached = window._chartCache[tf];
          if (cached) {
            renderTlChart(window._chartCfg.inst, window._chartCfg.symbol, cached.candles, cached.interval, cached.range);
          } else {
            const rangeMap = { '1d': '60d', '60m': '5d', '15m': '5d' };
            ws.send(JSON.stringify({ command: 'get_candles', instrument: window._chartCfg.inst, symbol: window._chartCfg.symbol, interval: tf, range: rangeMap[tf] || '60d' }));
            showToast('\uD83D\uDCCA Fetching ' + tf + ' candles...', 'var(--blue)');
          }
        }
      });
    });

    // Chart type pill clicks
    modal.querySelectorAll('.tl-ct-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const ct = btn.dataset.ct;
        if (window._chartCfg) {
          window._chartCfg.chartType = ct;
          const cached = window._chartCache[window._chartCfg.interval];
          if (cached) {
            renderTlChart(window._chartCfg.inst, window._chartCfg.symbol, cached.candles, cached.interval, cached.range);
          }
        }
      });
    });

    _startChartRefresh();
  } else {
    // ─── Subsequent calls: update data or switch chart type ───
    if (!window._lcChart || !window._lcSeries) return; // Chart not ready yet

    const prevType = window._lcChartType || 'candle';
    if (prevType !== chartType) {
      // Chart type changed — destroy entire chart and rebuild to avoid
      // removeSeries() triggering an async time-scale recalc on a half-ready series.
      // Cache current data so the rebuild uses the same candles.
      const snapInterval = window._chartCfg?.interval || interval;
      window._chartCache[snapInterval] = { candles, interval, range };
      window._chartCfg.chartType = chartType;
      // Recreate from scratch (isFirstOpen=true path handles everything)
      window._lcChart = null;
      window._lcSeries = null;
      renderTlChart(inst, symbol, candles, interval, range);
      return;
    } else {
      // Same chart type — just update data on the existing series
      try {
        window._lcSeries.setData(chartType === 'line'
          ? lcData.map(d => ({ time: d.time, value: d.close }))
          : lcData
        );
      } catch(e) {
        console.error('[Chart] setData update error:', e);
        // Fallback: destroy chart and rebuild from current candles
        window._lcChart = null;
        window._lcSeries = null;
        renderTlChart(inst, symbol, candles, interval, range);
      }
    }

    // Update stats bar
    const stats = document.getElementById('tlChartStats');
    if (stats) {
      stats.innerHTML = '<span>' + new Date(firstTs * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) + '</span><span style="color:var(--green)">Auto-refreshes every 1s</span><span>' + ohlc.length + ' bars</span><span>' + new Date(lastTs * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) + '</span>';
    }
  }
  } finally {
    window._chartRendering = false;
  }
}

/* ════════════════════════════════════════
   ALERT SOUNDS
════════════════════════════════════════ */
let _audioCtx=null;
function _getAudioCtx(){
  if(!_audioCtx)_audioCtx=new(window.AudioContext||window.webkitAudioContext)();
  return _audioCtx;
}
function playTone(freq,dur,type='sine'){
  try{
    const ctx=_getAudioCtx();
    const osc=ctx.createOscillator();
    const gain=ctx.createGain();
    osc.connect(gain);gain.connect(ctx.destination);
    osc.type=type;osc.frequency.value=freq;
    gain.gain.setValueAtTime(0.3,ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+dur);
    osc.start();osc.stop(ctx.currentTime+dur);
  }catch(e){}
}
function playBuyAlert(){playTone(880,0.15);setTimeout(()=>playTone(1100,0.2),180);}
function playSellAlert(){playTone(440,0.2);setTimeout(()=>playTone(330,0.25),250);}
function playSignalAlert(type){
  if(type==='BUY')playBuyAlert();
  else if(type==='SELL')playSellAlert();
  else{playTone(660,0.1);setTimeout(()=>playTone(660,0.1),130);}
}
function updateSignals(signals, prevCount=0){
  const sb=document.getElementById('signalsBody');
  if(!sb)return;
  if(!signals.length){sb.innerHTML='<tr><td colspan="6" class="empty-state">No signals yet...</td></tr>';return;}

  // Play alert sound for NEW signals only
  if(signals.length>prevCount){
    const latest=signals[signals.length-1];
    if(latest?.type)playSignalAlert(latest.type);
  }

  sb.innerHTML=signals.slice(-10).reverse().map((s,i)=>{
    const cls=s.type==='BUY'?'badge-green':s.type==='SELL'?'badge-red':'badge-gold';
    return`<tr>
      <td>${signals.length-i}</td>
      <td>${(s.time||'').split('T')[1]?.substring(0,5)||'—'}</td>
      <td>${s.strategy_name||'SAR'}</td>
      <td>${s.instrument||'—'}</td>
      <td><span class="${cls}">${s.type||'—'}</span></td>
      <td>₹${(s.price||0).toLocaleString('en-IN',{minimumFractionDigits:2})}</td>
    </tr>`;
  }).join('');
}

/* ════════════════════════════════════════
   STRATEGY HELPERS
════════════════════════════════════════ */
function toggleSeg(id){
  const el=document.getElementById('seg'+id);
  if(el) el.classList.toggle('open');
}
function toggleSys(id){
  const el=document.getElementById('sys'+id);
  if(el) el.classList.toggle('open');
}
function toggleSector(sectorId){
  const el=document.getElementById('sec_'+sectorId);
  if(el) el.classList.toggle('open');
}

/* ════════════════════════════════════════
   QUOTE LOOKUP
════════════════════════════════════════ */
function _inferSegment(inst){
  const u=inst.toUpperCase();
  if(/(CE|PE)\d+$/.test(u))return'OPTIONS'; // NIFTYCE35000, RELIANCEPE2500
  if(u.endsWith('FUT'))return'STOCK_FUTURES';
  if(/\b(SEP|OCT|NOV|DEC|JAN|AUG|JUL)(26|27)\b/.test(u))return'STOCK_FUTURES';
  if(/^(NIFTY|BANKNIFTY|FINNIFTY|SENSEX|MIDCPNIFTY)/.test(u))return'INDEX_FUTURES';
  if(/^(GOLD|SILVER|CRUDEOIL|NATURALGAS)/.test(u))return'COMMODITY_FUTURES';
  return'CASH';
}
function _inferSector(stock){
  // Map stock base symbol to sector code (uppercase+underscore, matches engine _infer_sector)
  // Use same stripping logic as getBaseSymbol to handle all contract formats
  const s=getBaseSymbol(stock).toUpperCase();
  // Index / commodity futures
  if(/^(NIFTY|BANKNIFTY|FINNIFTY|SENSEX|MIDCPNIFTY)$/.test(s))return'INDEX_FUTURES';
  if(/^(GOLD|SILVER|CRUDEOIL|NATURALGAS)$/.test(s))return'COMMODITY_FUTURES';
  const map={
    'CANBK':'PSU_BANK','SBIN':'PSU_BANK','SBI':'PSU_BANK','BANK OF BARODA':'PSU_BANK','UNIONBANK':'PSU_BANK',
    'PNB':'PSU_BANK','CENTRALBK':'PSU_BANK','INDIANB':'PSU_BANK','UCOBANK':'PSU_BANK',
    'HDFCBANK':'PVT_BANK','ICICIBANK':'PVT_BANK','KOTAKBANK':'PVT_BANK','INDUSINDBK':'PVT_BANK',
    'AXISBANK':'PVT_BANK','IDFCFIRSTB':'PVT_BANK','BANDHANBNK':'PVT_BANK','RBLBANK':'PVT_BANK',
    'MARUTI':'AUTO','M&M':'AUTO','TATAMOTORS':'AUTO','BAJAJ-AUTO':'AUTO','HEROMOTOCO':'AUTO',
    'EICHERMOT':'AUTO','TVSMOTOR':'AUTO','ASHOKLEY':'AUTO','BALKRISIND':'AUTO',
    'RELIANCE':'ENERGY','ONGC':'ENERGY','BPCL':'ENERGY','IOC':'ENERGY','HPCL':'ENERGY','GAIL':'ENERGY',
    'HINDUNILVR':'FMCG','NESTLE':'FMCG','DABUR':'FMCG','COLPAL':'FMCG','BRITANNIA':'FMCG','MARICO':'FMCG',
    'TITAN':'CONSUMER','HAVELLS':'CONSUMER','VOLTAS':'CONSUMER','CROMPTON':'CONSUMER',
    'BAJFINANCE':'FINANCIAL_SERVICES','BAJ FINSERV':'FINANCIAL_SERVICES','MUTHOOTFIN':'FINANCIAL_SERVICES',
    'INFY':'IT','TCS':'IT','HCLTECH':'IT','WIPRO':'IT','TECHM':'IT','LTIM':'IT','COFORGE':'IT',
    'TATASTEEL':'METAL','JSWSTEEL':'METAL','HINDALCO':'METAL','JSPL':'METAL','NMDC':'METAL','SAIL':'METAL',
    'SUNPHARMA':'PHARMA','CIPLA':'PHARMA','DRREDDY':'PHARMA','APOLLOPHARMA':'PHARMA','ZYDUSLIFE':'PHARMA',
    'NTPC':'PSE','POWERGRID':'PSE','COALINDIA':'PSE','BEL':'DEFENCE','HAL':'DEFENCE','BEML':'DEFENCE',
    'DLF':'REALTY','GODREJPROP':'REALTY',
    'ADANI PORTS':'INFRASTRUCTURE','ADANIPORTS':'INFRASTRUCTURE',
    'DELHIVERY':'INFRASTRUCTURE','CONCOR':'INFRASTRUCTURE',
    'ADANIENT':'MISC','ADANIGREEN':'MISC',
  };
  return map[s]||'OTHER';
}
function getQuote(inst){
  const q=window._quotes||{};
  // Try direct key
  if(q[inst]) return q[inst];
  // Try .NS suffix
  if(q[inst+'.NS']) return q[inst+'.NS'];
  // Try NSE: prefix
  if(q['NSE:'+inst]) return q['NSE:'+inst];
  return null;
}
function getLtpDisplay(inst){
  const q=getQuote(inst);
  if(!q) return {price:'—',change:'—',cls:''};
  const price=q.last_price||q.price||0;
  const chg=q.change||0;
  const pct=q.change_pct||0;
  const cls=chg>=0?'up':'dn';
  return {
    price: '₹'+price.toLocaleString('en-IN',{minimumFractionDigits:2}),
    change: `${chg>=0?'+':''}${pct.toFixed(2)}%`,
    cls
  };
}

/* ════════════════════════════════════════
   FUTURES STRATEGY DROPDOWN
════════════════════════════════════════ */
let _futStratKey = 'SAR_TOP_BOTTOM';  // Default selected futures strategy

function selectFutStrat(stratKey){
  _futStratKey = stratKey;
  // Update UI: highlight selected, dim others
  ['SAR','Other'].forEach(suffix => {
    const el = document.getElementById('futStrat'+suffix);
    if(!el) return;
    const isActive = suffix === 'SAR' && stratKey === 'SAR_TOP_BOTTOM'
                  || suffix === 'Other' && stratKey === 'OTHER';
    el.classList.toggle('active', isActive);
    el.querySelector('.strat-opt-radio').textContent = isActive ? '●' : '○';
  });
}

function applyFuturesStrategy(){
  // Get all checked futures instruments from watchlist
  const instruments = WATCHLISTS.FUTURE.map(x => x.inst);
  if(!instruments.length){
    showToast('No futures instruments in watchlist to apply strategy','var(--orange)');
    return;
  }
  const stratKey = 'FUTURE-' + _futStratKey;  // e.g. "FUTURE-SAR_TOP_BOTTOM"
  if(ws && ws.readyState === WebSocket.OPEN){
    ws.send(JSON.stringify({
      command: 'apply_strategy',
      strategy: _futStratKey,
      strategyName: _futStratKey === 'SAR_TOP_BOTTOM' ? 'SAR Top-Bottom' : 'Other',
      instruments: instruments,
      direction: 'LONGSHORT',
      pyramiding: 'ADD',
      lotSize: 30,
      capital: 100000,
      category: 'Future',
    }));
    showToast(`Applying SAR Top-Bottom to ${instruments.length} futures...`, 'var(--green)');
  } else {
    showToast('Engine not connected','var(--red)');
  }
}

/* ════════════════════════════════════════
   CASH STRATEGY DROPDOWN
════════════════════════════════════════ */
let _cashStratKey = 'RSI';  // Default selected cash strategy (RSI Reversal)

function selectCashStrat(stratKey){
  _cashStratKey = stratKey;
  // Map stratKey to the option element id
  const idMap = { RSI: 'cashStratRSI' };
  Object.entries(idMap).forEach(([key, elId]) => {
    const el = document.getElementById(elId);
    if(!el) return;
    const isActive = (key === stratKey);
    el.classList.toggle('active', isActive);
    el.querySelector('.strat-opt-radio').textContent = isActive ? '●' : '○';
  });
}

function applyCashStrategy(){
  // Get all cash instruments from watchlist
  const instruments = WATCHLISTS.CASH.map(x => x.inst);
  if(!instruments.length){
    showToast('No cash instruments in watchlist to apply strategy','var(--orange)');
    return;
  }
  const stratKey = 'CASH-' + _cashStratKey;  // e.g. "CASH-RSI"
  const stratLabel = 'RSI Reversal';
  if(ws && ws.readyState === WebSocket.OPEN){
    ws.send(JSON.stringify({
      command: 'apply_strategy',
      strategy: stratKey,
      strategyName: stratLabel,
      instruments: instruments,
      direction: 'LONGSHORT',
      pyramiding: 'ADD',
      lotSize: 30,
      capital: 100000,
      category: 'Cash',
    }));
    showToast(`Applying ${stratLabel} to ${instruments.length} cash stocks...`, 'var(--green)');
  } else {
    showToast('Engine not connected','var(--red)');
  }
}

/* ════════════════════════════════════════
   RENDER STRATEGY CHIPS
════════════════════════════════════════ */
function renderChip(inst,sysId,category){
  const isChecked=!!selectedInstruments[inst];
  const ltp=getLtpDisplay(inst);
  return `<label class="stock-chip ${isChecked?'checked':''}" id="chip_${inst.replace(/[^a-zA-Z0-9]/g,'_')}_${sysId}">
    <input type="checkbox" onchange="onChipToggle('${inst}','${sysId}','${category}',this.checked)" ${isChecked?'checked':''}>
    <span>${inst}</span>
    <span class="chip-ltp">${ltp.price}</span>
    <span class="chip-rm" onclick="event.stopPropagation();onChipRm('${inst}','${sysId}','${category}')">✕</span>
  </label>`;
}

function renderSystemStocks(sysId,category){
  const container=document.getElementById('stocks'+sysId);
  if(!container)return;
  const stocks=STRAT_STOCKS[sysId]||[];
  if(!stocks.length){
    container.innerHTML='<div class="no-stocks">No stocks — click "+ Add Stock" to add</div>';
    updateSysCount(sysId,category); return;
  }
  container.innerHTML=stocks.map(stock=>renderChip(stock,sysId,category)).join('');
  updateSysCount(sysId,category);
}

function renderSectorStocks(sectorKey){
  const container=document.getElementById('secStocks_'+sectorKey);
  if(!container)return;
  const stocks=STRAT_STOCKS['SEC_'+sectorKey]||[];
  if(!stocks.length){ container.innerHTML='<div class="no-stocks">No stocks</div>'; updateSectorCount(sectorKey); return; }
  container.innerHTML=stocks.map(stock=>renderChip(stock,'SEC_'+sectorKey,'FUTURE')).join('');
  updateSectorCount(sectorKey);
}

/* ════════════════════════════════════════
   CHIP TOGGLE
════════════════════════════════════════ */
function onChipToggle(inst,sysId,category,checked){
  if(checked){
    selectedInstruments[inst]=sysId;
    // Add to watchlist if not already there
    if(!WATCHLISTS[category].find(x=>x.inst===inst)){
      WATCHLISTS[category].push({ inst, sysId, entryPrice:'', sl:'', mode:'PAPER' });
    }
  } else {
    delete selectedInstruments[inst];
    // Remove from watchlist
    const idx=WATCHLISTS[category].findIndex(x=>x.inst===inst);
    if(idx!==-1) WATCHLISTS[category].splice(idx,1);
  }
  const chip=document.getElementById('chip_'+inst.replace(/[^a-zA-Z0-9]/g,'_')+'_'+sysId);
  if(chip) chip.classList.toggle('checked',checked);
  updateSysCount(sysId,category);
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
}

function onChipRm(inst,sysId,category){
  const chip=document.getElementById('chip_'+inst.replace(/[^a-zA-Z0-9]/g,'_')+'_'+sysId);
  if(chip){ chip.querySelector('input').checked=false; chip.classList.remove('checked'); }
  delete selectedInstruments[inst];
  const idx=WATCHLISTS[category].findIndex(x=>x.inst===inst);
  if(idx!==-1) WATCHLISTS[category].splice(idx,1);
  updateSysCount(sysId,category);
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
}

function refreshAllChips(){
  Object.keys(CASH_SYSTEMS).forEach(k=>renderSystemStocks(k,'CASH'));
  Object.keys(FUTURE_SYSTEMS).forEach(k=>renderSystemStocks(k,'FUTURE'));
  Object.keys(FUT_SECTORS).forEach(k=>renderSectorStocks(k));
}

function updateSysCount(sysId,category){
  const cntEl=document.getElementById('cnt'+sysId);
  if(cntEl){
    const total=(STRAT_STOCKS[sysId]||[]).length;
    const checked=Object.values(selectedInstruments).filter(v=>v===sysId).length;
    cntEl.textContent=`${checked}/${total} stocks`;
  }
  if(category==='CASH') updateSegCount('CASH');
  else if(category==='FUTURE') updateSegCount('FUTURE');
}
function updateSectorCount(sectorKey){
  const cntEl=document.getElementById('secCnt_'+sectorKey);
  if(cntEl){
    const total=(STRAT_STOCKS['SEC_'+sectorKey]||[]).length;
    const checked=Object.keys(selectedInstruments).filter(k=>selectedInstruments[k]==='SEC_'+sectorKey).length;
    cntEl.textContent=`${checked}/${total}`;
  }
  updateSegCount('FUTURE');
}
function updateSegCount(seg){
  const cntEl=document.getElementById('cnt'+seg);
  if(cntEl) cntEl.textContent=WATCHLISTS[seg].length+' in watchlist';
}

/* ════════════════════════════════════════
   ADD/REMOVE STOCKS
════════════════════════════════════════ */
function addStockPrompt(sysId){
  const category=CASH_SYSTEMS[sysId]?.category||FUTURE_SYSTEMS[sysId]?.category||'CASH';
  const label=CASH_SYSTEMS[sysId]?.label||FUTURE_SYSTEMS[sysId]?.label||sysId;
  const stock=prompt(`Add stock to ${label}:\n\nEnter stock name (e.g. RELIANCE):`);
  if(!stock)return;
  const s=stock.trim().toUpperCase();
  if(!s)return;
  if(!STRAT_STOCKS[sysId])STRAT_STOCKS[sysId]=[];
  if(STRAT_STOCKS[sysId].includes(s)){ showToast(`${s} already exists`,'var(--orange)'); return; }
  STRAT_STOCKS[sysId].push(s);
  saveStratStocks();
  selectedInstruments[s]=sysId;
  if(!WATCHLISTS[category].find(x=>x.inst===s)){
    WATCHLISTS[category].push({ inst:s, sysId, entryPrice:'', sl:'', mode:'PAPER' });
  }
  renderSystemStocks(sysId,category);
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
  showToast(`Added ${s} to ${label}`,'var(--green)');
}

function removeStockPrompt(sysId){
  const category=CASH_SYSTEMS[sysId]?.category||FUTURE_SYSTEMS[sysId]?.category||'CASH';
  const label=CASH_SYSTEMS[sysId]?.label||FUTURE_SYSTEMS[sysId]?.label||sysId;
  const stocks=STRAT_STOCKS[sysId]||[];
  if(!stocks.length){showToast('No stocks to remove','var(--orange)');return;}
  const list=stocks.map((s,i)=>`${i+1}. ${s}`).join('\n');
  const stock=prompt(`Remove stock from ${label}:\n\nCurrent: ${list}\n\nType the stock name to remove:`);
  if(!stock)return;
  const s=stock.trim().toUpperCase();
  const idx=stocks.indexOf(s);
  if(idx===-1){showToast(`${s} not found`,'var(--red)');return;}
  STRAT_STOCKS[sysId].splice(idx,1);
  saveStratStocks();
  if(selectedInstruments[s]===sysId){
    delete selectedInstruments[s];
    const wi=WATCHLISTS[category].findIndex(x=>x.inst===s);
    if(wi!==-1)WATCHLISTS[category].splice(wi,1);
  }
  renderSystemStocks(sysId,category);
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
  showToast(`Removed ${s} from ${label}`,'var(--red)');
}

/* ════════════════════════════════════════
   SYSTEM CHECKBOX
════════════════════════════════════════ */
function onSysCheckChange(sysId){
  const cb=document.getElementById('cb'+sysId);
  if(!cb)return;
  const category=CASH_SYSTEMS[sysId]?.category||FUTURE_SYSTEMS[sysId]?.category||'CASH';
  const stocks=STRAT_STOCKS[sysId]||[];
  if(cb.checked){
    stocks.forEach(stock=>{
      selectedInstruments[stock]=sysId;
      if(!WATCHLISTS[category].find(x=>x.inst===stock)){
        WATCHLISTS[category].push({ inst:stock, sysId, entryPrice:'', sl:'', mode:'PAPER' });
      }
    });
  } else {
    stocks.forEach(stock=>{
      delete selectedInstruments[stock];
      const wi=WATCHLISTS[category].findIndex(x=>x.inst===stock);
      if(wi!==-1)WATCHLISTS[category].splice(wi,1);
    });
  }
  renderSystemStocks(sysId,category);
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
}

/* ════════════════════════════════════════
   CUSTOM INSTRUMENT
════════════════════════════════════════ */
function addCustomInstrument(){
  const input=document.getElementById('stratCustomInput');
  const seg=document.getElementById('stratCustomSeg');
  if(!input)return;
  const val=input.value.trim().toUpperCase();
  if(!val)return;
  const category=seg?.value||'CASH';
  if(!WATCHLISTS[category].find(x=>x.inst===val)){
    WATCHLISTS[category].push({ inst:val, sysId:category, entryPrice:'', sl:'', mode:'PAPER' });
  }
  selectedInstruments[val]=category;
  input.value='';
  updateSegCount(category);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
  showToast(`Added ${val} to ${category} watchlist`,'var(--green)');
}

/* ════════════════════════════════════════
   WATCHLIST TABS
════════════════════════════════════════ */
function switchWlTab(tab){
  activeWlTab=tab;
  ['CASH','FUTURE','OPTION'].forEach(t=>{
    const tabEl=document.getElementById('wlTab'+t);
    const panelEl=document.getElementById('wlPanel'+t);
    if(tabEl)tabEl.classList.toggle('active',t===tab);
    if(panelEl)panelEl.classList.toggle('active',t===tab);
  });
}

/* ════════════════════════════════════════
   RENDER WATCHLIST TABLE
════════════════════════════════════════ */
function renderAllWatchlists(){
  // CASH segment has no strategy — always keep it empty (defense against browser JS cache)
  WATCHLISTS['CASH'] = [];
  renderWatchlistTable('CASH');
  renderWatchlistTable('FUTURE');
  renderWatchlistTable('OPTION');
  // Update tab counts
  ['CASH','FUTURE','OPTION'].forEach(tab=>{
    const countEl=document.getElementById('wlCount'+tab);
    if(countEl)countEl.textContent=`(${WATCHLISTS[tab].length})`;
  });
}

function renderWatchlistTable(tab){
  const tbody=document.getElementById('wlTbody'+tab);
  if(!tbody)return;
  const items=WATCHLISTS[tab];

  // Update stats
  const statCount=document.getElementById('wlStatCount'+tab);
  const statPaper=document.getElementById('wlStatPaper'+tab);
  const statLive=document.getElementById('wlStatLive'+tab);
  if(statCount)statCount.textContent=items.length;
  if(statPaper)statPaper.textContent=items.filter(x=>x.mode==='PAPER').length;
  if(statLive)statLive.textContent=items.filter(x=>x.mode==='LIVE').length;

  if(!items.length){
    const icons={CASH:'💰',FUTURE:'📈',OPTION:'📊'};
    const colspan=tab==='FUTURE'?'9':'10';
    tbody.innerHTML=`<tr class="wl-empty-row"><td colspan="${colspan}">No instruments in ${tab} Watchlist.<br><span style="font-size:11px">Add from the Strategies page or use the form below.</span></td></tr>`;
    return;
  }

  tbody.innerHTML=items.map((item,idx)=>{
    const ltp=getLtpDisplay(item.inst);
    const id=`${tab}_${idx}`;
    const isPaper=item.mode==='PAPER';
    const modeCls=isPaper?'paper':'live';
    const modeLbl=isPaper?'PAPER':'LIVE';

    // Strategy label — show friendly name (TB, RSI, etc.), NOT the sector sysId
    const rawStrat=(item.strategy||'SAR_TOP_BOTTOM');
    const stratMap={'SAR_TOP_BOTTOM':'TB','TOP_BOTTOM_2':'TB2','RSI_REVERSAL':'RSI','MACD_CROSS':'MACD','BB_SQUEEZE':'BB'};
    const stratLabel=stratMap[rawStrat]||rawStrat.split('_')[0];

    // Sector label — extract from FUT_SECTORS if available (for FUTURE tab)
    let sectorLabel='—';
    if(tab==='FUTURE'){
      Object.entries(FUT_SECTORS).forEach(([sector,stocks])=>{
        if(stocks.includes(item.inst)) sectorLabel=sector;
      });
    }

    // Entry / SL columns — only for CASH
    const entrySlCols=tab==='CASH' ? `
      <td class="wl-entry">
        <input type="number" class="wl-edit" id="wlEntry_${id}"
          value="${item.entryPrice}"
          placeholder="Entry"
          onclick="this.select()"
          onchange="onWlEntryChange('${tab}',${idx},this.value)">
      </td>
      <td class="wl-sl">
        <input type="number" class="wl-edit" id="wlSL_${id}"
          value="${item.sl}"
          placeholder="SL"
          onclick="this.select()"
          onchange="onWlSlChange('${tab}',${idx},this.value)">
      </td>` : '';

    return `<tr data-idx="${idx}" data-tab="${tab}">
      <td class="wl-sr">${idx+1}</td>
      <td class="wl-inst">${item.inst}</td>
      <td class="wl-sector">${tab==='FUTURE' ? sectorLabel : '—'}</td>
      <td class="wl-strat">${stratLabel}</td>
      <td class="wl-ltp ${ltp.cls}">${ltp.price}</td>
      <td class="wl-change ${ltp.cls}">${ltp.change}</td>
      ${entrySlCols}
      <td>
        <div class="wl-mode ${modeCls}" id="wlMode_${id}"
          onclick="onWlModeToggle('${tab}',${idx})"
          title="Click to switch mode">
          ${isPaper?'📋 PAPER':'⚡ LIVE'}
        </div>
      </td>
      <td>
        <button class="wl-hit" id="wlHit_${id}" onclick="onWlHit('${tab}',${idx})">GO</button>
      </td>
      <td>
        <button class="wl-rm" onclick="onWlRemove('${tab}',${idx})" title="Remove">✕</button>
      </td>
    </tr>`;
  }).join('');
}

/* ════════════════════════════════════════
   WATCHLIST EDIT EVENTS
════════════════════════════════════════ */
function onWlEntryChange(tab,idx,val){
  if(WATCHLISTS[tab][idx]) WATCHLISTS[tab][idx].entryPrice=val;
  saveWatchlists();
}
function onWlSlChange(tab,idx,val){
  if(WATCHLISTS[tab][idx]) WATCHLISTS[tab][idx].sl=val;
  saveWatchlists();
}
function onWlModeToggle(tab,idx){
  const item=WATCHLISTS[tab][idx];
  if(!item)return;
  item.mode=item.mode==='PAPER'?'LIVE':'PAPER';
  const id=`${tab}_${idx}`;
  const el=document.getElementById('wlMode_'+id);
  if(el){
    el.className=`wl-mode ${item.mode==='PAPER'?'paper':'live'}`;
    el.innerHTML=item.mode==='PAPER'?'📋 PAPER':'⚡ LIVE';
  }
  saveWatchlists();
  renderAllWatchlists(); // refresh stats
}

function onWlHit(tab,idx){
  const item=WATCHLISTS[tab][idx];
  if(!item)return;

  if(!(ws && ws.readyState===WebSocket.OPEN)){
    showToast('Engine not connected — cannot GO', 'var(--red)');
    return;
  }

  if(tab==='FUTURE'){
    // Derive sector: check if sysId is SEC_<name>, else infer from stock name
    let sector = 'AUTO';
    if(item.sysId && item.sysId.startsWith('SEC_')){
      sector = item.sysId.replace('SEC_',''); // e.g. 'PSU Bank', 'Auto', 'IT'
    } else {
      sector = _inferSector(item.inst);
    }
    ws.send(JSON.stringify({
      command: 'add_position',
      instrument: item.inst,
      mode: item.mode || 'PAPER',
      segment: 'STOCK_FUTURES',
      sector: sector,
    }));
    showToast(`📋 ${item.inst} added to Trade Log (WAITING)`, item.mode==='LIVE'?'var(--orange)':'var(--blue)');
  } else {
    // CASH / OPTION — no strategy defined yet
    showToast('⚠️ No strategy defined for CASH/OPTION segment', 'var(--orange)');
  }
}

function onWlRemove(tab,idx){
  const item=WATCHLISTS[tab][idx];
  if(!item)return;
  const inst=item.inst;
  const sysId=item.sysId;
  WATCHLISTS[tab].splice(idx,1);
  // Also uncheck strategy chip
  if(selectedInstruments[inst]===sysId){
    delete selectedInstruments[inst];
    refreshAllChips();
  }
  updateSegCount(tab);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
  showToast(`Removed ${inst}`,'var(--red)');
}

/* ════════════════════════════════════════
   ADD INSTRUMENT FROM WATCHLIST FORM
════════════════════════════════════════ */
function wlAddInstrument(tab){
  const input=document.getElementById('wlAdd'+tab);
  if(!input)return;
  const val=input.value.trim().toUpperCase();
  if(!val){showToast('Enter instrument name','var(--orange)');return;}
  if(WATCHLISTS[tab].find(x=>x.inst===val)){
    showToast(`${val} already in watchlist`,'var(--orange)');return;
  }
  let sysId = tab;
  let strategy = 'SAR_TOP_BOTTOM';
  if(tab==='FUTURE'){
    const sectorSel=document.getElementById('wlFutSector');
    const stratSel=document.getElementById('wlFutStrat');
    const chosenSector=sectorSel&&sectorSel.value?sectorSel.value:_inferSector(val);
    strategy=stratSel&&stratSel.value?stratSel.value:'SAR_TOP_BOTTOM';
    sysId=chosenSector&&chosenSector!=='OTHER'?'SEC_'+chosenSector:'FUTURE';
    selectedInstruments[val]=sysId;
  } else {
    selectedInstruments[val]=tab;
  }
  WATCHLISTS[tab].push({ inst:val, sysId:sysId, entryPrice:'', sl:'', mode:'PAPER', strategy:strategy });
  input.value='';
  updateSegCount(tab);
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
  showToast(`📋 ${val} added (${tab}, ${strategy.split('_')[0]})`,'var(--green)');
}

/* ════════════════════════════════════════
   ENGINE SYNC
════════════════════════════════════════ */
function syncToEngine(){
  if(ws&&ws.readyState===WebSocket.OPEN){
    // Sync ALL segments: CASH, FUTURES, and OPTIONS — send strategy/sector per instrument
    const allInsts=WATCHLISTS.CASH.concat(WATCHLISTS.FUTURE,WATCHLISTS.OPTION).map(x=>({
      inst:x.inst,
      strategy:x.strategy||'SAR_TOP_BOTTOM',
      sector:x.sector||'OTHER',
    }));
    ws.send(JSON.stringify({command:'sync_watchlist',instruments:allInsts}));
  }
}

/* ════════════════════════════════════════
   RENDER FUTURE SECTORS
════════════════════════════════════════ */
function renderFutureSectors(){
  const container=document.getElementById('futureSectorsBody');
  if(!container)return;
  container.innerHTML=Object.entries(FUT_SECTORS).map(([sector,stocks])=>{
    if(!STRAT_STOCKS['SEC_'+sector])STRAT_STOCKS['SEC_'+sector]=[...stocks];
    const checked=stocks.filter(s=>selectedInstruments[s]&&selectedInstruments[s]==='SEC_'+sector).length;
    return `<div class="sector-row" id="sec_${sector}">
      <div class="sector-row-header" onclick="toggleSector('${sector}')">
        <input type="checkbox" class="sector-cb" onchange="onSectorCheck('${sector}',this.checked)">
        <span class="sector-name">${sector}</span>
        <span class="sector-meta" id="secCnt_${sector}">${checked}/${stocks.length}</span>
        <span class="sector-arrow">▶</span>
      </div>
      <div class="sector-row-body">
        <div class="sys-stocks" id="secStocks_${sector}">
          ${stocks.map(stock=>renderChip(stock,'SEC_'+sector,'FUTURE')).join('')}
        </div>
        <div class="sys-row-actions">
          <button class="btn-add" onclick="addStockPrompt('SEC_${sector}')">+ Add Stock</button>
          <button class="btn-remove" onclick="removeStockPrompt('SEC_${sector}')">− Remove Stock</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

function onSectorCheck(sector,checked){
  const stocks=FUT_SECTORS[sector]||[];
  if(checked){
    stocks.forEach(s=>{
      selectedInstruments[s]='SEC_'+sector;
      if(!WATCHLISTS.FUTURE.find(x=>x.inst===s)){
        WATCHLISTS.FUTURE.push({ inst:s, sysId:'SEC_'+sector, entryPrice:'', sl:'', mode:'PAPER' });
      }
    });
  } else {
    stocks.forEach(s=>{
      delete selectedInstruments[s];
      const wi=WATCHLISTS.FUTURE.findIndex(x=>x.inst===s);
      if(wi!==-1)WATCHLISTS.FUTURE.splice(wi,1);
    });
  }
  renderSectorStocks(sector);
  updateSegCount('FUTURE');
  saveWatchlists();
  renderAllWatchlists();
  syncToEngine();
}

/* ════════════════════════════════════════
   TOAST
════════════════════════════════════════ */
function showToast(msg,color){
  const existing=document.querySelector('.toast-mavis');
  if(existing)existing.remove();
  const t=document.createElement('div');
  t.className='toast-mavis';
  t.textContent=msg;
  t.style.cssText=`position:fixed;bottom:24px;right:24px;z-index:99999;background:var(--bg-card);border:1px solid ${color||'var(--green)'};color:${color||'var(--green)'};padding:10px 18px;border-radius:8px;font-size:12px;font-weight:600;box-shadow:0 4px 20px rgba(0,0,0,0.5);animation:fadeUp 0.3s ease;max-width:320px`;
  document.body.appendChild(t);
  setTimeout(()=>t.remove(),3500);
}
const style=document.createElement('style');
style.textContent='@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}';
document.head.appendChild(style);

/* ════════════════════════════════════════
   INIT
════════════════════════════════════════ */
function init(){
  loadStratStocks();
  loadWatchlists();
  switchOrdersTab('Trades');  // Default to Trade Log panel (open positions)
  Object.keys(CASH_SYSTEMS).forEach(k=>{if(!STRAT_STOCKS[k])STRAT_STOCKS[k]=[...CASH_SYSTEMS[k].stocks];});
  Object.keys(FUTURE_SYSTEMS).forEach(k=>{if(!STRAT_STOCKS[k])STRAT_STOCKS[k]=[...FUTURE_SYSTEMS[k].stocks];});
  Object.keys(FUT_SECTORS).forEach(k=>{if(!STRAT_STOCKS['SEC_'+k])STRAT_STOCKS['SEC_'+k]=[...FUT_SECTORS[k]];});
  Object.keys(CASH_SYSTEMS).forEach(k=>renderSystemStocks(k,'CASH'));
  Object.keys(FUTURE_SYSTEMS).forEach(k=>renderSystemStocks(k,'FUTURE'));
  renderFutureSectors();
  // Clocks
  setInterval(()=>{
    const el=document.getElementById('stratClock');
    if(el)el.textContent=new Date().toLocaleTimeString('en-IN',{hour12:true});
    const wl=document.getElementById('wlClock');
    if(wl)wl.textContent=new Date().toLocaleTimeString('en-IN',{hour12:true});
  },1000);
  renderAllWatchlists();
  Object.keys(CASH_SYSTEMS).forEach(k=>updateSegCount('CASH'));
  Object.keys(FUTURE_SYSTEMS).forEach(k=>updateSegCount('FUTURE'));
  switchOrdersTab('Trades'); // Default to Trade Log tab
  connectWS();
}

init();

// Force hard reload when page is restored from Chrome bfcache (back/forward cache)
// This ensures fresh JS is loaded even if tab was backgrounded
window.addEventListener('pageshow', function(e){
  if(e.persisted){
    // Page was restored from bfcache — force a hard reload
    window.location.reload();
  }
});
