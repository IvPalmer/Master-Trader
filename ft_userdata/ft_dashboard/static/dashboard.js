/* dashboard.js — Alpine controller + ECharts panels for master-trader.
 *
 * Charts:
 *  - chart-equity     equity curve (live + scaled backtest expected)
 *  - chart-drawdown   underwater drawdown
 *  - chart-candles    open-position OHLC + entry + stop
 *  - chart-perpair    horizontal bars by pair
 *  - chart-equity-<k> per-bot dry-run equity overlay
 */

// C1 fix + light theme: updated palette
const COLORS = {
  pos: '#059669', neg: '#dc2626', warn: '#d97706',
  accent: '#0891b2', accent2: '#7c3aed', info: '#2563eb',
  text: '#0c121b', text2: '#475569', text3: '#64748b',
  surface: '#ffffff', surface2: '#f5f7fa', border: '#e4e8ee',
  hairline: 'rgba(15, 23, 42, 0.07)',
};

const ECHART_COMMON = {
  textStyle: { fontFamily: '"JetBrains Mono", ui-monospace, monospace', fontSize: 11, color: COLORS.text3 },
  backgroundColor: 'transparent',
  grid: { left: 50, right: 18, top: 28, bottom: 30, containLabel: false },
  axisPointer: { lineStyle: { color: COLORS.border, width: 1 } },
};

