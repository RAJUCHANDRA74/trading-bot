// ═══════════════════════════════════════════════════════════════
// SARTrader — Bloomberg Dashboard JS
// Engine state format:
//   {"type":"state","data":{ mode, timestamp, paper, brokers,
//     quotes, strategies, positions, signals, trades,
//     live_trades, segment_pnl, watchlist, watchlist_data,
//     available_futures, current_expiry, ... }}
// ═══════════════════════════════════════════════════════════════

// ─── STATE ───────────────────────────────────────────────────
var _ws = null;
var _loggedIn = false;
var _engineMode = 'PAPER';
var _positions = {};       // inst → position object
var _signals = [];         // recent signals array
var _quotes = {};          // inst → {last_price, change, change_pct, arrow}
var _quotesBase = {};     // base sym → quote (for NIFTY, BANK, etc.)
var _segFilter = 'ALL';   // dashboard segment filter
var _tlSegFilter = 'ALL'; // trade log segment filter
var _wlTab = 'ALL';        // watchlist active tab
var _selectedStrategy = 'RSI';
var _journalData = {};    // inst → notes
var _drawdown = 0;
var _initCapital = 100000;
var _realCapital = 163199;
var _wsConnected = false;
var _reconnectTimer = null;
var _lastState = null;
var _liveTrades = [];     // closed trades from engine
var _segmentPnl = {};     // {CASH: x, FUTURE: x, OPTIONS: x}

// ─── PASSWORD ────────────────────────────────────────────────
function attemptLogin() {
  var pw = document.getElementById('loginPassword').value;
  if (!pw) return;
  fetch('/auth', {method: 'POST', body: pw})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.ok) {
        _loggedIn = true;
        document.getElementById('loginOverlay').style.display = 'none';
        document.getElementById('mainLayout').classList.add('active');
        initWS();
        startClock();
      } else {
        var err = document.getElementById('loginError');
        err.style.display = 'block';
        document.getElementById('loginPassword').value = '';
      }
    })
    .catch(function(){
      // If /auth endpoint not available, accept any non-empty password
      _loggedIn = true;
      document.getElementById('loginOverlay').style.display = 'none';
      document.getElementById('mainLayout').classList.add('active');
      initWS();
      startClock();
    });
}

function logout() {
  if (_ws) { try { _ws.close(); } catch(e){} _ws = null; }
  _loggedIn = false;
  _positions = {};
  _signals = [];
  _quotes = {};
  _liveTrades = [];
  document.getElementById('loginOverlay').style.display = 'flex';
  document.getElementById('mainLayout').classList.remove('active');
  document.getElementById('loginPassword').value = '';
  document.getElementById('loginError').style.display = 'none';
}

// ─── WEBSOCKET ───────────────────────────────────────────────
function initWS() {
  var host = window.location.hostname || 'localhost';
  // WS port is HTTP port + 1
  var port = parseInt(window.location.port) || 8765;
  port = port + 1;
  var url = 'ws://' + host + ':' + port;
  connectWS(url);
}

function connectWS(url) {
  if (_ws) { try { _ws.close(); } catch(e){} }
  _ws = new WebSocket(url);
  _ws.onopen = function() {
    _wsConnected = true;
    setWsStatus(true);
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    send({type: 'get_state'});
  };
  _ws.onmessage = function(evt) {
    try {
      var msg = JSON.parse(evt.data);
      handleMessage(msg);
    } catch(e) { console.warn('WS parse error', e); }
  };
  _ws.onclose = function() {
    _wsConnected = false;
    setWsStatus(false);
    _reconnectTimer = setTimeout(function(){ connectWS(url); }, 3000);
  };
  _ws.onerror = function() {
    _wsConnected = false;
    setWsStatus(false);
  };
}

function send(obj) {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(obj));
  }
}

function setWsStatus(connected) {
  var dot = document.getElementById('wsDot');
  var lbl = document.getElementById('wsLabel');
  if (!dot || !lbl) return;
  dot.style.background = connected ? 'var(--text)' : 'var(--red)';
  lbl.textContent = connected ? 'WS' : 'WS';
}

