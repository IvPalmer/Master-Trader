/* dashboard.js — Alpine controller + TradingView charts for master-trader.
 *
 * Charts:
 *  - chart-equity     equity curve (live + scaled backtest expected)
 *  - chart-drawdown   underwater drawdown
 *  - chart-candles    open-position OHLC + entry + stop
 *  - chart-perpair    horizontal bars by pair
 *  - chart-equity-<k> per-bot dry-run equity overlay
 */

// Palette mirrors styles.css tokens so charts match the page.
const COLORS = {
  surface:  '#ffffff',
  surface2: '#f6f8fa',
  text:     '#12171f',
  text2:    '#56606e',
  text3:    '#61717f',
  border:   '#dce3e9',
  hairline: '#edf1f4',
  accent:   '#0e87a3',
  pos:      '#0a8f5b',
  neg:      '#d2473a',
  warn:     '#b07a16',
  info:     '#0e87a3',
};

// Bug fix B3: coerce timestamps — Freqtrade returns ms but guard against seconds
function toMs(ts) {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

// Closed P&L persists between fills. Extend only to the latest observation;
// the current open mark is a separate snapshot, never invented unrealized history.
function closedEquityThroughMark(realized, marked) {
  const points = realized.map(p => [new Date(p[0]), p[1]]);
  const last = points[points.length - 1];
  const end = marked[marked.length - 1]?.[0];
  if (last && end && Number(new Date(end)) > Number(last[0])) {
    points.push([new Date(end), last[1]]);
  }
  return points;
}

function dash() {
  // Chart libraries keep identity-sensitive internals. Keep instances outside Alpine
  // reactive state so methods always receive the original instance as `this`.
  const charts = {};
  return {
    raw: { bots: {}, errors: {}, last_poll: null },
    pollInterval: 30,
    tab: '',
    clock: '—',
    equityBot: 'fleet',
    // Dry-run drawer: which bot's inline dossier shows under the grad table.
    // Single selection so the table controls the view rather than stacking dossiers.
    selectedDryBot: null,
    closedTrades: [],
    tradesView: 'open',
    tradesFilter: 'all',
    _tradeTfOverride: {},
    _tradeScale: {},
    expandedTrade: null,
    closeTrade: null, closeBusy: false, closeMessage: '', closeUser: '', closePassword: '', closeRequestId: null,
    showClose(trade) {
      this.closeTrade = {...trade}; this.closeMessage = ''; this.closePassword = '';
      this.closeRequestId = crypto.randomUUID();
      this.$refs.closeDialog.showModal();
    },
    dismissClose() { if (!this.closeBusy) { this.$refs.closeDialog.close(); this.closePassword = ''; } },
    async submitClose() {
      if (this.closeBusy || !this.closeTrade) return;
      const t = this.closeTrade; this.closeBusy = true; this.closeMessage = 'Submitting exit request…';
      try {
        const credential = btoa(String.fromCharCode(...new TextEncoder().encode(this.closeUser+':'+this.closePassword)));
        const r = await fetch(`/api/trades/${encodeURIComponent(t.bot_key)}/${t.trade_id}/close`, {
          method:'POST', headers:{'Content-Type':'application/json','X-Trade-Action':'close','Authorization':'Basic '+credential},
          body:JSON.stringify({request_id:this.closeRequestId,pair:t.pair,amount:t.amount,open_timestamp:t.open_ts,is_short:!!t.is_short})
        });
        const result = await r.json();
        if (!r.ok) {
          this.closeMessage = typeof result.detail==='string' ? result.detail : 'Request rejected. Refresh the position before trying again.';
          if ([401,403,409,422,503].includes(r.status)) this.closeBusy = false;
          return;
        }
        this.closeMessage = result.state==='already_closed' ? 'This position is already closed.' : result.state==='accepted' ? 'Exit request accepted. Waiting for the bot to report the fill.' : 'Exit status is uncertain. Check the bot’s orders before taking further action.';
        // Keep submission disabled after accepted/uncertain responses. Refresh does not mean filled.
        await this.refresh();
      } catch (_) {
        this.closeMessage = 'Connection interrupted. The exit may have been submitted. Check the bot’s orders before trying again.';
      } finally { this.closePassword = ''; }
    },
    expandTrade(trade) {
      const id = this.tradeChartId(trade);
      this.expandedTrade = this.expandedTrade === id ? null : id;
      this.$nextTick(() => { this._scheduleChartResize(); document.getElementById(id)?.closest(".trade-card")?.scrollIntoView({block:"start"}); });
    },
    setTradeScale(trade, value) { this._tradeScale[this.tradeChartId(trade)] = value; this.renderTradeChart(trade); },
    tradeScale(trade) { return this._tradeScale[this.tradeChartId(trade)] || "price"; },
    _chartObservers: {},
    _chartResizeTimers: [],
    _equityData: {},
    _tradeCandles: {},
    _tradeChartState: {},
    _tradeChartRequest: {},
    _tradeChartsBusy: false,
    _killersSL: {},   // {symbol: posted channel SL} for copy-trader open positions
    _attentionExpanded: false,
    // Command bar: dismissed incident keys (session-local)
    _dismissedIncidents: new Set(),
    // Dry-run tab: which bot row is expanded
    _expandedDryBot: null,

    // ─── lifecycle ───
    boot() {
      const hash = location.hash.slice(1);
      this.tab = hash || 'live';

      this.tickClock();
      setInterval(() => this.tickClock(), 1000);
      this.fetchKillersSL();
      this.refresh().then(() => {
        this.equityBot = 'fleet';
        // Default the dry-run drawer to whichever bot is closest to graduation.
        // Falls back to first dry bot if no closest-to-gate ranking is available.
        this.selectedDryBot = this.closestToGate?.key || this.dryRunBots[0]?.key || null;
        this.fetchClosedTrades();
        this._renderTabFresh();
      });
      setInterval(() => this.refresh().then(() => {
        this.fetchClosedTrades();
        this.fetchKillersSL();
        this.$nextTick(() => this.renderCharts());
      }), this.pollInterval * 1000);
      window.addEventListener('hashchange', () => {
        const nextTab = location.hash.slice(1) || 'live';
        if (nextTab === this.tab) return;
        this.tab = nextTab;
        this._renderTabFresh();
      });
      window.addEventListener('resize', () => {
        this._scheduleChartResize();
      });
    },
    setTab(t) {
      if (this.tab === t) return;
      this.tab = t;
      location.hash = t === 'live' ? '' : t;
      this._renderTabFresh();
    },

    openPositionsTab() {
      this.tradesView = 'open';
      this.tradesFilter = 'all';
      this.setTab('trades');
    },
    openTradesHistory() {
      this.tradesView = 'closed';
      this.tradesFilter = 'all';
      this.setTab('trades');
    },
    setEquityBot(key) {
      this.equityBot = key || 'fleet';
      this.$nextTick(() => {
        this.renderEquity();
        this.renderDrawdown();
        this.renderPerPair();
        this._scheduleChartResize(['chart-equity', 'chart-drawdown', 'chart-perpair']);
      });
    },

    setTradesFilter(f) { this.tradesFilter = f; this.$nextTick(() => this.renderCharts()); },
    setTradesView(v) { this.tradesView = v; this.tradesFilter = 'all'; this.$nextTick(() => this.renderCharts()); },
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
      return this.bots.filter(b => b.dry_run === false)
        .sort((a, b) => (a.label||'').localeCompare(b.label||''));
    },
    get dryRunBots() {
      return this.bots.filter(b => b.dry_run === true)
        .sort((a, b) => (a.label||'').localeCompare(b.label||''));
    },
    get allBots() {
      return [...this.bots].sort((a, b) => {
          if (a.dry_run !== b.dry_run) return a.dry_run ? 1 : -1;
          return (a.label||'').localeCompare(b.label||'');
        });
    },
    get activeBot() {
      if (!this.tab.startsWith('bot:')) return null;
      return this.raw.bots?.[this.tab.slice(4)] || null;
    },
    get liveAccountCount() {
      return new Set(this.liveBots.map(b => b.account_group || b.key)).size;
    },
    get liveVenueCount() {
      return new Set(this.liveBots.map(b => b.venue || 'binance')).size;
    },
    get binanceLiveBots() {
      return this.liveBots.filter(b => (b.venue || 'binance') === 'binance');
    },
    get hyperliquidLiveBots() {
      return this.liveBots.filter(b => b.venue === 'hyperliquid');
    },

    // ─── fleet-aggregated hero stats (Bug fix B2: defensive chaining throughout) ───
    get hero() {
      const live = this.liveBots;
      // Several strategies may share one exchange account. Count deployable
      // capital once per account_group while still adding every strategy's P&L.
      // Without this, Funding/Keltner/OI triple-count the same Binance wallet.
      const accounts = new Map();
      for (const b of live) {
        const group = b.account_group || b.key;
        const owned = b.wallet?.bot_owned ?? b.wallet?.starting_capital ?? 0;
        accounts.set(group, Math.max(accounts.get(group) ?? 0, owned));
      }
      const observed = this.raw.account_health;
      const walletNow = observed?.complete
        ? observed.equity
        : (observed ? null : [...accounts.values()].reduce((s, v) => s + v, 0));
      const totalPnl = live.reduce((s, b) => s + (b.pnl?.all_coin ?? 0), 0);
      const totalRealizedPnl = live.reduce((s, b) => s + (b.pnl?.closed ?? 0), 0);
      const totalUnrealizedPnl = live.reduce((s, b) => s + (b.pnl?.unrealized ?? ((b.pnl?.all_coin ?? 0) - (b.pnl?.closed ?? 0))), 0);
      const start = walletNow == null ? null : walletNow - totalPnl;
      const closedTrades = live.reduce((s, b) => s + (b.stats?.closed_trade_count ?? 0), 0);
      const totalWins = live.reduce((s, b) => s + (b.stats?.winning_trades ?? 0), 0);
      const totalLosses = live.reduce((s, b) => s + (b.stats?.losing_trades ?? 0), 0);
      const winRate = (totalWins + totalLosses) ? totalWins / (totalWins + totalLosses) : 0;
      const aggregateClosed = this.closedTrades;
      const grossProfit = live.reduce((s, b) => s + Number(b.stats?.gross_profit || 0), 0);
      const grossLoss = live.reduce((s, b) => s + Number(b.stats?.gross_loss || 0), 0);
      const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : null;
      const expectancyPerTrade = closedTrades > 0 ? totalRealizedPnl / closedTrades : null;
      const ddMax = live.length ? Math.max(...live.map(b => (b.stats?.max_drawdown ?? 0) * 100)) : 0;
      const ddCurrentPerBot = live.map(b => {
        const dd = b.drawdown_curve;
        return dd && dd.length ? dd[dd.length - 1][1] : 0;
      });
      const ddCurrent = ddCurrentPerBot.length ? Math.min(...ddCurrentPerBot) : 0;
      const ddBacktest = live.length
        ? Math.max(...live.map(b => b.baseline?.max_dd_pct || 0))
        : 0;
      const ddCap = ddBacktest * 1.5;
      const open = live.reduce((s, b) => s + (b.open_trades || []).length, 0);
      const openNotional = live.reduce((s, b) => s + (b.open_trades || []).reduce((a, t) => a + (t.stake_amount || 0), 0), 0);
      const car = live.reduce((s, b) => s + (b.capital_at_risk?.abs_loss || 0), 0);
      const carPct = start ? (car / start * 100) : 0;

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
        concentration = live[0]?.concentration ?? null;
      }

      const allRecentTrades = aggregateClosed;
      const wins = allRecentTrades.filter(t => (t.profit_abs || 0) > 0);
      const losses = allRecentTrades.filter(t => (t.profit_abs || 0) < 0);
      const avgWin = wins.length ? wins.reduce((s, t) => s + t.profit_abs, 0) / wins.length : null;
      const avgLoss = losses.length ? losses.reduce((s, t) => s + t.profit_abs, 0) / losses.length : null;
      const payoff = avgLoss && avgLoss !== 0 ? Math.abs(avgWin / avgLoss) : null;

      return {
        walletNow, walletStart: start, totalPnl, totalRealizedPnl, totalUnrealizedPnl,
        totalPct: start ? (totalPnl / start * 100) : 0,
        closedTrades,
        winRate, profitFactor, expectancyPerTrade,
        expectancySample: closedTrades,
        drawdownMaxPct: ddMax, drawdownCurrentPct: ddCurrent,
        drawdownBacktest: ddBacktest, drawdownCap: ddCap,
        openCount: open, openNotional,
        capitalAtRisk: car, capitalAtRiskPct: carPct,
        concentration, avgWin, avgLoss, payoff,
      };
    },

    // ─── Command bar incidents ───
    // Full list (pre-dismiss)
    get _rawIncidents() {
      const items = [];
      const now = Date.now() / 1000;
      for (const warning of (this.raw.account_health?.warnings || [])) {
        items.push({color: 'amber', icon: '!', subject: warning,
          reason: 'Live request handling or account valuation needs attention.',
          cta: 'view portfolio', action: () => this.setTab('portfolio'), detailTab: 'portfolio'});
      }

      for (const b of this.liveBots) {
        for (const t of (b.open_trades || [])) {
          if ((t.profit_pct || 0) <= -3) {
            items.push({
              color: 'red', icon: '▼',
              subject: `${t.pair} unrealized ${this.fmtPctSigned(t.profit_pct)}`,
              reason: `${b.label} · open position · ${this.fmtAge(Math.max(0, Math.floor((Date.now() - toMs(t.open_timestamp)) / 1000)))} open`,
              cta: 'open detail',
              logsHint: b.links?.logs_hint || null,
              action: () => { this.setTab('live'); this.$nextTick(() => this.setOpenPos({ ...t, _bot: b.key })); },
              detailTab: 'live',
            });
          }
        }
      }

      const staleBots = this.raw.status?.stale_bots || [];
      for (const s of staleBots) {
        const key   = typeof s === 'string' ? s : (s.key || s.bot_key || '');
        const meta  = key ? this.raw.bots?.[key] : null;
        const label = (typeof s === 'object' && s.label) || meta?.label || meta?.name || key || 'unknown';
        const stale = (typeof s === 'object' && s.stale_hours) ? s.stale_hours + 'h ago' : 'unknown';
        items.push({
          color: 'red', icon: '!',
          subject: `${label} bot stale`,
          reason: `last seen ${stale} · check container`,
          cta: 'check logs',
          logsHint: meta?.links?.logs_hint || null,
          action: () => { if (key && this.allBots.find(b => b.key === key)) this.setTab('bot:' + key); },
          detailTab: key ? 'bot:' + key : null,
        });
      }

      for (const b of [...this.liveBots, ...this.dryRunBots]) {
        if (b.delta_24h?.dd_breach) {
          items.push({
            color: 'amber', icon: '⚠',
            subject: `${b.label} DD breach last 24h`,
            reason: `drawdown exceeded 1.5× backtest cap`,
            cta: 'view bot',
            logsHint: b.links?.logs_hint || null,
            action: () => { this.setTab(b.dry_run ? 'dryrun' : 'live'); },
            detailTab: b.dry_run ? 'dryrun' : 'live',
          });
        }
      }

      for (const b of this.liveBots) {
        if (b.position_integrity?.status === 'critical') {
          const issue = b.position_integrity.issues?.[0];
          items.push({
            color: 'red', icon: '!',
            subject: `${b.label} has a phantom dry-run trade`,
            reason: `${issue?.pair || 'unknown pair'} · simulated record inherited by live bot · excluded from P&L`,
            cta: 'inspect bot', logsHint: b.links?.logs_hint || null,
            action: () => this.setTab('bot:' + b.key), detailTab: 'bot:' + b.key,
          });
        }
        if (b.native_stop?.status === 'missing') {
          items.push({
            color: 'red', icon: '!',
            subject: `${b.label} native stop missing`,
            reason: b.native_stop.detail || 'open Hyperliquid position has no visible exchange stop',
            cta: 'inspect bot', logsHint: b.links?.logs_hint || null,
            action: () => this.setTab('bot:' + b.key), detailTab: 'bot:' + b.key,
          });
        }
        if (b.readiness && b.readiness.healthy === false) {
          items.push({
            color: 'amber', icon: '◷',
            subject: `${b.label} signal feed unavailable`,
            reason: b.readiness.error || b.readiness.detail || 'entry telemetry is stale',
            cta: 'inspect bot', logsHint: b.links?.logs_hint || null,
            action: () => this.setTab('bot:' + b.key), detailTab: 'bot:' + b.key,
          });
        }
        if (b.history?.complete === false) {
          items.push({
            color: 'amber', icon: '!',
            subject: `${b.label} epoch ledger incomplete`,
            reason: b.history.error || 'trade pagination did not reach the epoch boundary',
            cta: 'inspect bot', logsHint: b.links?.logs_hint || null,
            action: () => this.setTab('bot:' + b.key), detailTab: 'bot:' + b.key,
          });
        }
      }

      for (const b of this.dryRunBots) {
        const pct = b.gate1?.trades?.pct ?? 0;
        const remaining = (b.gate1?.trades?.target ?? 30) - (b.gate1?.trades?.actual ?? 0);
        if (pct >= 80 && remaining > 0) {
          items.push({
            color: 'amber', icon: '◷',
            subject: `${b.label} needs ${remaining} more trade${remaining !== 1 ? 's' : ''} to gate-1`,
            reason: `${Math.round(pct)}% of sample threshold reached`,
            cta: 'view progress',
            logsHint: null,
            action: () => { this.setTab('dryrun'); },
            detailTab: 'dryrun',
          });
        }
      }


      return items;
    },
    get observationNotices() {
      return this.dryRunBots.filter(b => b.observational && !b.baseline?.profit_factor);
    },
    get attentionItems() {
      return this._rawIncidents.filter(item => !this._dismissedIncidents.has(item.subject));
    },
    // Legacy alias used in some computed paths
    get attentionVisible() {
      const items = this.attentionItems;
      if (this._attentionExpanded || items.length <= 3) return items;
      return items.slice(0, 3);
    },
    dismissIncident(subject) {
      this._dismissedIncidents = new Set([...this._dismissedIncidents, subject]);
    },

    // expanded incident tracking
    _expandedIncident: null,
    toggleIncident(subject) {
      this._expandedIncident = this._expandedIncident === subject ? null : subject;
    },

    // ─── last closed trade (for last-closed-trade fallback in open positions panel) ───
    get lastFleetClosedTrade() {
      const trades = this.liveBots.flatMap(b => (b.recent_trades || []).filter(t => !t.is_open));
      if (!trades.length) return null;
      return [...trades].sort((a, b) => (b.close_timestamp || 0) - (a.close_timestamp || 0))[0];
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
    },
    get openPos() {
      const list = this.openPositions;
      if (!list.length) return null;
      if (this.openPosKey) {
        const match = list.find(p => (p._bot + ':' + p.pair) === this.openPosKey);
        if (match) return match;
      }
      const sorted = [...list].sort((a, b) => (toMs(b.open_timestamp) || 0) - (toMs(a.open_timestamp) || 0));
      return sorted[0];
    },
    get openPosAge() {
      const ts = this.openPos?.open_timestamp;
      if (!ts) return 0;
      return Math.max(0, Math.floor((Date.now() - toMs(ts)) / 1000));
    },
    get recentLiveTrades() {
      const live = this.liveBots;
      return live.flatMap(bot => (bot.recent_trades || []).map(trade => ({
        ...trade,
        _bot: bot.key,
        _botLabel: bot.label,
      }))).sort((a, b) => (b.close_timestamp || 0) - (a.close_timestamp || 0)).slice(0, 30);
    },
    get statusLabel() {
      if (!this.raw.last_poll) return 'connecting';
      const age = Date.now() / 1000 - this.raw.last_poll;
      if (age > 120) return 'stale';
      if (this.raw.status?.level === 'red') return 'incident';
      if (this.raw.status?.level === 'yellow') return 'degraded';
      if (Object.keys(this.raw.errors || {}).length) return 'partial';
      return 'live';
    },
    get staleClass() {
      if (!this.raw.last_poll) return 'warn';
      const age = Date.now() / 1000 - this.raw.last_poll;
      if (age > 120) return 'err';
      if (this.raw.status?.level === 'red') return 'err';
      if (this.raw.status?.level === 'yellow') return 'warn';
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

    isBotStale(bot) {
      const stale = this.raw.status?.stale_bots || [];
      return stale.some(item => (typeof item === 'string' ? item : (item.key || item.bot_key)) === bot.key);
    },
    botStatus(bot) {
      if (!bot?.reachable) return { label: 'unreachable', cls: 'offline' };
      if (this.isBotStale(bot)) return { label: 'stale', cls: 'stale' };
      if (bot.position_integrity?.status === 'critical') return { label: 'position fault', cls: 'offline' };
      return { label: 'running', cls: 'running' };
    },
    botActivity(bot) {
      if (!bot?.reachable) return 'Last known state · reconnecting';
      const open = bot?.open_trades?.length || 0;
      if (open) return `managing ${open} open position${open === 1 ? '' : 's'}`;
      if (bot?.readiness?.label) return bot.readiness.label;
      const last = this.lastClosedTrade(bot);
      if (last?.close_timestamp) {
        const age = Math.max(0, Math.floor((Date.now() - toMs(last.close_timestamp)) / 1000));
        return `last trade ${this.fmtAge(age)} ago`;
      }
      if ((bot?.days_running ?? 0) < 1) return 'fresh live epoch · scanning';
      return 'scanning · waiting for signal';
    },
    readinessDetail(bot) {
      return bot?.readiness?.detail || bot?.readiness?.gate || 'waiting for entry conditions';
    },
    readinessTone(bot) {
      const status = bot?.readiness?.status;
      if (['unavailable', 'stale'].includes(status)) return 'bad';
      if (['warming', 'blocked'].includes(status)) return 'warn';
      return 'good';
    },
    stopTone(bot) {
      if (bot?.native_stop?.status === 'missing') return 'bad';
      if (['awaiting-first-fill', 'awaiting-fill', 'awaiting-stop', 'no-open-position'].includes(bot?.native_stop?.status)) return 'pending';
      return bot?.native_stop?.status === 'verified' ? 'good' : 'pending';
    },
    fmtEpoch(bot) {
      const ts = bot?.epoch?.start_ts_ms;
      if (!ts) return bot?.epoch?.label || 'current epoch';
      return `${bot.epoch.label || 'Epoch label unavailable'} · since ${new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })}`;
    },
    venueLabel(bot) {
      return bot?.venue === 'hyperliquid' ? 'Hyperliquid perps' : 'Binance spot';
    },
    accountLabel(bot) {
      return bot?.account_group === 'binance-spot' ? 'shared wallet' : 'dedicated account';
    },
    strategyKindLabel(bot) {
      return bot?.strategy_kind === 'copy-trader' ? 'copy-trader' : 'autonomous quant';
    },
    botCapitalLabel(bot) {
      return bot?.account_group === 'binance-spot' ? 'shared capital' : 'bot capital';
    },
    botHasHistory(bot) {
      return (bot?.stats?.closed_trade_count || 0) > 0 || (bot?.open_trades?.length || 0) > 0;
    },
    get selectedEquityBot() {
      return this.equityBot === 'fleet' ? null : (this.raw.bots?.[this.equityBot] || null);
    },
    get equitySelectionLabel() {
      return this.selectedEquityBot?.label || 'fleet';
    },
    botCapital(bot) {
      const account = this.raw.account_health?.accounts?.[bot.account_group];
      if (!bot.dry_run && bot.account_group !== 'binance-spot' && account) return account.equity;
      return bot.wallet?.bot_owned;
    },
    get equityTitle() {
      return this.selectedEquityBot ? `${this.selectedEquityBot.label} equity` : 'Portfolio equity';
    },
    get equitySubtitle() {
      const bot = this.selectedEquityBot;
      if (!bot) return 'Realized equity over time · current equity shown separately';
      if (bot.lineage) return this.equityExplanation(bot);
      if (bot.baseline?.annual_return_pct) return 'Realized live equity · current equity shown separately';
      return 'Realized live equity · current equity shown separately';
    },
    equityExplanation(bot) {
      const closed = bot?.stats?.closed_trade_count || 0;
      return `Historical dry-run + rebased live returns · comparison scale, not account balance. ${closed ? closed + ' closed live trades' : 'No closed live trades: solid line stays flat'}; current equity snapshot includes open P&L.`;
    },
    get equityHasHistory() {
      return this.selectedEquityBot
        ? Boolean(this.selectedEquityBot.lineage) || (this.selectedEquityBot.stats?.closed_trade_count || 0) > 0
          || (this.selectedEquityBot.open_trades?.length || 0) > 0
        : this.hero.closedTrades > 0 || this.hero.openCount > 0;
    },
    get selectedPnl() {
      return this.selectedEquityBot?.pnl?.all_coin ?? this.hero.totalPnl;
    },
    get selectedRealizedPnl() {
      return this.selectedEquityBot?.pnl?.closed ?? this.hero.totalRealizedPnl;
    },
    get selectedUnrealizedPnl() {
      const bot = this.selectedEquityBot;
      return bot
        ? (bot.pnl?.unrealized ?? ((bot.pnl?.all_coin ?? 0) - (bot.pnl?.closed ?? 0)))
        : this.hero.totalUnrealizedPnl;
    },
    get selectedReturn() {
      return this.selectedEquityBot ? this.selectedEquityBot.pnl?.all_pct : this.hero.totalPct;
    },
    get selectedMaxDrawdown() {
      return this.selectedEquityBot
        ? (this.selectedEquityBot.stats?.max_drawdown || 0) * 100
        : this.hero.drawdownMaxPct;
    },
    get selectedClosedTrades() {
      return this.selectedEquityBot?.stats?.closed_trade_count ?? this.hero.closedTrades;
    },
    get selectedWinRate() {
      return this.selectedEquityBot?.stats?.winrate ?? this.hero.winRate;
    },
    get selectedProfitFactor() {
      return this.selectedEquityBot
        ? this.selectedEquityBot.stats?.profit_factor
        : this.hero.profitFactor;
    },
    get selectedConcentration() {
      return this.selectedEquityBot?.concentration || (this.selectedEquityBot ? null : this.hero.concentration);
    },
    get selectedExpectancy() {
      const bot = this.selectedEquityBot;
      if (bot) {
        const sample = bot.expectancy?.sample || bot.stats?.closed_trade_count || 0;
        return {
          sample,
          avgWin: sample ? (bot.expectancy?.avg_win ?? null) : null,
          avgLoss: sample ? (bot.expectancy?.avg_loss ?? null) : null,
          payoff: sample ? (bot.expectancy?.payoff ?? null) : null,
          perTrade: sample ? (bot.expectancy?.expectancy ?? null) : null,
        };
      }
      return {
        sample: this.hero.expectancySample,
        avgWin: this.hero.avgWin,
        avgLoss: this.hero.avgLoss,
        payoff: this.hero.payoff,
        perTrade: this.hero.expectancyPerTrade,
      };
    },
    get fleetPerformanceData() {
      const trades = this.closedTrades
        .filter(t => t.close_ts)
        .map(t => ({ ...t, close_timestamp: t.close_ts, _bot: t.bot_key }))
        .sort((a, b) => toMs(a.close_timestamp) - toMs(b.close_timestamp));
      const start = this.hero.walletStart || this.hero.walletNow || 0;
      let equity = start;
      const epochStarts = this.liveBots.map(bot => toMs(bot.epoch?.start_ts_ms || 0)).filter(Boolean);
      const openStarts = this.openPositions.map(position => toMs(position.open_timestamp || 0)).filter(Boolean);
      const firstTs = trades.length
        ? toMs(trades[0].close_timestamp)
        : Math.min(...[...epochStarts, ...openStarts, Date.now()]);
      const live = [[Math.max(0, firstTs - 1000), Number(start.toFixed(4))]];
      const drawdown = [[Math.max(0, firstTs - 1000), 0]];
      let peak = start;
      for (const trade of trades) {
        equity += Number(trade.profit_abs || 0);
        peak = Math.max(peak, equity);
        const dd = peak > 0 ? (equity - peak) / peak * 100 : 0;
        const ts = toMs(trade.close_timestamp);
        live.push([ts, Number(equity.toFixed(4))]);
        drawdown.push([ts, Number(dd.toFixed(4))]);
      }
      const realized = live.map(point => [...point]);
      const drawdownRealized = drawdown.map(point => [...point]);
      if (this.hero.openCount > 0) {
        equity += this.hero.totalUnrealizedPnl;
        peak = Math.max(peak, equity);
        const now = Date.now();
        const dd = peak > 0 ? (equity - peak) / peak * 100 : 0;
        live.push([now, Number(equity.toFixed(4))]);
        drawdown.push([now, Number(dd.toFixed(4))]);
      }
      return { live, realized, drawdown, drawdownRealized, trades, hasOpenMark: this.hero.openCount > 0 };
    },

    get portfolioAccounts() {
      const accounts = new Map();
      for (const bot of this.liveBots) {
        const key = bot.account_group || bot.key;
        const current = accounts.get(key) || {
          key,
          venue: bot.venue || 'binance',
          capital: 0,
          pnl: 0,
          atRisk: 0,
          open: 0,
          bots: [],
        };
        current.capital = Math.max(current.capital, Number(bot.wallet?.bot_owned ?? bot.wallet?.starting_capital ?? 0));
        current.pnl += Number(bot.pnl?.all_coin || 0);
        current.atRisk += Number(bot.capital_at_risk?.abs_loss || 0);
        current.open += bot.open_trades?.length || 0;
        current.bots.push(bot.label);
        accounts.set(key, current);
      }
      return [...accounts.values()]
        .map(account => ({
          ...account,
          free: this.raw.account_health?.accounts?.[account.key]?.free,
          margin: this.raw.account_health?.accounts?.[account.key]?.margin,
          notional: this.raw.account_health?.accounts?.[account.key]?.notional,
          capital: this.raw.account_health?.accounts?.[account.key]?.equity
            ?? (this.raw.account_health ? null : account.capital),
          label: account.key === 'binance-spot'
            ? 'Binance spot'
            : (account.bots.length === 1 ? account.bots[0] : account.key),
          weight: this.hero.walletNow ? (this.raw.account_health?.accounts?.[account.key]?.equity ?? account.capital) / this.hero.walletNow * 100 : 0,
        }))
        .sort((a, b) => b.capital - a.capital);
    },

    get portfolioVenues() {
      const venues = new Map();
      for (const account of this.portfolioAccounts) {
        const key = account.venue === 'hyperliquid' ? 'Hyperliquid perps' : 'Binance spot';
        const current = venues.get(key) || { label: key, capital: 0, pnl: 0, accounts: 0, bots: 0 };
        current.capital += account.capital;
        current.pnl += account.pnl;
        current.accounts += 1;
        current.bots += account.bots.length;
        venues.set(key, current);
      }
      return [...venues.values()].sort((a, b) => b.capital - a.capital);
    },

    get portfolioStrategyRows() {
      return this.liveBots.map(bot => ({
        key: bot.key,
        label: bot.label,
        realized: Number(bot.pnl?.closed || 0),
        unrealized: Number(bot.pnl?.unrealized ?? ((bot.pnl?.all_coin || 0) - (bot.pnl?.closed || 0))),
        pnl: Number(bot.pnl?.all_coin || 0),
        trades: bot.stats?.closed_trade_count || 0,
        open: bot.open_trades?.length || 0,
      })).sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
    },

    get portfolioPairRows() {
      const pairs = new Map();
      for (const bot of this.liveBots) {
        for (const row of bot.per_pair || []) {
          const current = pairs.get(row.pair) || { pair: row.pair, realized: 0, unrealized: 0, pnl: 0, trades: 0 };
          current.realized += Number(row.pnl || 0);
          current.trades += Number(row.count || row.trades || 0);
          pairs.set(row.pair, current);
        }
        for (const trade of bot.open_trades || []) {
          const current = pairs.get(trade.pair) || { pair: trade.pair, realized: 0, unrealized: 0, pnl: 0, trades: 0 };
          current.unrealized += Number(trade.profit_abs || 0);
          pairs.set(trade.pair, current);
        }
      }
      return [...pairs.values()]
        .map(row => ({ ...row, pnl: row.realized + row.unrealized }))
        .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
    },

    get portfolioDrawdownMax() {
      const values = this.fleetPerformanceData.drawdown.map(point => Number(point[1] || 0));
      return values.length ? Math.abs(Math.min(...values, 0)) : 0;
    },

    get portfolioCurrentDrawdown() {
      const rows = this.fleetPerformanceData.drawdown;
      return rows.length ? Number(rows[rows.length - 1][1] || 0) : 0;
    },

    // ─── last closed trade for a bot ───
    lastClosedTrade(bot) {
      const trades = (bot.recent_trades || []).filter(t => !t.is_open);
      if (!trades.length) return null;
      return [...trades].sort((a, b) => (b.close_timestamp || 0) - (a.close_timestamp || 0))[0];
    },

    // Bug fix B4: pfDelta as number not string
    deviationSummary(bot) {
      const btPf = bot.baseline?.profit_factor ?? null;
      const livePf = bot.stats?.profit_factor ?? null;
      if (livePf == null || btPf == null || btPf === 0) return null;
      // Bug fix B4: convert to number before comparison
      const pfDelta = Math.round((livePf - btPf) / btPf * 100);
      const sign = pfDelta >= 0 ? '+' : '';
      const withinBand = Math.abs(pfDelta) <= 20 ? '— within ±20% band' : '— OUTSIDE ±20% band';
      return `${bot.label}: live PF ${livePf.toFixed(2)} is ${sign}${pfDelta}% vs backtest ${btPf} ${withinBand}`;
    },

    openTradesForBot(bot) {
      return (bot.open_trades || []).map(t => {
        // Bug fix B3: use toMs() for age calculation
        const ageMin = t.open_timestamp ? Math.round((Date.now() - toMs(t.open_timestamp)) / 60000) : 0;
        return { ...t, ageMin };
      });
    },

    // ─── dry-run graduation board helpers ───
    dryBotVerdict(bot) {
      if (bot.no_baseline || bot.observational) return { text: 'observational', cls: 'obs' };
      const g1 = bot.gate1 ? Object.values(bot.gate1).every(x => x.ok) : false;
      const g2 = bot.gate2 ? ['profit', 'pf', 'dd'].every(k =>
        bot.gate2[k]?.status === 'ok' || bot.gate2[k]?.status === 'n/a') : false;
      const g3 = bot.gate3 ? Object.values(bot.gate3).every(x => x.ok) : false;
      if (g1 && g2 && g3) return { text: 'ready', cls: 'ready' };
      if (g1) return { text: 'watch', cls: 'watch' };
      return { text: 'not ready', cls: '' };
    },
    dryBotBlocker(bot) {
      if (bot.no_baseline || bot.observational) return 'observational · monitoring only';
      if (!bot.gate1) return '—';
      const t = bot.gate1.trades;
      const remaining = (t?.target ?? 30) - (t?.actual ?? 0);
      if (remaining > 0) return `${remaining} more trades to gate-1`;
      if (!bot.gate2) return 'gate-2 pending data';
      const pfStatus = bot.gate2.pf?.status;
      if (pfStatus === 'breach') return 'PF outside ±20% band';
      const ddStatus = bot.gate2.dd?.status;
      if (ddStatus === 'breach') return 'DD breach';
      return 'gate-3 check';
    },
    get closestToGate() {
      const nonObs = this.dryRunBots.filter(b => !b.no_baseline && !b.observational);
      if (!nonObs.length) return null;
      // Sort by gate-1 trades pct descending
      return [...nonObs].sort((a, b) => (b.gate1?.trades?.pct ?? 0) - (a.gate1?.trades?.pct ?? 0))[0];
    },
    get selectedDryBotObj() {
      if (!this.selectedDryBot) return null;
      return this.dryRunBots.find(b => b.key === this.selectedDryBot) || null;
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
    // Bug fix B1: fmtPctSigned already appends %, do NOT add extra '%'
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
    // Defensive: observational bots (no_baseline) have null gates — caller
    // hides this via x-show, but Alpine still evaluates the expression, so
    // we need to short-circuit here too.
    readyVerdict(bot) {
      if (!bot?.gate1 || !bot?.gate2 || !bot?.gate3) return { text: 'observational', cls: '' };
      const g1 = Object.values(bot.gate1).every(x => x?.ok);
      const g2 = ['profit', 'pf', 'dd'].every(k =>
        bot.gate2[k]?.status === 'ok' || bot.gate2[k]?.status === 'n/a');
      const g3 = Object.values(bot.gate3).every(x => x?.ok);
      if (g1 && g2 && g3) return { text: 'ready to flip', cls: 'ready' };
      if (g1) return { text: 'gate-1 cleared · band watch', cls: 'watch' };
      return { text: 'not ready', cls: '' };
    },
    etaToGate1(bot) {
      const need = 30 - (bot.stats?.closed_trade_count ?? 0);
      if (need <= 0) return 'cleared';
      if (!bot.stats?.closed_trade_count || !bot.days_running) return 'idle';
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
      if (!window.TradingAnalytics) { setTimeout(() => this.renderCharts(), 100); return; }
      const t = this.tab;
      if (t === 'live') {
        this.renderEquity();
        this.renderDrawdown();
        this.renderPerPair();

      } else if (t === 'portfolio') {
        this.renderPortfolioCharts();
      } else if (t === 'dryrun') {
        this.dryRunBots.forEach(b => this.renderBotEquity(b.key));
        if (this._expandedDryBot) {
          this.renderDetailCharts(this._expandedDryBot);
        }
      } else if (t === 'trades') {
        this.renderTradesCharts();
      } else if (t.startsWith('bot:')) {
        const key = t.slice(4);
        this.renderDetailCharts(key);
      }
      this._scheduleChartResize();
    },

    // ─── trades tab ───
    // Open positions across the whole fleet, shaped to mirror a closed-trade
    // record so the same card template + chart renderer can draw them.
    // `close_rate`/`close_ts` stand in as the live current price / "now" so
    // the chart spans entry → now. No exit/stop lines (is_open branches those).
    get openTradesAll() {
      const now = Date.now();
      const out = [];
      for (const b of this.allBots) {
        for (const t of (b.open_trades || [])) {
          const openMs = toMs(t.open_timestamp || 0);
          // Copy-trader posted stops are also exchange resident. Prefer the
          // channel's exact level when available; retain Freqtrade's observed
          // stop as the fallback for every bot.
          // Only the killers copy-trader has channel-posted SLs — gate on its
          // exact key (short-keltner-hl is also observational but has none).
          // Best-effort match: latest OPEN signal per symbol; aliased bases
          // (e.g. 1000PEPE vs channel PEPE) just fall back to the Freqtrade
          // stop. The exact position→signal SL lives in the receiver DB, which
          // the dashboard doesn't mount.
          const sym = String(t.pair || '').split('/')[0];
          const postedSL = (b.key === 'killers-ft') ? this._killersSL[sym] : null;
          const ftStop = (typeof t.stop_loss_abs === 'number' && t.stop_loss_abs > 0) ? t.stop_loss_abs : null;
          const stopIsPosted = (typeof postedSL === 'number' && postedSL > 0);
          out.push({
            bot_key: b.key, bot_name: b.name, pair: t.pair, dry_run: b.dry_run, trade_id: t.trade_id, amount: t.amount,
            open_rate: t.open_rate, close_rate: t.current_rate,
            open_ts: t.open_timestamp, close_ts: now,
            profit_pct: t.profit_pct, profit_abs: t.profit_abs,
            is_win: (t.profit_abs || 0) > 0, is_open: true,
            stop_rate: ftStop,
            is_short: t.is_short,
            exit_levels: (t.exit_levels || []).filter(x => ["active","pending","unknown","placing","blocked","rejected"].includes(x.state)),
            stop_is_posted: false,
            stoploss_pct: t.stop_loss_pct,
            duration_min: openMs ? Math.round((now - openMs) / 60000) : 0,
            booked_pct: t.booked_pct ?? null,
            riding_pct: t.riding_pct ?? null,
            tps_total: t.tps_total ?? null,
            tps_hit: t.tps_hit ?? null,
            next_tp: t.next_tp ?? null,
          });
        }
      }
      return out.sort((a, b) => toMs(b.open_ts) - toMs(a.open_ts));
    },
    get filteredTrades() {
      let trades = this.tradesView === 'open' ? this.openTradesAll : this.closedTrades;
      if (this.tradesView === 'closed' && this.tradesFilter === 'recent24h') {
        const cutoff = Date.now() - 24 * 3600 * 1000;
        trades = trades.filter(t => toMs(t.close_ts) > cutoff);
      } else if (this.tradesFilter !== 'all' && this.tradesFilter !== 'recent24h') {
        trades = trades.filter(t => t.bot_key === this.tradesFilter);
      }
      return trades;
    },
    get tradesWinRate() {
      const f = this.filteredTrades;
      if (!f.length) return '—';
      return ((f.filter(t => t.is_win).length / f.length) * 100).toFixed(1);
    },
    get tradesTotalPnl() {
      return this.filteredTrades.reduce((s, t) => s + (t.profit_abs || 0), 0);
    },
    get tradeDataIncomplete() {
      return Object.keys(this.raw.errors || {}).length > 0;
    },
    get tradesRecentSummary() {
      const f = this.filteredTrades;
      const wr = f.length ? ((f.filter(t => t.is_win).length / f.length) * 100).toFixed(0) : 0;
      const pnl = f.reduce((s, t) => s + (t.profit_abs || 0), 0);
      const pnlStr = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
      if (this.tradesView === 'open') {
        return this.tradeDataIncomplete ? `${f.length} observed positions · awaiting unavailable bots` : `${f.length} open position${f.length === 1 ? '' : 's'} · unrealized ${pnlStr}`;
      }
      // estimate days window for the filter
      if (this.tradesFilter === 'recent24h') {
        return `${f.length} closed trades · last 24h · win ${wr}% · ${pnlStr}`;
      }
      return `${f.length} closed trades · win ${wr}% · ${pnlStr}`;
    },
    formatTradeWindow(trade) {
      if (!trade.open_ts) return '';
      const open = new Date(toMs(trade.open_ts));
      const dur = trade.duration_min;
      const day = open.getUTCMonth() + 1 + '-' + String(open.getUTCDate()).padStart(2, '0');
      const hh = String(open.getUTCHours()).padStart(2, '0') + ':' + String(open.getUTCMinutes()).padStart(2, '0');
      const durStr = dur ? (dur < 60 ? dur + 'm' : (dur / 60).toFixed(1) + 'h') : '—';
      return `${day} ${hh} · ${durStr}`;
    },
    _tradeKey(trade) { return trade.bot_key + ':' + trade.pair + ':' + trade.open_ts; },
    // DOM id for a trade's chart — includes a sanitized pair so two trades a
    // bot opens in the same ms (different pairs) don't collide on bot+open_ts.
    tradeChartId(trade) { return 'trade-chart-' + trade.bot_key + '-' + trade.open_ts + '-' + String(trade.pair || '').replace(/[^A-Za-z0-9]/g, ''); },
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

    async fetchKillersSL() {
      // Posted channel stop-loss per symbol for copy-trader open positions.
      try {
        const r = await fetch('/api/killers/state', { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        this._killersSL = data.posted_sl || {};
        // SL map may arrive after the first chart render → repaint open cards.
        if (this.tab === 'trades' && this.tradesView === 'open') this.$nextTick(() => this.renderTradesCharts());
      } catch (e) { console.warn('fetchKillersSL', e); }
    },

    async fetchClosedTrades() {
      try {
        const r = await fetch('/api/closed_trades', { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        this.closedTrades = data.trades || [];
        if (this.tab === 'trades') this.$nextTick(() => this.renderTradesCharts());
        if (this.tab === 'live' || this.tab === 'portfolio') this.$nextTick(() => this.renderCharts());
      } catch (e) { console.warn('fetchClosedTrades', e); }
    },

    async renderTradesCharts() {
      if (this._tradeChartsBusy) return;
      this._tradeChartsBusy = true;
      try {
        for (const trade of this.filteredTrades) {
          try { await this.renderTradeChart(trade); }
          catch (error) {
            this._tradeChartState[this.tradeChartId(trade)] = { error: 'Price chart unavailable. Retry shortly.' };
            console.warn('renderTradeChart', trade.pair, error?.message);
          }
        }
      } finally { this._tradeChartsBusy = false; }
    },
    focusTradeEntry(trade) { charts[this.tradeChartId(trade)]?.focusEntry(); },

    tradeChartStatus(trade) { return this._tradeChartState[this.tradeChartId(trade)] || { loading: true }; },
    retryTradeChart(trade) {
      const prefix = trade.bot_key + ':' + trade.pair + ':';
      Object.keys(this._tradeCandles).filter(k => k.startsWith(prefix)).forEach(k => delete this._tradeCandles[k]);
      this.renderTradeChart(trade);
    },

    async renderTradeChart(trade) {
      const chartId = this.tradeChartId(trade);
      const tf = this.tradeTimeframe(trade);
      const request = (this._tradeChartRequest[chartId] || 0) + 1;
      this._tradeChartRequest[chartId] = request;
      this._tradeChartState[chartId] = { loading: true };
      // Key by open_ts too so distinct trades on the same bot/pair/tf (e.g. two
      // SUI scalps) don't share a window. Open trades skip the cache so the
      // chart keeps up with the live candle on each poll.
      const cacheKey = trade.bot_key + ':' + trade.pair + ':' + tf + ':' + trade.open_ts + ':' + (trade.is_open ? 'open' : 'closed');
      // Closed trades are immutable → cache forever. Open trades refresh on a
      // 60s TTL so the chart tracks the live candle without re-fetching Binance
      // on every tab switch / 30s poll (the over-fetch caused intermittent
      // blank charts when a fetch failed or was still in flight).
      const cached = this._tradeCandles[cacheKey];
      let candles = null;
      if (cached) {
        if (!trade.is_open) candles = cached.candles;
        else if (Date.now() - cached.ts < 60000) candles = cached.candles;
      }
      if (!candles) {
        try {
          const tfMs = { '5m': 5*60_000, '15m': 15*60_000, '1h': 60*60_000, '4h': 4*60*60_000 }[tf] || 60*60_000;
          const padCandles = 100;
          // Bug fix B3: use toMs for open_ts / close_ts
          const endMs = Math.min(Date.now(), toMs(trade.close_ts) + padCandles * tfMs);
          const startMs = Math.max(toMs(trade.open_ts) - padCandles * tfMs, endMs - 499 * tfMs);
          const url = `/api/trade_candles/${encodeURIComponent(trade.bot_key)}?pair=${encodeURIComponent(trade.pair)}&timeframe=${tf}&limit=500&start_ms=${startMs}&end_ms=${endMs}`;
          const r = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(95000) });
          if (!r.ok) throw new Error('Candles unavailable');
          const data = await r.json();
          candles = data.candles || [];
          this._tradeCandles[cacheKey] = { ts: Date.now(), candles };
        } catch {
          if (this._tradeChartRequest[chartId] === request) this._tradeChartState[chartId] = { error: 'Price chart unavailable. Retry shortly.' };
          return;
        }
      }
      if (this._tradeChartRequest[chartId] !== request) return;
      if (!candles.length) {
        this._tradeChartState[chartId] = { error: 'No candles in this window. Try a longer timeframe.' };
        return;
      }
      this._tradeChartState[chartId] = { loading: false, clipped: candles[0][0] > toMs(trade.open_ts) };

      const el = document.getElementById(chartId);
      if (!el || !window.TradingPriceChart) return;
      if (charts[chartId] && charts[chartId].getDom() !== el) { charts[chartId].dispose(); delete charts[chartId]; }
      if (!charts[chartId]) charts[chartId] = new window.TradingPriceChart(el);
      charts[chartId].render(candles, trade, tf, this.tradeScale(trade));
      charts[chartId].resize();
    },

    _resizeChart(id, chart = charts[id]) {
      const el = document.getElementById(id);
      if (!el || !chart || !el.isConnected || el.offsetParent === null) return;
      const rect = el.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      if (width < 120 || height < 80) return;
      try { chart.resize({ width, height, silent: true }); }
      catch (e) { console.warn('resize', id, e?.message); }
    },

    _disposeCharts() {
      this._chartResizeTimers.forEach(timer => clearTimeout(timer));
      this._chartResizeTimers = [];
      Object.values(this._chartObservers).forEach(observer => observer?.disconnect?.());
      this._chartObservers = {};
      Object.values(charts).forEach(chart => {
        try { chart?.dispose?.(); } catch {}
      });
      Object.keys(charts).forEach(id => delete charts[id]);
    },

    _renderTabFresh() {
      this.$nextTick(() => requestAnimationFrame(() => {
        // x-show must finish applying before the chart reads the destination
        // panel. Recreating here prevents a hidden tab's 0px coordinate grid
        // from surviving after its canvas expands.
        this._disposeCharts();
        this.renderCharts();
        this._scheduleChartResize();
      }));
    },

    _scheduleChartResize(ids = null) {
      this._chartResizeTimers.forEach(timer => clearTimeout(timer));
      const resize = () => requestAnimationFrame(() => {
        const keys = ids || Object.keys(charts);
        keys.forEach(id => this._resizeChart(id));
      });
      resize();
      this._chartResizeTimers = [60, 240].map(delay => setTimeout(resize, delay));
    },

    _ensureChart(id) {
      const el = document.getElementById(id);
      if (!el) return null;
      const existing = charts[id];
      if (existing && existing.getDom?.() !== el) {
        this._chartObservers[id]?.disconnect?.();
        try { existing.dispose(); } catch {}
        delete charts[id];
      }
      if (!charts[id] || charts[id].isDisposed()) {
        const chart = new window.TradingAnalytics(el);
        if (typeof ResizeObserver !== 'undefined') {
          const ro = new ResizeObserver(entries => {
            const box = entries[0]?.contentRect;
            if (!box || box.width < 120 || box.height < 80) return;
            this._resizeChart(id, chart);
          });
          ro.observe(el);
          this._chartObservers[id]?.disconnect?.();
          this._chartObservers[id] = ro;
        }
        charts[id] = chart;
        this._scheduleChartResize([id]);
      }
      return charts[id];
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

    _equityView(id, data, bot = null, hasOpen = false) {
      const lineage = data?.lineage;
      const marked = lineage?.live || data?.live || [];
      const closed = closedEquityThroughMark(lineage?.realized || data?.realized || [], marked);
      const series = [];
      if (lineage?.legacy?.length) series.push({label: lineage.legacy_label || 'Historical paper', data: lineage.legacy, color: COLORS.text3});
      series.push({label: lineage ? `${lineage.live_label || 'Live'} · realized` : 'Realized equity', data: closed, color: COLORS.accent, step: true});
      const snapshot = hasOpen && marked.length ? {label:lineage?'Current rebased value · includes open P&L':'Current equity · includes open P&L', value:marked[marked.length-1][1]} : null;
      this._ensureChart(id)?.lines(series, {snapshot, note: lineage?.transition?.label || bot?.epoch?.label || '', empty:'Equity history not available yet'});
    },

    async renderEquity() {
      const key = this.equityBot || 'fleet';
      const bot = key === 'fleet' ? null : this.raw.bots[key];
      const data = key === 'fleet' ? this.fleetPerformanceData : await this._fetchEquity(key);
      this._equityView('chart-equity', data, bot, bot ? !!bot.open_trades?.length : this.hero.openCount > 0);
    },

    async renderDrawdown() {
      const key = this.equityBot || 'fleet';
      const data = key === 'fleet' ? this.fleetPerformanceData : this._equityData[key] || await this._fetchEquity(key);
      this._drawdownView('chart-drawdown', data, key === 'fleet' ? this.hero.drawdownBacktest : this.raw.bots[key]?.baseline?.max_dd_pct);
    },

    _drawdownView(id, data, reference) {
      this._ensureChart(id)?.lines([{label:'Drawdown',data:data?.lineage?.drawdown || data?.drawdown || [],color:COLORS.neg,step:true}], {percent:true, note:reference ? `Historical reference: −${Math.abs(reference).toFixed(2)}% · limit: −${(Math.abs(reference)*1.5).toFixed(2)}%` : '', empty:'Drawdown history not available yet'});
    },

    _pairRows(bots) {
      const pairs = new Map();
      for (const bot of bots) {
        for (const row of bot.per_pair || []) {
          const item = pairs.get(row.pair) || {label:row.pair, realized:0, unrealized:0};
          item.realized += Number(row.pnl || 0); pairs.set(row.pair,item);
        }
        for (const row of bot.open_trades || []) {
          const item = pairs.get(row.pair) || {label:row.pair, realized:0, unrealized:0};
          item.unrealized += Number(row.profit_abs || 0); pairs.set(row.pair,item);
        }
      }
      return [...pairs.values()].sort((a,b)=>Math.abs(b.realized+b.unrealized)-Math.abs(a.realized+a.unrealized)).slice(0,10);
    },

    renderPerPair() {
      this._ensureChart('chart-perpair')?.comparison(this._pairRows(this.selectedEquityBot ? [this.selectedEquityBot] : this.liveBots));
    },

    renderPortfolioCharts() {
      const data = this.fleetPerformanceData;
      this._equityView('chart-portfolio-equity',data,null,this.hero.openCount>0);
      this._drawdownView('chart-portfolio-dd',data);
      this._ensureChart('chart-portfolio-strategy')?.comparison(this.portfolioStrategyRows);
      this._ensureChart('chart-portfolio-pair')?.comparison(this.portfolioPairRows.map(row=>({...row,label:row.pair})));
      this._scheduleChartResize();
    },

    async renderBotEquity(key) {
      const data = await this._fetchEquity(key);
      this._equityView('chart-equity-'+key,data,this.raw.bots[key],!!this.raw.bots[key]?.open_trades?.length);
    },

    async renderDetailCharts(key) {
      const bot = this.raw.bots[key]; if (!bot) return;
      const data = await this._fetchEquity(key);
      this._equityView('chart-detail-equity-'+key,data,bot,!!bot.open_trades?.length);
      this._drawdownView('chart-detail-dd-'+key,data,bot.baseline?.max_dd_pct);
      this._ensureChart('chart-detail-pair-'+key)?.comparison(this._pairRows([bot]));
    },
  };
}