function dash() {
  return {
    raw: { bots: {}, errors: {}, last_poll: null },
    pollInterval: 30,
    tab: '',
    clock: '—',
    equityBot: null,
    closedTrades: [],
    tradesFilter: 'all',
    _tradeTfOverride: {},
    _charts: {},
    _equityData: {},
    _tradeCandles: {},
    _attentionExpanded: false,

    // ─── lifecycle ───
    boot() {
      // Restore tab from hash or default to live
      const hash = location.hash.slice(1);
      this.tab = hash || 'live';

      this.tickClock();
      setInterval(() => this.tickClock(), 1000);
      this.refresh().then(() => {
        this.equityBot = this.liveBots[0]?.key || null;
        this.fetchClosedTrades();
        this.$nextTick(() => this.renderCharts());
      });
      setInterval(() => this.refresh().then(() => {
        this.fetchClosedTrades();
        this.renderCharts();
      }), this.pollInterval * 1000);
      window.addEventListener('hashchange', () => {
        this.tab = location.hash.slice(1) || 'live';
        this.$nextTick(() => this.renderCharts());
      });
      window.addEventListener('resize', () => {
        Object.entries(this._charts).forEach(([id, c]) => {
          try { c?.resize(); }
          catch (e) { console.warn('resize', id, e?.message); }
        });
      });
      this.$watch('tab', () => this.$nextTick(() => this.renderCharts()));
    },
    setTab(t) {
      this.tab = t;
      location.hash = t === 'live' ? '' : t;
    },

    setTradesFilter(f) { this.tradesFilter = f; this.$nextTick(() => this.renderCharts()); },
    tickClock() {
      const d = new Date();
      this.clock = String(d.getUTCHours()).padStart(2, '0') + ':' +
                   String(d.getUTCMinutes()).padStart(2, '0') + ' utc';
    },

    async refresh() {
      try {
        const r = await fetch('/api/state', { cache: 'no-store' });
        if (r.ok) this.raw = await r.json();
      } catch (e) { console.warn('refresh', e); }
    },

    // ─── derived ───
    get bots() { return Object.values(this.raw.bots || {}); },
    get liveBots() {
      return this.bots.filter(b => b.reachable && b.dry_run === false)
        .sort((a, b) => a.label.localeCompare(b.label));
    },
    get dryRunBots() {
      return this.bots.filter(b => b.reachable && b.dry_run === true)
        .sort((a, b) => (a.label||'').localeCompare(b.label||''));
    },
    get allBots() {
      return this.bots.filter(b => b.reachable)
        .sort((a, b) => {
          // live first, then dry; alphabetical within each group
          if (a.dry_run !== b.dry_run) return a.dry_run ? 1 : -1;
          return (a.label||'').localeCompare(b.label||'');
        });
    },
    // ─── C1 fix: fleet-aggregated hero stats ───
    get hero() {
      const live = this.liveBots;
      const start = live.reduce((s, b) => s + b.wallet.starting_capital, 0);
      const owned = live.reduce((s, b) => s + b.wallet.bot_owned, 0);
      const walletNow = (live.length && owned > 0) ? owned : start;
      const totalPnl = walletNow - start;
      const closedTrades = live.reduce((s, b) => s + b.stats.closed_trade_count, 0);
      const totalWins = live.reduce((s, b) => s + b.stats.winning_trades, 0);
      const totalLosses = live.reduce((s, b) => s + b.stats.losing_trades, 0);
      // C1: weighted win rate (by closed-trade count) across all live bots
      const winRate = (totalWins + totalLosses) ? totalWins / (totalWins + totalLosses) : 0;
      // C1: fleet profit factor = sum(gross_profit) / sum(gross_loss)
      const grossProfit = live.reduce((s, b) => s + (b.stats.gross_profit ?? 0), 0);
      const grossLoss = live.reduce((s, b) => s + Math.abs(b.stats.gross_loss ?? 0), 0);
      const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : null;
      // C1: fleet expectancy = total realized PnL / total closed trades
      const totalRealizedPnl = live.reduce((s, b) => {
        return s + (b.stats.profit_all ?? b.pnl?.all_abs ?? 0);
      }, 0);
      const expectancyPerTrade = closedTrades > 0 ? totalRealizedPnl / closedTrades : null;
      // C1: max DD across fleet
      const ddMax = live.length ? Math.max(...live.map(b => b.stats.max_drawdown * 100)) : 0;
      const ddCurrentPerBot = live.map(b => {
        const dd = b.drawdown_curve;
        return dd && dd.length ? dd[dd.length - 1][1] : 0;
      });
      const ddCurrent = ddCurrentPerBot.length ? Math.min(...ddCurrentPerBot) : 0;
      // C1: max backtest DD across the fleet (worst bot's lab cap)
      const ddBacktest = live.length
        ? Math.max(...live.map(b => b.baseline?.max_dd_pct || 0))
        : 0;
      const ddCap = ddBacktest * 1.5;
      const open = live.reduce((s, b) => s + b.open_trades.length, 0);
      const openNotional = live.reduce((s, b) => s + b.open_trades.reduce((a, t) => a + (t.stake_amount || 0), 0), 0);
      const car = live.reduce((s, b) => s + (b.capital_at_risk?.abs_loss || 0), 0);
      const carPct = start ? (car / start * 100) : 0;

      // C1: fleet concentration — top pair across all live bots (aggregated by pair string)
      const pairMap = {};
      for (const b of live) {
        for (const pp of (b.per_pair || [])) {
          if (!pairMap[pp.pair]) pairMap[pp.pair] = { pnl: 0, trades: 0 };
          pairMap[pp.pair].pnl += Number(pp.pnl || 0);
          pairMap[pp.pair].trades += Number(pp.count || pp.trades || 0);
        }
      }
      const pairEntries = Object.entries(pairMap).sort((a, b) => Math.abs(b[1].pnl) - Math.abs(a[1].pnl));
      const grossPosPnl = pairEntries.reduce((s, [, v]) => s + Math.max(0, v.pnl), 0);
      let concentration = null;
      if (pairEntries.length) {
        const [topPair, topData] = pairEntries[0];
        const topShare = grossPosPnl > 0 ? Math.max(0, topData.pnl) / grossPosPnl : 0;
        const exTopPnl = pairEntries.slice(1).reduce((s, [, v]) => s + v.pnl, 0);
        const warn = topShare > 0.7 ? 'danger' : topShare > 0.5 ? 'warn' : '';
        concentration = { top_pair: topPair, top_pair_pnl: topData.pnl, top_pair_trades: topData.trades, top_share: topShare, ex_top_pnl: exTopPnl, warn };
      } else {
        // Fall back to primary bot's concentration if no per_pair fleet data yet
        concentration = live[0]?.concentration ?? null;
      }

      // C1: fleet avg win/loss for expectancy display
      const allRecentTrades = live.flatMap(b => b.recent_trades || []).filter(t => !t.is_open);
      const wins = allRecentTrades.filter(t => (t.profit_abs || 0) > 0);
      const losses = allRecentTrades.filter(t => (t.profit_abs || 0) < 0);
      const avgWin = wins.length ? wins.reduce((s, t) => s + t.profit_abs, 0) / wins.length : null;
      const avgLoss = losses.length ? losses.reduce((s, t) => s + t.profit_abs, 0) / losses.length : null;
      const payoff = avgLoss && avgLoss !== 0 ? Math.abs(avgWin / avgLoss) : null;

      return {
        walletNow,
        walletStart: start,
        totalPnl,
        totalPct: start ? (totalPnl / start * 100) : 0,
        closedTrades,
        // C1: labeled as fleet-level stats
        winRate,
        profitFactor,
        expectancyPerTrade,
        expectancySample: closedTrades,
        drawdownMaxPct: ddMax,
        drawdownCurrentPct: ddCurrent,
        drawdownBacktest: ddBacktest,
        drawdownCap: ddCap,
        openCount: open,
        openNotional,
        capitalAtRisk: car,
        capitalAtRiskPct: carPct,
        concentration,
        avgWin,
        avgLoss,
        payoff,
      };
    },

    // ─── C4: attention stack items ───
    get attentionItems() {
      const items = [];
      const now = Date.now() / 1000;

      // 1. Bleeding open trades (profit_pct ≤ -3%) — RED
      for (const b of this.liveBots) {
        for (const t of (b.open_trades || [])) {
          if ((t.profit_pct || 0) <= -3) {
            items.push({
              color: 'red',
              icon: '▼',
              subject: `${t.pair} bleeding ${this.fmtPctSigned(t.profit_pct)}`,
              reason: `${b.label} · open position`,
              cta: 'view trade',
              action: () => { this.setTab('live'); this.$nextTick(() => this.setOpenPos({ ...t, _bot: b.key })); },
            });
          }
        }
      }

      // 2. Stale bots — RED
      // status.stale_bots may be a list of strings (bot keys) or objects.
      // Resolve label across naming variants: raw.bots[key].label / .name / key fallback.
      const staleBots = this.raw.status?.stale_bots || [];
      for (const s of staleBots) {
        const key   = typeof s === 'string' ? s : (s.key || s.bot_key || '');
        const meta  = key ? this.raw.bots?.[key] : null;
        const label = (typeof s === 'object' && s.label) || meta?.label || meta?.name || key || 'unknown';
        const stale = (typeof s === 'object' && s.stale_hours) ? s.stale_hours + 'h ago' : 'unknown';
        items.push({
          color: 'red',
          icon: '!',
          subject: `${label} bot stale`,
          reason: `last seen ${stale} · check container`,
          cta: 'check logs',
          action: () => { if (key && this.allBots.find(b => b.key === key)) this.setTab('bot:' + key); },
        });
      }

      // 3. DD breach in last 24h — AMBER
      for (const b of [...this.liveBots, ...this.dryRunBots]) {
        if (b.delta_24h?.dd_breach) {
          items.push({
            color: 'amber',
            icon: '⚠',
            subject: `${b.label} DD breach last 24h`,
            reason: `drawdown exceeded 1.5× backtest cap`,
            cta: 'view bot',
            action: () => { this.setTab(b.dry_run ? 'dryrun' : 'live'); },
          });
        }
      }

      // 4. Gate-1 blocker: dry bot close to gate-1 (≥80% on trades ring) — AMBER
      for (const b of this.dryRunBots) {
        const pct = b.gate1?.trades?.pct ?? 0;
        const remaining = (b.gate1?.trades?.target ?? 30) - (b.gate1?.trades?.actual ?? 0);
        if (pct >= 80 && remaining > 0) {
          items.push({
            color: 'amber',
            icon: '◷',
            subject: `${b.label} needs ${remaining} more trade${remaining !== 1 ? 's' : ''} to gate-1`,
            reason: `${Math.round(pct)}% of sample threshold reached`,
            cta: 'view progress',
            action: () => { this.setTab('dryrun'); },
          });
        }
      }

      // 5. Observational bots with no baseline — BLUE (low urgency)
      for (const b of this.dryRunBots) {
        if (b.observational && !b.baseline?.profit_factor) {
          items.push({
            color: 'blue',
            icon: '○',
            subject: `${b.label} running observational · no baseline gate`,
            reason: 'copy-trader mode — graduation gates not active',
            cta: 'view bot',
            action: () => { this.setTab('dryrun'); },
          });
        }
      }

      return items;
    },
    get attentionVisible() {
      const items = this.attentionItems;
      if (this._attentionExpanded || items.length <= 3) return items;
      return items.slice(0, 3);
    },

    get openPositions() {
      const out = [];
      for (const b of this.liveBots) {
        for (const t of (b.open_trades || [])) {
          out.push({ ...t, _bot: b.key });
        }
      }
      return out;
    },
    openPosKey: null,
    setOpenPos(p) {
      this.openPosKey = p._bot + ':' + p.pair;
      this.$nextTick(() => this.renderCandles());
    },
    get openPos() {
      const list = this.openPositions;
      if (!list.length) return null;
      if (this.openPosKey) {
        const match = list.find(p => (p._bot + ':' + p.pair) === this.openPosKey);
        if (match) return match;
      }
      const sorted = [...list].sort((a, b) => (b.open_timestamp || 0) - (a.open_timestamp || 0));
      return sorted[0];
    },
    get openPosAge() {
      const ts = this.openPos?.open_timestamp;
      if (!ts) return 0;
      return Math.max(0, Math.floor((Date.now() - ts) / 1000));
    },
    get recentLiveTrades() {
      const live = this.liveBots;
      return live.flatMap(b => b.recent_trades).sort((a, b) => (b.close_timestamp || 0) - (a.close_timestamp || 0)).slice(0, 30);
    },
    get statusLabel() {
      if (!this.raw.last_poll) return 'connecting';
      const age = Date.now() / 1000 - this.raw.last_poll;
      if (age > 120) return 'stale';
      if (Object.keys(this.raw.errors || {}).length) return 'partial';
      return 'live';
    },
    get staleClass() {
      if (!this.raw.last_poll) return 'warn';
      const age = Date.now() / 1000 - this.raw.last_poll;
      if (age > 120) return 'err';
      if (Object.keys(this.raw.errors || {}).length) return 'warn';
      return '';
    },
    get lastPollLabel() {
      if (!this.raw.last_poll) return 'never';
      const age = Date.now() / 1000 - this.raw.last_poll;
      if (age < 60) return Math.round(age) + 's ago';
      if (age < 3600) return Math.round(age / 60) + 'm ago';
      return Math.round(age / 3600) + 'h ago';
    },

    // ─── C5: last closed trade for a bot ───
    // Don't mutate bot.recent_trades — sort a shallow copy.
    lastClosedTrade(bot) {
      const trades = (bot.recent_trades || []).filter(t => !t.is_open);
      if (!trades.length) return null;
      return [...trades].sort((a, b) => (b.close_timestamp || 0) - (a.close_timestamp || 0))[0];
    },

    // C5: deviation summary sentence
    deviationSummary(bot) {
      const liveProfit = bot.pnl?.all_pct ?? null;
      const btPf = bot.baseline?.profit_factor ?? null;
      const livePf = bot.stats?.profit_factor ?? null;
      if (livePf == null || btPf == null || btPf === 0) return null;
      const pfDelta = ((livePf - btPf) / btPf * 100).toFixed(0);
      const sign = pfDelta >= 0 ? '+' : '';
      const withinBand = Math.abs(pfDelta) <= 20 ? '— within ±20% band' : '— OUTSIDE ±20% band';
      return `${bot.label}: live PF ${livePf.toFixed(2)} is ${sign}${pfDelta}% vs backtest ${btPf} ${withinBand}`;
    },

    // C5: open trades for a specific bot (for per-bot detail panel)
    openTradesForBot(bot) {
      return (bot.open_trades || []).map(t => {
        const targetPct = bot.baseline?.roi_ladder?.[0] ?? 8;
        const stopPct = Math.abs(bot.baseline?.stoploss ?? 5);
        const currentPct = t.profit_pct ?? 0;
        // Progress bar: 0 = stop, 50% = entry, 100% = ROI target
        const totalRange = targetPct + stopPct;
        const progress = totalRange > 0 ? Math.max(0, Math.min(100, ((currentPct + stopPct) / totalRange) * 100)) : 50;
        const ageMin = t.open_timestamp ? Math.round((Date.now() - t.open_timestamp) / 60000) : 0;
        return { ...t, progress, ageMin, targetPct, stopPct };
      });
    },

    // ─── formatters ───
    fmtRate(n) { return n == null ? '—' : Number(n).toPrecision(5); },
    fmtUsd(n) { return n === null || n === undefined ? '—' : '$' + Number(n).toFixed(2); },
    fmtUsdSigned(n) {
      if (n === null || n === undefined) return '—';
      const v = Number(n);
      return (v >= 0 ? '+$' : '−$') + Math.abs(v).toFixed(2);
    },
    fmtPct(n, d = 2) { return n === null || n === undefined || isNaN(n) ? '—' : Number(n).toFixed(d) + '%'; },
    fmtPctSigned(n, d = 2) {
      if (n === null || n === undefined || isNaN(n)) return '—';
      const v = Number(n);
      return (v >= 0 ? '+' : '') + v.toFixed(d) + '%';
    },
    fmtPF(n) { return n === null || n === undefined || isNaN(n) ? '—' : Number(n).toFixed(2); },
    fmtAge(s) {
      if (!s) return '—';
      if (s < 60) return s + 's';
      if (s < 3600) return Math.round(s / 60) + 'm';
      if (s < 86400) return (s / 3600).toFixed(1) + 'h';
      return (s / 86400).toFixed(1) + 'd';
    },
    fmtMin(m) {
      if (!m) return '—';
      if (m < 60) return m + 'm';
      if (m < 1440) return (m / 60).toFixed(1) + 'h';
      return (m / 1440).toFixed(1) + 'd';
    },
    fmtDate(s) {
      if (!s) return '—';
      try { return s.replace('T', ' ').replace(/:\d{2}\..*/, '').slice(5, 16); }
      catch { return s; }
    },

    // ─── verdict + ETA ───
    readyVerdict(bot) {
      const g1 = Object.values(bot.gate1).every(x => x.ok);
      const g2 = ['profit', 'pf', 'dd'].every(k =>
        bot.gate2[k].status === 'ok' || bot.gate2[k].status === 'n/a');
      const g3 = Object.values(bot.gate3).every(x => x.ok);
      if (g1 && g2 && g3) return { text: 'ready to flip', cls: 'ready' };
      if (g1) return { text: 'gate-1 cleared · band watch', cls: 'watch' };
      return { text: 'not ready', cls: '' };
    },
    etaToGate1(bot) {
      const need = 30 - bot.stats.closed_trade_count;
      if (need <= 0) return 'cleared';
      if (bot.stats.closed_trade_count === 0 || bot.days_running === 0) return 'idle';
      const rate = bot.stats.closed_trade_count / bot.days_running;
      if (rate <= 0) return 'idle';
      const days = need / rate;
      if (days < 60) return Math.round(days) + ' days';
      if (days < 365) return Math.round(days / 7) + ' weeks';
      return Math.round(days / 30) + ' months';
    },
    g2DeltaClass(s) {
      if (s === 'ok') return 'pos';
      if (s === 'cold' || s === 'breach') return 'neg';
      return 'warn';
    },

    // ─── ring SVG (gate 1) ───
    renderRing(pct, ok) {
      const r = 46, c = 2 * Math.PI * r;
      const dash = c * Math.min(100, pct) / 100;
      const cls = ok ? 'ok' : 'run';
      return `
        <svg viewBox="0 0 110 110">
          <circle class="track" cx="55" cy="55" r="${r}"></circle>
          <circle class="arc ${cls}" cx="55" cy="55" r="${r}"
                  stroke-dasharray="${dash} ${c}"></circle>
        </svg>
        <div class="center"><div><div class="num">${Math.round(pct)}%</div></div></div>
      `;
    },

    // ─── bullet bar (gate 2) ───
    renderBullet(g, kind) {
      let lo, hi, target, lower, upper, actual, status;
      if (kind === 'pct') {
        target = g.expected_pct; lower = g.lower; upper = g.upper;
        actual = g.actual_pct; status = g.status;
        const span = Math.max(Math.abs(target - lower), Math.abs(upper - target), 4);
        lo = target - span * 2; hi = target + span * 2;
      } else if (kind === 'pf') {
        target = g.expected; lower = g.lower; upper = g.upper;
        actual = g.actual; status = g.status;
        if (actual === null || actual === undefined) {
          return `<div style="font-size:10px;color:var(--text-3);padding:2px 0;">no losses yet · PF undefined</div>`;
        }
        lo = 0; hi = Math.max(target * 2, actual * 1.2);
      } else if (kind === 'dd') {
        target = g.expected_pct; lower = 0; upper = g.expected_pct;
        actual = g.actual_pct; status = g.status;
        lo = 0; hi = g.cap_pct;
      } else { return ''; }
      const pct = v => Math.max(0, Math.min(100, ((v - lo) / (hi - lo) * 100)));
      const bandLeft = pct(lower);
      const bandWidth = pct(upper) - bandLeft;
      const targetX = pct(target);
      const markerX = pct(actual);
      const cls = status === 'ok' ? '' : ((status === 'cold' || status === 'breach') ? 'err' : 'warn');
      return `
        <div class="bullet-band" style="left:${bandLeft}%;width:${bandWidth}%;"></div>
        <div class="bullet-target" style="left:${targetX}%;"></div>
        <div class="bullet-marker ${cls}" style="left:calc(${markerX}% - 1.5px);"></div>
      `;
    },

    // ─── chart rendering ───
    renderCharts() {
      if (!window.echarts) { setTimeout(() => this.renderCharts(), 100); return; }
      const t = this.tab;
      if (t === 'live') {
        this.renderEquity();
        this.renderDrawdown();
        this.renderPerPair();
        this.renderCandles();
      } else if (t === 'dryrun') {
        this.dryRunBots.forEach(b => this.renderBotEquity(b.key));
      } else if (t === 'trades') {
        this.renderTradesCharts();
      } else if (t.startsWith('bot:')) {
        const key = t.slice(4);
        this.renderDetailCharts(key);
      }
    },

    // ─── trades tab ───
    get filteredTrades() {
      if (this.tradesFilter === 'all') return this.closedTrades;
      return this.closedTrades.filter(t => t.bot_key === this.tradesFilter);
    },
    get tradesWinRate() {
      const f = this.filteredTrades;
      if (!f.length) return '—';
      return ((f.filter(t => t.is_win).length / f.length) * 100).toFixed(1);
    },
    get tradesTotalPnl() {
      return this.filteredTrades.reduce((s, t) => s + (t.profit_abs || 0), 0);
    },
    formatTradeWindow(trade) {
      if (!trade.open_ts) return '';
      const open = new Date(trade.open_ts);
      const dur = trade.duration_min;
      const day = open.getUTCMonth() + 1 + '-' + String(open.getUTCDate()).padStart(2, '0');
      const hh = String(open.getUTCHours()).padStart(2, '0') + ':' + String(open.getUTCMinutes()).padStart(2, '0');
      const durStr = dur ? (dur < 60 ? dur + 'm' : (dur / 60).toFixed(1) + 'h') : '—';
      return `${day} ${hh} · ${durStr}`;
    },
    _tradeKey(trade) { return trade.bot_key + ':' + trade.pair + ':' + trade.open_ts; },
    tradeTimeframe(trade) {
      const k = this._tradeKey(trade);
      if (this._tradeTfOverride[k]) return this._tradeTfOverride[k];
      const durMin = trade.duration_min || 60;
      if (durMin < 90) return '5m';
      if (durMin < 360) return '15m';
      if (durMin < 1440) return '1h';
      return '4h';
    },
    setTradeTimeframe(trade, tf) {
      this._tradeTfOverride[this._tradeKey(trade)] = tf;
      this.$nextTick(() => this.renderTradeChart(trade));
    },

    async fetchClosedTrades() {
      try {
        const r = await fetch('/api/closed_trades', { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        this.closedTrades = data.trades || [];
        if (this.tab === 'trades') this.$nextTick(() => this.renderTradesCharts());
      } catch (e) { console.warn('fetchClosedTrades', e); }
    },

    renderTradesCharts() {
      this.filteredTrades.forEach(t => this.renderTradeChart(t));
    },

    async renderTradeChart(trade) {
      const chartId = 'trade-chart-' + trade.bot_key + '-' + trade.open_ts;
      const tf = this.tradeTimeframe(trade);
      const cacheKey = trade.bot_key + ':' + trade.pair + ':' + tf;
      let candles = this._tradeCandles[cacheKey];
      if (!candles) {
        try {
          const tfMs = { '5m': 5*60_000, '15m': 15*60_000, '1h': 60*60_000, '4h': 4*60*60_000 }[tf] || 60*60_000;
          const padCandles = 100;
          const startMs = trade.open_ts - padCandles * tfMs;
          const endMs = trade.close_ts + padCandles * tfMs;
          const url = `/api/binance_candles?pair=${encodeURIComponent(trade.pair)}&timeframe=${tf}&limit=500&start_ms=${startMs}&end_ms=${endMs}`;
          const r = await fetch(url, { cache: 'no-store' });
          if (!r.ok) return;
          const data = await r.json();
          candles = data.candles || [];
          this._tradeCandles[cacheKey] = candles;
        } catch { return; }
      }
      if (!candles.length) return;

      const span = trade.close_ts - trade.open_ts;
      const visiblePadMs = Math.max(span * 0.5, 30 * 60 * 1000);
      const visibleStart = trade.open_ts - visiblePadMs;
      const visibleEnd = trade.close_ts + visiblePadMs;

      const allCandles = candles.filter(c => c && c.length >= 5);
      if (!allCandles.length) return;

      const chart = this._ensureChart(chartId);
      if (!chart) return;

      const dates = allCandles.map(c => typeof c[0] === 'number' ? c[0] : new Date(c[0]).getTime());
      const ohlc = allCandles.map(c => [c[1], c[2], c[3], c[4]]);

      const winColor = trade.is_win ? COLORS.pos : COLORS.neg;
      const entryTs = trade.open_ts;
      const exitTs = trade.close_ts;

      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        grid: { left: 12, right: 56, top: 12, bottom: 54, containLabel: false },
        xAxis: {
          type: 'time',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 9, hideOverlap: true },
          splitLine: { show: false },
          axisPointer: { label: { show: false } },
        },
        yAxis: {
          type: 'value',
          scale: true,
          position: 'right',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 9, formatter: v => v.toPrecision(4) },
          splitLine: { lineStyle: { color: COLORS.border, opacity: 0.5 } },
          axisPointer: { label: { show: false } },
          min: ({ min, max }) => {
            const lo = Math.min(min, trade.open_rate, trade.close_rate, trade.stop_rate || trade.open_rate);
            const range = Math.max(max - min, 0.0001);
            return lo - range * 0.05;
          },
          max: ({ min, max }) => {
            const hi = Math.max(max, trade.open_rate, trade.close_rate);
            const range = Math.max(max - min, 0.0001);
            return hi + range * 0.05;
          },
        },
        dataZoom: [
          {
            type: 'slider',
            xAxisIndex: 0,
            startValue: visibleStart,
            endValue: visibleEnd,
            height: 22,
            bottom: 12,
            backgroundColor: COLORS.surface2,
            fillerColor: 'rgba(8, 145, 178, 0.12)',
            borderColor: COLORS.border,
            handleSize: '120%',
            handleStyle: { color: COLORS.accent, borderColor: COLORS.accent },
            moveHandleStyle: { color: COLORS.accent, opacity: 0.7 },
            emphasis: { handleStyle: { color: COLORS.accent, borderColor: COLORS.accent, shadowBlur: 4, shadowColor: COLORS.accent } },
            textStyle: { color: COLORS.text3, fontSize: 9 },
            showDetail: false,
            filterMode: 'filter',
          },
        ],
        series: [
          {
            type: 'candlestick',
            data: dates.map((d, i) => [d, ...ohlc[i]]),
            itemStyle: {
              color: COLORS.pos,
              color0: COLORS.neg,
              borderColor: COLORS.pos,
              borderColor0: COLORS.neg,
              borderWidth: 1,
            },
            markLine: {
              symbol: 'none',
              silent: true,
              animation: false,
              precision: 6,
              data: [
                {
                  yAxis: trade.open_rate,
                  lineStyle: { color: COLORS.text2, type: 'solid', width: 1, opacity: 0.8 },
                  label: { show: true, formatter: 'entry ' + (trade.open_rate||0).toPrecision(5),
                           position: 'insideStartTop', color: COLORS.text2, fontSize: 10, padding: [2, 4],
                           backgroundColor: 'rgba(245,247,250,0.9)', borderRadius: 2, borderColor: COLORS.border, borderWidth: 1 },
                },
                {
                  yAxis: trade.close_rate,
                  lineStyle: { color: winColor, type: 'solid', width: 1, opacity: 0.8 },
                  label: { show: true, formatter: (trade.is_win ? 'roi ' : 'sl ') + (trade.close_rate||0).toPrecision(5),
                           position: 'insideEndTop', color: winColor, fontSize: 10, padding: [2, 4],
                           backgroundColor: 'rgba(245,247,250,0.9)', borderRadius: 2, borderColor: winColor, borderWidth: 1 },
                },
                ...(trade.stop_rate ? [{
                  yAxis: trade.stop_rate,
                  lineStyle: { color: COLORS.neg, type: 'dashed', width: 1, opacity: 0.35 },
                  label: { show: true, formatter: 'stop ' + trade.stoploss_pct.toFixed(1) + '%',
                           position: 'insideStartBottom', color: COLORS.neg, fontSize: 9, padding: [2, 4],
                           backgroundColor: 'rgba(245,247,250,0.9)', borderRadius: 2, opacity: 0.8 },
                }] : []),
              ],
            },
            markPoint: {
              symbolSize: 12,
              animation: false,
              silent: true,
              label: { show: false },
              data: [
                {
                  name: 'entry',
                  value: trade.open_rate,
                  xAxis: entryTs,
                  yAxis: trade.open_rate,
                  symbol: 'circle',
                  itemStyle: {
                    color: COLORS.text,
                    borderColor: COLORS.surface,
                    borderWidth: 2,
                  },
                },
                {
                  name: 'exit',
                  value: trade.close_rate,
                  xAxis: exitTs,
                  yAxis: trade.close_rate,
                  symbol: 'circle',
                  itemStyle: {
                    color: winColor,
                    borderColor: COLORS.surface,
                    borderWidth: 2,
                  },
                },
              ],
            },
          },
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          backgroundColor: COLORS.surface,
          borderColor: COLORS.border,
          textStyle: { color: COLORS.text, fontSize: 10 },
          formatter: params => {
            const p = params.find(x => x.seriesType === 'candlestick');
            if (!p) return '';
            const [, o, c, l, h] = p.data;
            const d = new Date(p.axisValue);
            const ts = (d.getUTCMonth()+1) + '-' + String(d.getUTCDate()).padStart(2,'0') + ' ' +
                       String(d.getUTCHours()).padStart(2,'0') + ':' + String(d.getUTCMinutes()).padStart(2,'0');
            return `<b>${ts}</b><br/>O ${o.toPrecision(5)}<br/>H ${h.toPrecision(5)}<br/>L ${l.toPrecision(5)}<br/>C ${c.toPrecision(5)}`;
          },
        },
      }, true);
    },

    _ensureChart(id) {
      const el = document.getElementById(id);
      if (!el) return null;
      if (!this._charts[id] || this._charts[id].isDisposed()) {
        const chart = echarts.init(el, null, { renderer: 'canvas' });
        requestAnimationFrame(() => { try { chart.resize(); } catch {} });
        if (typeof ResizeObserver !== 'undefined') {
          const ro = new ResizeObserver(() => { try { chart.resize(); } catch {} });
          ro.observe(el);
          this._chartObservers = this._chartObservers || {};
          this._chartObservers[id]?.disconnect?.();
          this._chartObservers[id] = ro;
        }
        this._charts[id] = chart;
      }
      return this._charts[id];
    },

    async _fetchEquity(botKey) {
      if (!botKey) return null;
      try {
        const r = await fetch(`/api/equity/${botKey}`, { cache: 'no-store' });
        if (!r.ok) return null;
        const data = await r.json();
        this._equityData[botKey] = data;
        return data;
      } catch { return null; }
    },

    async renderEquity() {
      const key = this.equityBot || this.liveBots[0]?.key;
      if (!key) return;
      const data = await this._fetchEquity(key);
      const chart = this._ensureChart('chart-equity');
      if (!chart) return;
      const bot = this.raw.bots[key];
      const live = (data?.live || []).map(p => [new Date(p[0]), p[1]]);
      const startTs = data?.bot_start_ts_ms || (live[0]?.[0]?.getTime() ?? Date.now());
      const startCap = data?.starting_capital ?? bot.wallet.starting_capital;
      const annual = bot.baseline?.annual_return_pct ?? 0;
      const lastLiveTs = live.length ? live[live.length - 1][0].getTime() : Date.now();
      const horizon = Math.max(lastLiveTs, Date.now()) + 12 * 3600 * 1000;
      const expected = [];
      const POINTS = 80;
      for (let i = 0; i <= POINTS; i++) {
        const ts = startTs + (horizon - startTs) * i / POINTS;
        const days = (ts - startTs) / 86400000;
        const eq = startCap * Math.pow(1 + annual / 100, days / 365);
        expected.push([new Date(ts), Number(eq.toFixed(4))]);
      }
      const liveByTs = new Map(live.map(([d, v]) => [d.getTime(), v]));
      const winMarks = [];
      const lossMarks = [];
      const sortedClosed = (bot.recent_trades || [])
        .filter(t => !t.is_open && t.close_timestamp)
        .sort((a, b) => a.close_timestamp - b.close_timestamp);
      let runningEquity = bot.wallet.starting_capital;
      for (const t of sortedClosed) {
        runningEquity += Number(t.profit_abs || 0);
        const y = liveByTs.get(t.close_timestamp) ?? runningEquity;
        const m = { coord: [t.close_timestamp, y], pair: t.pair, pct: t.profit_pct };
        if ((t.profit_abs || 0) >= 0) winMarks.push(m);
        else lossMarks.push(m);
      }
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis',
          backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => v != null ? '$' + Number(v).toFixed(2) : '—',
        },
        legend: {
          data: ['live equity', 'backtest expected'],
          top: 0, right: 8, textStyle: { color: COLORS.text3, fontSize: 11 }, icon: 'roundRect', itemWidth: 10, itemHeight: 3,
        },
        grid: { left: 60, right: 18, top: 32, bottom: 30 },
        xAxis: {
          type: 'time',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 10 },
          splitLine: { show: false },
        },
        yAxis: {
          type: 'value',
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' },
          splitLine: { lineStyle: { color: COLORS.hairline, type: 'dashed' } },
          scale: true,
        },
        series: [
          {
            name: 'backtest expected',
            type: 'line', data: expected,
            showSymbol: false,
            lineStyle: { color: COLORS.text3, type: 'dashed', width: 1.4, opacity: 0.7 },
            itemStyle: { color: COLORS.text3 }, z: 1,
          },
          {
            name: 'live equity',
            type: 'line', data: live, smooth: false, showSymbol: false,
            lineStyle: { color: COLORS.accent, width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(8, 145, 178, 0.18)' },
                { offset: 1, color: 'rgba(8, 145, 178, 0.0)' },
              ]),
            },
            itemStyle: { color: COLORS.accent },
            markPoint: {
              symbol: 'circle', symbolSize: 7,
              data: [
                ...winMarks.map(m => ({
                  coord: m.coord, itemStyle: { color: COLORS.pos, borderColor: COLORS.surface, borderWidth: 1.5 },
                  label: { show: false },
                  tooltip: { formatter: () => `${m.pair} · +${m.pct?.toFixed(2)}%` },
                })),
                ...lossMarks.map(m => ({
                  coord: m.coord, itemStyle: { color: COLORS.neg, borderColor: COLORS.surface, borderWidth: 1.5 },
                  label: { show: false },
                  tooltip: { formatter: () => `${m.pair} · ${m.pct?.toFixed(2)}%` },
                })),
              ],
            },
            z: 2,
          },
        ],
      }, true);
    },

    async renderDrawdown() {
      const key = this.equityBot || this.liveBots[0]?.key;
      if (!key) return;
      let data = this._equityData[key];
      if (!data) data = await this._fetchEquity(key);
      const chart = this._ensureChart('chart-drawdown');
      if (!chart) return;
      const bot = this.raw.bots[key];
      const dd = (data?.drawdown || []).map(p => [new Date(p[0]), p[1]]);
      const ddCap = -(bot?.baseline?.max_dd_pct || 20) * 1.5;
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis',
          backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => v != null ? Number(v).toFixed(2) + '%' : '—',
        },
        grid: { left: 50, right: 18, top: 22, bottom: 30 },
        xAxis: {
          type: 'time',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 10 },
        },
        yAxis: {
          type: 'value', max: 0, min: Math.floor(ddCap),
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: {
            color: COLORS.text3, fontSize: 10,
            formatter: v => Math.round(v) + '%',
          },
          splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.5 } },
        },
        series: [{
          type: 'line', data: dd, showSymbol: false, smooth: false,
          lineStyle: { color: COLORS.neg, width: 1.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(220, 38, 38, 0.0)' },
              { offset: 1, color: 'rgba(220, 38, 38, 0.22)' },
            ]),
          },
          markLine: {
            silent: true, symbol: 'none',
            data: [
              {
                yAxis: ddCap,
                lineStyle: { color: COLORS.warn, type: 'dashed', width: 1 },
                label: {
                  show: true, position: 'insideEndTop',
                  formatter: 'cap ' + ddCap.toFixed(1) + '%',
                  color: COLORS.warn, fontSize: 10,
                  backgroundColor: 'rgba(245,247,250,0.9)', padding: [2, 4], borderRadius: 2,
                },
              },
              {
                yAxis: -(bot?.baseline?.max_dd_pct || 0),
                lineStyle: { color: COLORS.text3, type: 'dotted', width: 1, opacity: 0.6 },
                label: {
                  show: true, position: 'insideEndBottom',
                  formatter: 'backtest ' + (-(bot?.baseline?.max_dd_pct || 0)).toFixed(1) + '%',
                  color: COLORS.text3, fontSize: 10,
                  backgroundColor: 'rgba(245,247,250,0.9)', padding: [2, 4], borderRadius: 2,
                },
              },
            ],
          },
        }],
      }, true);
    },

    renderPerPair() {
      const chart = this._ensureChart('chart-perpair');
      if (!chart) return;
      // C1: aggregate per_pair across all live bots
      const pairMap = {};
      for (const b of this.liveBots) {
        for (const pp of (b.per_pair || [])) {
          if (!pairMap[pp.pair]) pairMap[pp.pair] = 0;
          pairMap[pp.pair] += Number(pp.pnl || 0);
        }
      }
      const rows = Object.entries(pairMap)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .slice(0, 10);
      if (!rows.length) {
        chart.setOption({ ...ECHART_COMMON, series: [], xAxis: { type: 'value' }, yAxis: { type: 'category', data: [] } }, true);
        return;
      }
      const pairs = rows.map(r => r[0]);
      const pnls = rows.map(r => Number(r[1]).toFixed(2));
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis', axisPointer: { type: 'shadow' },
          backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => '$' + Number(v).toFixed(2),
        },
        grid: { left: 70, right: 50, top: 12, bottom: 24 },
        xAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' },
          splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.5 } },
        },
        yAxis: {
          type: 'category', data: [...pairs].reverse(),
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: COLORS.text2, fontSize: 11 },
        },
        series: [{
          type: 'bar', data: [...pnls].reverse(),
          itemStyle: {
            color: p => Number(p.value) >= 0 ? COLORS.pos : COLORS.neg,
            borderRadius: [0, 3, 3, 0],
          },
          label: {
            show: true, position: 'right', formatter: p => '$' + Number(p.value).toFixed(2),
            color: COLORS.text2, fontSize: 10, fontFamily: 'JetBrains Mono',
          },
          barWidth: 14,
        }],
      }, true);
    },

    async renderCandles() {
      const pos = this.openPos;
      const chart = this._ensureChart('chart-candles');
      if (!chart || !pos) return;
      try {
        const r = await fetch(`/api/candles/${pos._bot}?pair=${encodeURIComponent(pos.pair)}&timeframe=1h&limit=120`, { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        const candles = (data.candles || []).map(c => [c[0], c[1], c[2], c[3], c[4]]);
        if (!candles.length) return;
        const dates = candles.map(c => c[0]);
        const ohlc = candles.map(c => [c[1], c[2], c[3], c[4]]);

        const decimals = (() => {
          const rng = Math.max(...ohlc.flat());
          if (rng >= 100) return 2;
          if (rng >= 1) return 4;
          return 5;
        })();
        const fmt = v => Number(v).toFixed(decimals);
        const pct = (a, b) => ((a - b) / b * 100);

        const stop = pos.stop_loss_abs;
        const entry = pos.open_rate;
        const now = pos.current_rate;

        const lows = ohlc.map(c => c[2]);
        const highs = ohlc.map(c => c[3]);
        const candleMin = Math.min(...lows, stop ?? Infinity, entry ?? Infinity);
        const candleMax = Math.max(...highs, entry ?? -Infinity);
        const padY = (candleMax - candleMin) * 0.10;
        const yMin = candleMin - padY;
        const yMax = candleMax + padY;

        const areas = [];
        if (entry != null && stop != null) {
          areas.push([
            { yAxis: stop, itemStyle: { color: 'rgba(220, 38, 38, 0.08)' } },
            { yAxis: entry },
          ]);
        }
        if (entry != null && entry < yMax) {
          areas.push([
            { yAxis: entry, itemStyle: { color: 'rgba(5, 150, 105, 0.07)' } },
            { yAxis: yMax },
          ]);
        }

        const lines = [];
        const baseLabel = {
          show: true, fontSize: 10, fontFamily: 'JetBrains Mono',
          backgroundColor: 'rgba(245, 247, 250, 0.92)',
          padding: [3, 6], borderRadius: 2, borderWidth: 1,
        };
        if (entry != null) {
          lines.push({
            yAxis: entry,
            lineStyle: { color: COLORS.accent, type: 'solid', width: 1.6 },
            label: { ...baseLabel, position: 'insideStartTop', distance: 3,
                     formatter: '▶ entry ' + fmt(entry),
                     color: COLORS.accent, borderColor: COLORS.accent },
          });
        }
        if (stop != null) {
          lines.push({
            yAxis: stop,
            lineStyle: { color: COLORS.neg, type: 'dashed', width: 1.6 },
            label: { ...baseLabel, position: 'insideStartBottom', distance: 3,
                     formatter: '▼ stop −5% · ' + fmt(stop),
                     color: COLORS.neg, borderColor: COLORS.neg },
          });
        }
        if (now != null && entry != null) {
          const pnlPct = pct(now, entry);
          const farFromEntry = Math.abs(pnlPct) > 0.5;
          lines.push({
            yAxis: now,
            lineStyle: { color: pnlPct >= 0 ? COLORS.pos : COLORS.neg, type: 'dotted', width: 1.2 },
            label: { ...baseLabel,
                     position: farFromEntry ? 'insideEndTop' : 'insideMiddleTop',
                     distance: 3,
                     formatter: 'now ' + fmt(now) + ' · ' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%',
                     color: pnlPct >= 0 ? COLORS.pos : COLORS.neg,
                     borderColor: pnlPct >= 0 ? COLORS.pos : COLORS.neg },
          });
        }

        chart.setOption({
          ...ECHART_COMMON,
          animation: false,
          tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: COLORS.border } },
            backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1,
            textStyle: { color: COLORS.text, fontSize: 11 },
          },
          grid: { left: 60, right: 12, top: 14, bottom: 30 },
          xAxis: {
            type: 'category', data: dates,
            axisLine: { lineStyle: { color: COLORS.border } },
            axisLabel: { color: COLORS.text3, fontSize: 9, formatter: v => v.slice(5, 16).replace('T', ' ') },
          },
          yAxis: {
            scale: true,
            min: yMin - padY, max: yMax + padY,
            axisLine: { show: false }, axisTick: { show: false },
            axisLabel: { color: COLORS.text3, fontSize: 10, formatter: v => fmt(v) },
            splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.5 } },
          },
          series: [{
            type: 'candlestick', data: ohlc,
            itemStyle: {
              color: COLORS.pos, color0: COLORS.neg,
              borderColor: COLORS.pos, borderColor0: COLORS.neg,
              borderWidth: 1,
            },
            markArea: { silent: true, data: areas },
            markLine: { silent: true, symbol: 'none', data: lines },
          }],
        }, true);
      } catch (e) { console.warn('candles', e); }
    },

    async renderBotEquity(key) {
      const data = await this._fetchEquity(key);
      const chart = this._ensureChart('chart-equity-' + key);
      if (!chart) return;
      const bot = this.raw.bots[key];
      const startTs = data?.bot_start_ts_ms || 0;
      const expected = (data?.expected || []).filter(p => p[0] >= startTs).map(p => [new Date(p[0]), p[1]]);
      const live = (data?.live || []).map(p => [new Date(p[0]), p[1]]);
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis',
          backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => v != null ? '$' + Number(v).toFixed(2) : '—',
        },
        legend: {
          data: ['live equity', 'backtest expected'],
          top: 0, right: 8, textStyle: { color: COLORS.text3, fontSize: 11 }, icon: 'roundRect', itemWidth: 10, itemHeight: 3,
        },
        grid: { left: 60, right: 18, top: 32, bottom: 30 },
        xAxis: { type: 'time', axisLine: { lineStyle: { color: COLORS.border } }, axisLabel: { color: COLORS.text3, fontSize: 10 }, splitLine: { show: false } },
        yAxis: {
          type: 'value', scale: true,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' },
          splitLine: { lineStyle: { color: COLORS.hairline, type: 'dashed' } },
        },
        series: [
          { name: 'backtest expected', type: 'line', data: expected, showSymbol: false,
            lineStyle: { color: COLORS.text3, type: 'dashed', width: 1.2 } },
          { name: 'live equity', type: 'line', data: live, showSymbol: false,
            lineStyle: { color: COLORS.info, width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(37, 99, 235, 0.18)' },
                { offset: 1, color: 'rgba(37, 99, 235, 0.0)' },
              ]),
            },
          },
        ],
      }, true);
    },

    // ─── per-bot detail tab charts ───
    async renderDetailCharts(key) {
      const bot = this.raw.bots[key];
      if (!bot) return;
      const data = await this._fetchEquity(key);

      // equity
      const equityChart = this._ensureChart('chart-detail-equity-' + key);
      if (equityChart) {
        const startTs  = data?.bot_start_ts_ms || 0;
        const startCap = data?.starting_capital ?? bot.wallet?.starting_capital ?? 200;
        const annual   = bot.baseline?.annual_return_pct ?? 0;
        const live     = (data?.live || []).map(p => [new Date(p[0]), p[1]]);
        const lastLiveTs = live.length ? live[live.length-1][0].getTime() : Date.now();
        const horizon  = Math.max(lastLiveTs, Date.now()) + 12*3600*1000;
        const expected = [];
        for (let i = 0; i <= 80; i++) {
          const ts   = startTs + (horizon - startTs) * i / 80;
          const days = (ts - startTs) / 86400000;
          expected.push([new Date(ts), startCap * Math.pow(1 + annual/100, days/365)]);
        }
        equityChart.setOption({
          ...ECHART_COMMON, animation: false,
          tooltip: { trigger: 'axis', backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1, textStyle: { color: COLORS.text, fontSize: 11 }, valueFormatter: v => v != null ? '$' + Number(v).toFixed(2) : '—' },
          legend: { data: ['live equity', 'backtest expected'], top: 0, right: 8, textStyle: { color: COLORS.text3, fontSize: 11 }, icon: 'roundRect', itemWidth: 10, itemHeight: 3 },
          grid: { left: 60, right: 18, top: 32, bottom: 30 },
          xAxis: { type: 'time', axisLine: { lineStyle: { color: COLORS.border } }, axisLabel: { color: COLORS.text3, fontSize: 10 }, splitLine: { show: false } },
          yAxis: { type: 'value', scale: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' }, splitLine: { lineStyle: { color: COLORS.hairline, type: 'dashed' } } },
          series: [
            { name: 'backtest expected', type: 'line', data: expected, showSymbol: false, lineStyle: { color: COLORS.text3, type: 'dashed', width: 1.2 } },
            { name: 'live equity', type: 'line', data: live, showSymbol: false,
              lineStyle: { color: COLORS.info, width: 2 },
              areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(37,99,235,0.18)' }, { offset: 1, color: 'rgba(37,99,235,0)' }]) } },
          ],
        }, true);
      }

      // drawdown
      const ddChart = this._ensureChart('chart-detail-dd-' + key);
      if (ddChart) {
        const dd    = (data?.drawdown || []).map(p => [new Date(p[0]), p[1]]);
        const ddCap = -(bot.baseline?.max_dd_pct || 20) * 1.5;
        ddChart.setOption({
          ...ECHART_COMMON, animation: false,
          tooltip: { trigger: 'axis', backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1, textStyle: { color: COLORS.text, fontSize: 11 }, valueFormatter: v => v != null ? Number(v).toFixed(2) + '%' : '—' },
          grid: { left: 50, right: 18, top: 22, bottom: 30 },
          xAxis: { type: 'time', axisLine: { lineStyle: { color: COLORS.border } }, axisLabel: { color: COLORS.text3, fontSize: 10 } },
          yAxis: { type: 'value', max: 0, min: Math.floor(ddCap), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: COLORS.text3, fontSize: 10, formatter: v => Math.round(v) + '%' }, splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.5 } } },
          series: [{
            type: 'line', data: dd, showSymbol: false,
            lineStyle: { color: COLORS.neg, width: 1.5 },
            areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(220,38,38,0)' }, { offset: 1, color: 'rgba(220,38,38,0.22)' }]) },
            markLine: { silent: true, symbol: 'none', data: [{ yAxis: ddCap, lineStyle: { color: COLORS.warn, type: 'dashed', width: 1 }, label: { show: true, position: 'insideEndTop', formatter: 'cap ' + ddCap.toFixed(1) + '%', color: COLORS.warn, fontSize: 10, backgroundColor: 'rgba(245,247,250,0.9)', padding: [2, 4], borderRadius: 2 } }] },
          }],
        }, true);
      }

      // p&l by pair
      const pairChart = this._ensureChart('chart-detail-pair-' + key);
      if (pairChart) {
        const rows  = (bot.per_pair || []).slice(0, 10);
        const pairs = rows.map(r => r.pair);
        const pnls  = rows.map(r => Number(r.pnl).toFixed(2));
        pairChart.setOption({
          ...ECHART_COMMON, animation: false,
          tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: COLORS.surface, borderColor: COLORS.border, borderWidth: 1, textStyle: { color: COLORS.text, fontSize: 11 }, valueFormatter: v => '$' + Number(v).toFixed(2) },
          grid: { left: 70, right: 50, top: 12, bottom: 24 },
          xAxis: { type: 'value', axisLine: { lineStyle: { color: COLORS.border } }, axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' }, splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.5 } } },
          yAxis: { type: 'category', data: [...pairs].reverse(), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: COLORS.text2, fontSize: 11 } },
          series: [{ type: 'bar', data: [...pnls].reverse(), itemStyle: { color: p => Number(p.value) >= 0 ? COLORS.pos : COLORS.neg, borderRadius: [0, 3, 3, 0] }, label: { show: true, position: 'right', formatter: p => '$' + Number(p.value).toFixed(2), color: COLORS.text2, fontSize: 10, fontFamily: 'JetBrains Mono' }, barWidth: 12 }],
        }, true);
      }
    },

    _renderEmptyChart(chart, msg) {
      chart.setOption({
        ...ECHART_COMMON,
        graphic: [{ type: 'text', left: 'center', top: 'middle', style: { text: msg, fill: COLORS.text3, fontSize: 12 } }],
        xAxis: { show: false }, yAxis: { show: false }, series: [],
      }, true);
    },
  };
}