// ─── MESSAGE HANDLER ─────────────────────────────────────────
// Engine sends: {"type":"state", "data": {...state dict...}}
// The "data" field is the actual state object
function handleMessage(msg) {
  var state = msg.data || msg; // support both {type, data} and direct state

  if (msg.type === 'state' && msg.data) {
    _lastState = msg.data;
    _engineMode = msg.data.mode || 'PAPER';
    _positions = msg.data.positions || {};
    _signals = msg.data.signals || [];
    _liveTrades = msg.data.live_trades || [];
    _quotes = msg.data.quotes || {};
    _quotesBase = msg.data.quotes || {};
    _segmentPnl = msg.data.segment_pnl || {};
    if (msg.data.drawdown !== undefined) _drawdown = msg.data.drawdown;
    if (msg.data.capital !== undefined) _initCapital = msg.data.capital;
    if (msg.data.timestamp) { /* last update time */ }

    updateModeBadge();
    updateFooter();
    updateMetrics();
    updateSignals();
    updateTrades();
    updateTickerBar();
    updatePortfolio();
    updateBrokers();
    updateStrategies();
    updateWatchlist();

  } else if (msg.type === 'signal' && msg.data) {
    _signals = [msg.data].concat(_signals).slice(0, 50);
    updateSignals();

  } else if (msg.type === 'position_update' && msg.data) {
    var pos = msg.data;
    if (pos.instrument) {
      if (pos.status === 'CLOSED' || pos.closed) {
        delete _positions[pos.instrument];
      } else {
        _positions[pos.instrument] = pos;
      }
    }
    updateMetrics();
    updateTrades();
    updatePortfolio();

  } else if (msg.type === 'quote' && msg.data) {
    // Individual quote: {inst, last_price, change, change_pct}
    var q = msg.data;
    _quotes[q.inst] = q;
    _quotesBase[q.inst] = q;
    updateTickerBar();
    updateWatchlist();

  } else if (msg.type === 'notification') {
    // Show notification toast briefly
    showNotification(msg.message || msg.text || '');

  } else if (msg.type === 'error') {
    showNotification(msg.message || 'Error', true);
  }
}

// ─── NOTIFICATIONS ──────────────────────────────────────────
var _notifTimer = null;
function showNotification(text, isError) {
  var existing = document.getElementById('notifToast');
  if (existing) existing.remove();
  var div = document.createElement('div');
  div.id = 'notifToast';
  div.style.cssText = [
    'position:fixed;top:50px;right:20px;z-index:9999',
    'background:' + (isError ? 'var(--red-dim)' : 'var(--dim)'),
    'border:1px solid ' + (isError ? 'rgba(255,51,68,0.4)' : 'var(--text-soft)'),
    'color:' + (isError ? 'var(--red)' : 'var(--text)'),
    'padding:10px 16px;font-size:12px;font-family:var(--font)',
    'border-radius:2px;max-width:300px',
    'box-shadow:0 4px 12px rgba(0,0,0,0.5)'
  ].join(';');
  div.textContent = (isError ? '✗ ' : '✓ ') + text;
  document.body.appendChild(div);
  if (_notifTimer) clearTimeout(_notifTimer);
  _notifTimer = setTimeout(function(){ div.remove(); }, 4000);
}

// ─── CLOCK ──────────────────────────────────────────────────
function startClock() {
  tickClock();
  setInterval(tickClock, 1000);
}
function tickClock() {
  var els = ['liveClock','stratClock','wlClock','tlClock','pfClock','brClock'];
  var now = new Date();
  var h = now.getHours().toString().padStart(2,'0');
  var m = now.getMinutes().toString().padStart(2,'0');
  var s = now.getSeconds().toString().padStart(2,'0');
  var t = h + ':' + m + ':' + s;
  for (var i = 0; i < els.length; i++) {
    var el = document.getElementById(els[i]);
    if (el) el.textContent = t;
  }
}

// ─── VIEW SWITCHING ──────────────────────────────────────────
function switchView(name) {
  var views = ['Dashboard','Strategies','Watchlist','TradeLog','Portfolio','Brokers'];
  for (var i = 0; i < views.length; i++) {
    var vw = document.getElementById('view' + views[i]);
    var nb = document.getElementById('nav' + views[i]);
    if (vw) vw.classList.remove('active');
    if (nb) nb.classList.remove('active');
  }
  var av = document.getElementById('view' + name);
  var ab = document.getElementById('nav' + name);
  if (av) av.classList.add('active');
  if (ab) ab.classList.add('active');
}

// ─── METRICS ─────────────────────────────────────────────────
function updateMetrics() {
  // segment_pnl from engine: {CASH: x, FUTURE: x, OPTIONS: x}
  var segPnl = _segmentPnl || {};
  var futPnl = parseFloat(segPnl.FUTURE || segPnl.Futures || 0);
  var cashPnl = parseFloat(segPnl.CASH || segPnl.Cash || 0);
  var optPnl = parseFloat(segPnl.OPTIONS || segPnl.Options || 0);

  // Running positions
  var longs = 0, shorts = 0, totalPnl = 0;
  var keys = Object.keys(_positions);
  for (var i = 0; i < keys.length; i++) {
    var p = _positions[keys[i]];
    totalPnl += parseFloat(p.unrealized_pnl || 0);
    var dir = p.direction || p.side || '';
    if (dir === 'LONG') longs++;
    else if (dir === 'SHORT') shorts++;
  }

  // Closed P&L from live_trades
  var closedPnl = 0, wins = 0, losses = 0, tradeCount = 0;
  for (var j = 0; j < _liveTrades.length; j++) {
    var t = _liveTrades[j];
    var pnl = parseFloat(t.pnl || 0);
    closedPnl += pnl;
    tradeCount++;
    if (pnl > 0) wins++;
    else if (pnl < 0) losses++;
  }
  var winRate = tradeCount > 0 ? Math.round(wins / tradeCount * 100) + '%' : '—';

  var totalAllPnl = totalPnl + closedPnl;

  setBox('snapTotalPnl', totalAllPnl, true);
  setBox('snapTodayPnl', 0, true); // today P&L not tracked separately
  document.getElementById('snapLongs').textContent = longs;
  document.getElementById('snapShorts').textContent = shorts;
  setBox('snapFutPnl', futPnl, true);
  setBox('snapCashPnl', cashPnl, true);
  setBox('snapOptPnl', optPnl, true);
  document.getElementById('snapWinRate').textContent = winRate;
  setBox('snapClosedPnl', closedPnl, true);
}

function setBox(id, val, isPnl) {
  var el = document.getElementById(id);
  if (!el) return;
  var num = parseFloat(val) || 0;
  var prefix = num >= 0 ? '₹' : '-₹';
  el.textContent = prefix + formatNum(Math.abs(num));
  if (isPnl) {
    el.style.color = num >= 0 ? 'var(--text)' : 'var(--red)';
  }
}

function formatNum(n) {
  if (n >= 100000) return (n/100000).toFixed(1) + 'L';
  if (n >= 1000) return (n/1000).toFixed(1) + 'K';
  return n.toFixed(0);
}

// ─── MODE BADGE & FOOTER ─────────────────────────────────────
function updateModeBadge() {
  var badge = document.getElementById('topModeBadge');
  if (!badge) return;
  if (_engineMode === 'LIVE') {
    badge.className = 'mode-badge live';
    badge.textContent = '● LIVE';
  } else {
    badge.className = 'mode-badge paper';
    badge.textContent = '● PAPER';
  }
  var fm = document.getElementById('footerMode');
  if (fm) fm.textContent = _engineMode;
}

function updateFooter() {
  var sEl = document.getElementById('footerStatus');
  if (sEl) {
    sEl.textContent = _wsConnected ? 'ACTIVE' : 'RECONNECTING';
    sEl.style.color = _wsConnected ? 'var(--text)' : 'var(--amber)';
  }
  var btn = document.getElementById('btnExitAll');
  if (btn) {
    btn.style.display = Object.keys(_positions).length > 0 ? 'block' : 'none';
  }
}

// ─── TICKER BAR ─────────────────────────────────────────────
function updateTickerBar() {
  // Engine provides quotes under keys: NIFTY, BANKNIFTY, GOLD, SILVER
  // Each has: last_price, change, change_pct
  var tickers = {
    'NIFTY': ['niftyPrice','niftyArrow','niftyChange'],
    'BANKNIFTY': ['bnPrice','bnArrow','bnChange'],
    'GOLD': ['goldPrice','goldArrow','goldChange'],
    'SILVER': ['silverPrice','silverArrow','silverChange'],
    'USD/INR': ['usdPrice','usdArrow','usdChange']
  };
  var bases = Object.keys(tickers);
  for (var i = 0; i < bases.length; i++) {
    var base = bases[i];
    var ids = tickers[base];
    var q = _quotesBase[base] || _quotes[base] || {};
    var priceEl = document.getElementById(ids[0]);
    var arrowEl = document.getElementById(ids[1]);
    var chgEl = document.getElementById(ids[2]);

    if (priceEl) priceEl.textContent = q.last_price ? formatPrice(q.last_price) : '—';
    if (arrowEl) {
      var chg = parseFloat(q.change || 0);
      var pct = parseFloat(q.change_pct || 0);
      if (chg > 0) {
        arrowEl.textContent = '▲';
        arrowEl.className = 'tk-arrow up';
      } else if (chg < 0) {
        arrowEl.textContent = '▼';
        arrowEl.className = 'tk-arrow dn';
      } else {
        arrowEl.textContent = '—';
        arrowEl.className = 'tk-arrow';
      }
    }
    if (chgEl) {
      var pct = parseFloat(q.change_pct || 0);
      chgEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
      chgEl.className = 'tk-change ' + (pct >= 0 ? 'up' : 'dn');
    }
  }
}

function formatPrice(p) {
  if (!p && p !== 0) return '—';
  p = parseFloat(p);
  if (p >= 10000) return p.toFixed(0);
  if (p >= 100) return p.toFixed(1);
  return p.toFixed(2);
}

// ─── RECENT SIGNALS ──────────────────────────────────────────
// Engine sends: signals = self._signals[-20:]
// Each signal: {instrument, direction, type, price, sl, target, strategy, score, time, status, segment_type, ...}
function updateSignals() {
  var tbody = document.getElementById('signalsBody');
  if (!tbody) return;
  var filtered = _signals.filter(function(s) {
    if (_segFilter === 'ALL') return true;
    var seg = (s.segment_type || s.segment || '').toUpperCase();
    if (_segFilter === 'CASH') return !/FUT|OPT/i.test(seg);
    if (_segFilter === 'FUTURE') return /FUT/i.test(seg);
    if (_segFilter === 'OPTIONS') return /OPT/i.test(seg);
    return true;
  });
  var countEl = document.getElementById('signalCount');
  if (countEl) countEl.textContent = filtered.length;

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="11">No signals yet...</td></tr>';
    return;
  }
  var rows = [];
  for (var i = 0; i < filtered.length; i++) {
    var s = filtered[i];
    var dir = s.direction || s.side || '';
    var dirClass = dir === 'LONG' ? 'long' : dir === 'SHORT' ? 'short' : '';
    var status = s.status || 'ACTIVE';
    var statusClass = status === 'ACTIVE' ? 'active' : status === 'PENDING' ? 'pending' : 'closed';
    rows.push([
      '<tr>',
      '<td class="col-n">' + (i+1) + '</td>',
      '<td class="col-time">' + (s.time || '—') + '</td>',
      '<td class="col-strat">' + escHtml(s.strategy || '—') + '</td>',
      '<td class="col-inst">' + escHtml(s.instrument || '—') + '</td>',
      '<td class="col-type">' + escHtml(s.type || '—') + '</td>',
      '<td class="col-price">' + (s.price || '—') + '</td>',
      '<td class="col-dir ' + dirClass + '">' + dir + '</td>',
      '<td class="col-score">' + (s.score !== undefined ? s.score : '—') + '</td>',
      '<td class="col-sl">' + (s.sl || '—') + '</td>',
      '<td class="col-target">' + (s.target || '—') + '</td>',
      '<td class="col-status ' + statusClass + '">' + status + '</td>',
      '</tr>'
    ].join(''));
  }
  tbody.innerHTML = rows.join('');
}

// ─── RECENT TRADES (Running Positions) ────────────────────────
// Shows _positions (live, running positions)
function updateTrades() {
  var tbody = document.getElementById('tradesBody');
  if (!tbody) return;
  var seg = _segFilter;
  var posList = Object.keys(_positions).map(function(k){ return _positions[k]; });
  var filtered = posList.filter(function(p) {
    if (seg === 'ALL') return true;
    var st = (p.segment_type || p.sector || 'CASH').toUpperCase();
    if (seg === 'CASH') return !/FUT|OPT/i.test(st);
    if (seg === 'FUTURE') return /FUT/i.test(st);
    if (seg === 'OPTIONS') return /OPT/i.test(st);
    return true;
  });

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="12">No trades yet...</td></tr>';
    return;
  }
  var rows = [];
  for (var i = 0; i < filtered.length; i++) {
    var p = filtered[i];
    var dir = p.direction || p.side || '—';
    var dirClass = dir === 'LONG' ? 'long' : dir === 'SHORT' ? 'short' : '';
    var status = p.status || 'ACTIVE';
    var statusClass = status === 'ACTIVE' ? 'active' : 'closed';
    var pnl = parseFloat(p.unrealized_pnl || 0);
    var pnlClass = pnl >= 0 ? 'pos' : 'neg';
    var ltp = p.ltp || p.last_price || '—';
    var qty = p.qty || p.quantity || 1;
    var entry = p.entry_price || '—';
    var sector = p.sector || p.segment_type || '—';
    var inst = p.instrument || '';
    rows.push([
      '<tr onclick="showTradeDetail(\'' + escAttr(inst) + '\')" style="cursor:pointer">',
      '<td class="col-n">' + (i+1) + '</td>',
      '<td class="col-time">' + fmtTime(p.entry_time || p.entry_date || '—') + '</td>',
      '<td class="col-inst">' + escHtml(inst) + '</td>',
      '<td class="col-dir ' + dirClass + '">' + dir + '</td>',
      '<td class="col-price">' + entry + '</td>',
      '<td class="col-qty">' + qty + '</td>',
      '<td class="col-ltp">' + (typeof ltp === 'number' ? formatPrice(ltp) : ltp) + '</td>',
      '<td class="col-pnl ' + pnlClass + '">' + (pnl >= 0 ? '+' : '') + '₹' + pnl.toFixed(0) + '</td>',
      '<td class="col-status ' + statusClass + '">' + status + '</td>',
      '<td class="col-sector">' + escHtml(sector) + '</td>',
      '<td class="col-pnl ' + pnlClass + '">' + (pnl >= 0 ? '+' : '') + '₹' + pnl.toFixed(0) + '</td>',
      '<td class="col-remove" onclick="event.stopPropagation();removePosition(\'' + escAttr(inst) + '\')">×</td>',
      '</tr>'
    ].join(''));
  }
  tbody.innerHTML = rows.join('');
}

function fmtTime(ts) {
  if (!ts || ts === '—') return '—';
  if (ts.length > 10) return ts.slice(0,16).replace('T',' ');
  return ts;
}

// ─── SEGMENT FILTER ──────────────────────────────────────────
function onSegFilter() {
  var sel = document.getElementById('segFilter');
  _segFilter = sel ? sel.value : 'ALL';
  updateSignals();
  updateTrades();
}

function onTlSegFilter() {
  var sel = document.getElementById('tlSegFilter');
  _tlSegFilter = sel ? sel.value : 'ALL';
  updateTradeLog();
}

// ─── EXIT ALL ────────────────────────────────────────────────
function onExitAll() {
  if (!confirm('Exit ALL positions?')) return;
  send({type: 'exit_all'});
}

// ─── TRADE LOG ───────────────────────────────────────────────
// Shows closed trades from live_trades + running positions
function updateTradeLog() {
  var tbody = document.getElementById('tlBody');
  if (!tbody) return;
  var seg = _tlSegFilter;

  // Combine running positions + closed trades
  var running = Object.keys(_positions).map(function(k){ return _positions[k]; });
  var closed = (_liveTrades || []).map(function(t) {
    return {
      instrument: t.instrument || t.symbol || '—',
      direction: t.side || t.direction || '—',
      entry_price: t.entry_price || t.entry || 0,
      exit_price: t.exit_price || t.exit || 0,
      quantity: t.quantity || t.qty || 1,
      closed_pnl: t.pnl || 0,
      status: 'CLOSED',
      sector: t.sector || t.segment || '—',
      entry_time: t.entry_time || t.time || '—',
      exit_time: t.exit_time || t.closed_at || '—'
    };
  });
  var all = running.concat(closed);

  var filtered = all.filter(function(p) {
    if (seg === 'ALL') return true;
    var st = (p.segment_type || p.sector || 'CASH').toUpperCase();
    if (seg === 'CASH') return !/FUT|OPT/i.test(st);
    if (seg === 'FUTURE') return /FUT/i.test(st);
    if (seg === 'OPTIONS') return /OPT/i.test(st);
    return true;
  });

  // Summary
  var total = all.length;
  var wins = 0, losses = 0, netPnl = 0, active = running.length;
  for (var i = 0; i < all.length; i++) {
    var pnl = parseFloat(all[i].closed_pnl || all[i].unrealized_pnl || 0);
    if (all[i].status !== 'ACTIVE') {
      netPnl += pnl;
      if (pnl > 0) wins++;
      else if (pnl < 0) losses++;
    }
  }
  var wr = total > 0 ? Math.round(wins / total * 100) + '%' : '—';
  setEl('tlTotal', total);
  setEl('tlWins', wins);
  setEl('tlLosses', losses);
  setEl('tlWinRate', wr);
  var pnlEl = document.getElementById('tlPnl');
  if (pnlEl) {
    pnlEl.textContent = (netPnl >= 0 ? '₹' : '-₹') + Math.abs(netPnl).toFixed(0);
    pnlEl.style.color = netPnl < 0 ? 'var(--red)' : 'var(--text)';
  }
  setEl('tlActive', active);

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="11">No trades recorded...</td></tr>';
    return;
  }
  var rows = [];
  for (var j = 0; j < filtered.length; j++) {
    var p = filtered[j];
    var dir = p.direction || p.side || '—';
    var dirClass = dir === 'LONG' ? 'long' : dir === 'SHORT' ? 'short' : '';
    var status = p.status || 'CLOSED';
    var statusClass = status === 'ACTIVE' ? 'active' : status === 'CLOSED' ? 'closed' : 'pending';
    var pnl = parseFloat(p.closed_pnl || p.unrealized_pnl || 0);
    var pnlClass = pnl >= 0 ? 'pos' : 'neg';
    var exitPx = p.exit_price || p.close_price || (status === 'ACTIVE' ? '—' : '—');
    var qty = p.quantity || p.qty || 1;
    var entryPx = p.entry_price || '—';
    var sector = p.sector || p.segment_type || '—';
    var inst = p.instrument || '';
    rows.push([
      '<tr>',
      '<td class="col-n">' + (j+1) + '</td>',
      '<td class="col-time">' + fmtTime(p.entry_time || p.time || '—') + '</td>',
      '<td class="col-inst">' + escHtml(inst) + '</td>',
      '<td class="col-dir ' + dirClass + '">' + dir + '</td>',
      '<td class="col-price">' + (entryPx !== '—' ? formatPrice(entryPx) : '—') + '</td>',
      '<td class="col-qty">' + qty + '</td>',
      '<td class="col-price">' + (exitPx !== '—' && exitPx ? formatPrice(exitPx) : '—') + '</td>',
      '<td class="col-pnl ' + pnlClass + '">' + (pnl >= 0 ? '+' : '') + '₹' + pnl.toFixed(0) + '</td>',
      '<td class="col-status ' + statusClass + '">' + status + '</td>',
      '<td class="col-sector">' + escHtml(sector) + '</td>',
      '<td>',
      status === 'ACTIVE'
        ? '<button class="tl-stop" style="padding:2px 8px;font-size:10px" onclick="closePosition(\'' + escAttr(inst) + '\')">CLOSE</button>'
        : '',
      '</td>',
      '</tr>'
    ].join(''));
  }
  tbody.innerHTML = rows.join('');
}

function setEl(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ─── TRADE DETAIL ────────────────────────────────────────────
function showTradeDetail(inst) {
  switchView('TradeLog');
}

function removePosition(inst) {
  if (!confirm('Remove ' + inst + ' from dashboard?')) return;
  send({type: 'remove_position', instrument: inst});
}

function closePosition(inst) {
  send({type: 'exit_position', instrument: inst});
}

// ─── WATCHLIST ───────────────────────────────────────────────
// Engine provides: watchlist = list of symbols, watchlist_data = {sym: {symbol, strategy, added_at, ...}}
function wlTab(seg, el) {
  _wlTab = seg;
  var tabs = document.querySelectorAll('.wl-tab');
  for (var i = 0; i < tabs.length; i++) tabs[i].classList.remove('active');
  if (el) el.classList.add('active');
  updateWatchlist();
}

function updateWatchlist() {
  var tbody = document.getElementById('wlBody');
  if (!tbody) return;

  // Get watchlist from state
  var wlKeys = [];
  if (_lastState && _lastState.watchlist_data) {
    wlKeys = Object.keys(_lastState.watchlist_data);
  } else if (_lastState && _lastState.watchlist) {
    wlKeys = _lastState.watchlist;
  }

  var filtered = wlKeys.filter(function(inst) {
    if (_wlTab === 'ALL') return true;
    var s = inst.toUpperCase();
    if (_wlTab === 'CASH') return !/FUT|OPT/i.test(s);
    if (_wlTab === 'FUTURE') return /FUT/i.test(s);
    if (_wlTab === 'OPTIONS') return /OPT/i.test(s);
    return true;
  });

  // Stats
  var total = wlKeys.length;
  var active = 0, longs = 0, shorts = 0;
  for (var i = 0; i < wlKeys.length; i++) {
    var q = _quotes[wlKeys[i]] || {};
    if (q.signal === 'LONG') { active++; longs++; }
    else if (q.signal === 'SHORT') { active++; shorts++; }
  }
  setEl('wlCount', total);
  setEl('wlActive', active);
  setEl('wlLongs', longs);
  setEl('wlShorts', shorts);

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">No instruments in watchlist...</td></tr>';
    return;
  }
  var rows = [];
  for (var j = 0; j < filtered.length; j++) {
    var inst = filtered[j];
    var wd = _lastState && _lastState.watchlist_data ? (_lastState.watchlist_data[inst] || {}) : {};
    var q = _quotes[inst] || {};
    var ltp = q.last_price || wd.ltp || '—';
    var chg = parseFloat(q.change_pct || 0);
    var chgStr = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    var chgCls = chg >= 0 ? 'up' : 'dn';
    var sig = q.signal || wd.signal || '—';
    var sigColor = sig === 'LONG' ? 'var(--text)' : sig === 'SHORT' ? 'var(--red)' : 'var(--text-dim)';
    rows.push([
      '<tr>',
      '<td class="col-n">' + (j+1) + '</td>',
      '<td class="col-inst">' + escHtml(inst) + '</td>',
      '<td class="col-strat">' + escHtml(wd.strategy || '—') + '</td>',
      '<td class="col-price">' + (typeof ltp === 'number' ? formatPrice(ltp) : ltp) + '</td>',
      '<td><span class="tk-change ' + chgCls + '">' + chgStr + '</span></td>',
      '<td>' + (wd.entry || '—') + '</td>',
      '<td class="col-sl">' + (wd.sl || '—') + '</td>',
      '<td style="color:' + sigColor + ';font-weight:bold">' + sig + '</td>',
      '<td class="col-remove" onclick="removeFromWatchlist(\'' + escAttr(inst) + '\')">×</td>',
      '</tr>'
    ].join(''));
  }
  tbody.innerHTML = rows.join('');
}

function addWatchlistPrompt() {
  var inst = prompt('Enter instrument symbol:');
  if (inst && inst.trim()) {
    send({type: 'add_to_watchlist', instrument: inst.trim().toUpperCase()});
  }
}

function removeFromWatchlist(inst) {
  send({type: 'remove_strategy', instrument: inst});
}

// ─── STRATEGIES ─────────────────────────────────────────────
function selectCashStrat(id) {
  _selectedStrategy = id;
  var chips = document.querySelectorAll('[id^="cashStrat"]');
  for (var i = 0; i < chips.length; i++) chips[i].classList.remove('active');
  var el = document.getElementById('cashStrat' + id);
  if (el) el.classList.add('active');
}

function toggleSeg(seg) {
  var el = document.getElementById('seg' + seg);
  if (el) el.classList.toggle('open');
}

function toggleSys(sys) {
  var el = document.getElementById('sys' + sys);
  if (el) el.classList.toggle('open');
}

function addStockPrompt(sys) {
  var inst = prompt('Enter stock symbol (e.g. RELIANCE):');
  if (inst && inst.trim()) {
    send({type: 'apply_strategy', instrument: inst.trim().toUpperCase(), strategy: sys});
  }
}

function removeStockPrompt(sys) {
  var inst = prompt('Enter stock symbol to remove:');
  if (inst && inst.trim()) {
    send({type: 'remove_strategy', instrument: inst.trim().toUpperCase()});
  }
}

function addFuturePrompt() {
  var inst = prompt('Enter futures symbol (e.g. ICICIBANKSEPFUT26):');
  if (inst && inst.trim()) {
    send({type: 'apply_strategy', instrument: inst.trim().toUpperCase(), strategy: 'STOCKFUT'});
  }
}

function addOptionPrompt() {
  var inst = prompt('Enter option symbol (e.g. NIFTY 26000 CE):');
  if (inst && inst.trim()) {
    send({type: 'apply_strategy', instrument: inst.trim().toUpperCase(), strategy: 'TB1'});
  }
}

function updateStrategies() {
  if (!_lastState || !_lastState.strategies) return;
  var strats = _lastState.strategies;

  // Count per segment
  var cashCount = 0, futCount = 0, optCount = 0;
  var stratKeys = Object.keys(strats);
  for (var i = 0; i < stratKeys.length; i++) {
    var k = stratKeys[i];
    var upper = k.toUpperCase();
    if (/FUT/i.test(k)) futCount++;
    else if (/OPT|CE|PE/i.test(k)) optCount++;
    else cashCount++;
  }

  setStratCount('cntCASH', cashCount + ' in watchlist');
  setStratCount('cntFUTURE', futCount + ' in watchlist');
  setStratCount('cntOPTIONS', optCount + ' in watchlist');
  setStratCount('cntABCT', cashCount + ' stocks');
  setStratCount('cntSTOCKFUT', futCount + ' stocks');
  setStratCount('cntTB1', optCount + ' instruments');

  // System checkbox states
  var sysMap = {ABCT: 'cbABCT', STOCKFUT: 'cbSTOCKFUT', TB1: 'cbTB1'};
  var sysKeys = Object.keys(sysMap);
  for (var j = 0; j < sysKeys.length; j++) {
    var sysKey = sysKeys[j];
    var cb = document.getElementById(sysMap[sysKey]);
    if (!cb) continue;
    // Find matching strategy key
    var matched = false;
    for (var sk = 0; sk < stratKeys.length; sk++) {
      if (stratKeys[sk].toUpperCase().includes(sysKey)) {
        cb.checked = strats[stratKeys[sk]].enabled || false;
        matched = true;
        break;
      }
    }
    if (!matched) cb.checked = false;
  }
}

function setStratCount(id, text) {
  var el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ─── PORTFOLIO ──────────────────────────────────────────────
function updatePortfolio() {
  var capital = _engineMode === 'LIVE' ? _realCapital : _initCapital;
  var deployed = 0;
  var keys = Object.keys(_positions);
  for (var i = 0; i < keys.length; i++) {
    var p = _positions[keys[i]];
    deployed += parseFloat(p.deployed_value || 0);
    // Estimate deployed from entry_price * qty if not set
    if (!p.deployed_value && p.entry_price && p.qty) {
      deployed += parseFloat(p.entry_price) * parseInt(p.qty);
    }
  }
  var available = capital - deployed;

  setEl('pfCapital', '₹' + capital.toLocaleString('en-IN'));
  setEl('pfDeployed', '₹' + deployed.toLocaleString('en-IN'));
  setEl('pfAvailable', '₹' + available.toLocaleString('en-IN'));
  setEl('pfDD', '₹' + _drawdown.toLocaleString('en-IN'));

  var tbody = document.getElementById('pfBody');
  if (!tbody) return;
  var activePos = keys.filter(function(k){ return (_positions[k].status || '') === 'ACTIVE'; });
  if (!activePos || activePos.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No active positions...</td></tr>';
    return;
  }
  var rows = [];
  for (var j = 0; j < activePos.length; j++) {
    var p = _positions[activePos[j]];
    var dir = p.direction || p.side || '—';
    var dirClass = dir === 'LONG' ? 'long' : dir === 'SHORT' ? 'short' : '';
    var pnl = parseFloat(p.unrealized_pnl || 0);
    var pnlClass = pnl >= 0 ? 'pos' : 'neg';
    var inst = p.instrument || '';
    rows.push([
      '<tr>',
      '<td class="col-n">' + (j+1) + '</td>',
      '<td class="col-inst">' + escHtml(inst) + '</td>',
      '<td class="col-dir ' + dirClass + '">' + dir + '</td>',
      '<td class="col-qty">' + (p.qty || p.quantity || 1) + '</td>',
      '<td class="col-price">' + (p.entry_price ? formatPrice(p.entry_price) : '—') + '</td>',
      '<td class="col-ltp">' + (p.ltp ? formatPrice(p.ltp) : '—') + '</td>',
      '<td class="col-pnl ' + pnlClass + '">' + (pnl >= 0 ? '+' : '') + '₹' + pnl.toFixed(0) + '</td>',
      '<td class="col-sl">' + (p.current_sl || p.sl || '—') + '</td>',
      '<td class="col-target">' + (p.target || '—') + '</td>',
      '<td class="col-remove" onclick="removePosition(\'' + escAttr(inst) + '\')">×</td>',
      '</tr>'
    ].join(''));
  }
  tbody.innerHTML = rows.join('');
}

// ─── BROKERS ─────────────────────────────────────────────────
function updateBrokers() {
  if (!_lastState || !_lastState.brokers) return;
  var brs = _lastState.brokers;

  // M-Stock
  if (brs.MSTOCK) {
    var ms = brs.MSTOCK;
    var statusEl = document.getElementById('mstockStatus');
    if (statusEl) {
      statusEl.textContent = ms.connected ? 'CONNECTED' : 'DISCONNECTED';
      statusEl.className = 'broker-status ' + (ms.connected ? 'connected' : 'disconnected');
    }
    if (ms.account) {
      var acc = ms.account;
      setEl('brAccount', acc.client_id || acc.account_id || '—');
      setEl('brBalance', acc.balance ? '₹' + parseFloat(acc.balance).toLocaleString('en-IN') : '—');
    }
    setEl('brApi', ms.connected ? 'WHITELISTED' : '—');
    setEl('brData', ms.connected ? 'STREAMING' : '—');
    setEl('brOrders', (ms.positions ? ms.positions.length + ' positions' : '—'));
  }
}

function disconnectBroker(br) {
  send({type: 'disconnect_broker', broker: br});
}
function reconnectBroker(br) {
  send({type: 'connect_broker', broker: br});
}
function showKiteConnect() {
  var key = prompt('Enter Kite API Key:');
  if (key && key.trim()) {
    send({type: 'connect_broker', broker: 'KITE', api_key: key.trim()});
  }
}
function showAlpineConnect() {
  var clientId = prompt('Enter Alpine Client ID:');
  if (clientId && clientId.trim()) {
    send({type: 'connect_broker', broker: 'ALPINE', client_id: clientId.trim()});
  }
}

// ─── TRADE JOURNAL ──────────────────────────────────────────
function saveJournal(btn) {
  var card = btn ? btn.closest('.journal-card') : null;
  if (!card) return;
  var textarea = card.querySelector('textarea');
  var instEl = card.querySelector('.journal-inst');
  var inst = instEl ? instEl.textContent : '';
  var note = textarea ? textarea.value : '';
  _journalData[inst] = note;
  send({type: 'save_journal', instrument: inst, note: note});
  btn.textContent = 'SAVED ✓';
  setTimeout(function(){ btn.textContent = 'SAVE NOTE'; }, 1500);
}

// ─── UTILITIES ──────────────────────────────────────────────
function escHtml(str) {
  if (str === undefined || str === null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escAttr(str) {
  if (str === undefined || str === null) return '';
  return String(str).replace(/'/g,"\\'").replace(/"/g,'&quot;');
}

// ─── INIT ────────────────────────────────────────────────────
window.addEventListener('load', function() {
  document.getElementById('loginOverlay').style.display = 'flex';
  // Auto-login for development: press Enter on password field
  document.getElementById('loginPassword').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') attemptLogin();
  });
});

// Keyboard shortcut: Ctrl+Shift+R = hard refresh
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.shiftKey && e.key === 'R') {
    e.preventDefault();
    window.location.reload();
  }
});
