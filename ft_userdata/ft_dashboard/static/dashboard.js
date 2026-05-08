/* dashboard.js — Alpine controller + ECharts panels for master-trader.
 *
 * Charts:
 *  - chart-equity     equity curve (live + scaled backtest expected)
 *  - chart-drawdown   underwater drawdown
 *  - chart-candles    open-position OHLC + entry + stop
 *  - chart-perpair    horizontal bars by pair
 *  - chart-equity-<k> per-bot dry-run equity overlay
 */

const COLORS = {
  pos: '#34d399', neg: '#f87171', warn: '#fbbf24',
  accent: '#22d3ee', accent2: '#a78bfa', info: '#60a5fa',
  text: '#e6ebf2', text2: '#a8b3c4', text3: '#6b7689',
  surface: '#131a26', surface2: '#1a2332', border: '#1f2a3c',
};

const ECHART_COMMON = {
  textStyle: { fontFamily: '"JetBrains Mono", ui-monospace, monospace', fontSize: 11, color: COLORS.text2 },
  backgroundColor: 'transparent',
  grid: { left: 50, right: 18, top: 28, bottom: 30, containLabel: false },
  axisPointer: { lineStyle: { color: COLORS.border, width: 1 } },
};

function dash() {
  return {
    raw: { bots: {}, errors: {}, last_poll: null },
    pollInterval: 30,
    tab: location.hash === '#dryrun' ? 'dryrun' : 'live',
    clock: '—',
    equityBot: null,
    _charts: {},
    _equityData: {},

    // ─── lifecycle ───
    boot() {
      this.tickClock();
      setInterval(() => this.tickClock(), 1000);
      this.refresh().then(() => {
        this.equityBot = this.liveBots[0]?.key || null;
        this.$nextTick(() => this.renderCharts());
      });
      setInterval(() => this.refresh().then(() => this.renderCharts()), this.pollInterval * 1000);
      window.addEventListener('hashchange', () => {
        this.tab = location.hash === '#dryrun' ? 'dryrun' : 'live';
        this.$nextTick(() => this.renderCharts());
      });
      window.addEventListener('resize', () => {
        Object.values(this._charts).forEach(c => c?.resize());
      });
      this.$watch('tab', () => this.$nextTick(() => this.renderCharts()));
    },
    setTab(t) { this.tab = t; location.hash = t === 'live' ? '' : '#dryrun'; },
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
        .sort((a, b) => a.label.localeCompare(b.label));
    },
    get hero() {
      const live = this.liveBots;
      const start = live.reduce((s, b) => s + b.wallet.starting_capital, 0);
      const owned = live.reduce((s, b) => s + b.wallet.bot_owned, 0);
      const closed = live.reduce((s, b) => s + b.pnl.closed, 0);
      const all = live.reduce((s, b) => s + b.pnl.all_coin, 0);
      const closedTrades = live.reduce((s, b) => s + b.stats.closed_trade_count, 0);
      const totalWins = live.reduce((s, b) => s + b.stats.winning_trades, 0);
      const totalLosses = live.reduce((s, b) => s + b.stats.losing_trades, 0);
      const winRate = (totalWins + totalLosses) ? totalWins / (totalWins + totalLosses) : 0;
      const dd = live.length ? Math.max(...live.map(b => b.stats.max_drawdown * 100)) : 0;
      const ddBacktest = live.length ? live[0].baseline.max_dd_pct : 0;
      const ddCap = ddBacktest * 1.5;
      const open = live.reduce((s, b) => s + b.open_trades.length, 0);
      const openNotional = live.reduce((s, b) => s + b.open_trades.reduce((a, t) => a + (t.stake_amount || 0), 0), 0);
      const car = live.reduce((s, b) => s + (b.capital_at_risk?.abs_loss || 0), 0);
      const carPct = start ? (car / start * 100) : 0;
      // first live bot for concentration + expectancy (single live bot today)
      const primary = live[0];
      return {
        walletNow: owned || start,
        walletStart: start,
        totalPnl: all,
        totalPct: start ? (all / start * 100) : 0,
        closedPnl: closed,
        closedTrades,
        winRate,
        profitFactor: primary?.stats.profit_factor,
        drawdownPct: dd,
        drawdownBacktest: ddBacktest,
        drawdownCap: ddCap,
        openCount: open,
        openNotional,
        capitalAtRisk: car,
        capitalAtRiskPct: carPct,
        concentration: primary?.concentration,
        avgWin: primary?.expectancy?.avg_win,
        avgLoss: primary?.expectancy?.avg_loss,
        payoff: primary?.expectancy?.payoff,
        expectancyPerTrade: primary?.expectancy?.expectancy,
        expectancySample: primary?.expectancy?.sample || 0,
      };
    },
    get openPos() {
      const live = this.liveBots;
      for (const b of live) {
        if (b.open_trades.length) return { ...b.open_trades[0], _bot: b.key };
      }
      return null;
    },
    get openPosAge() {
      if (!this.openPos?.open_timestamp) return 0;
      return Math.floor((Date.now() - this.openPos.open_timestamp) / 1000);
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

    // ─── formatters ───
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
      if (this.tab === 'live') {
        this.renderEquity();
        this.renderDrawdown();
        this.renderPerPair();
        this.renderCandles();
      } else {
        this.dryRunBots.forEach(b => this.renderBotEquity(b.key));
      }
    },

    _ensureChart(id) {
      const el = document.getElementById(id);
      if (!el) return null;
      if (!this._charts[id] || this._charts[id].isDisposed()) {
        this._charts[id] = echarts.init(el, null, { renderer: 'canvas' });
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
      const startTs = data?.bot_start_ts_ms || 0;
      const expectedRebased = (data?.expected || [])
        .filter(p => p[0] >= startTs)
        .map(p => [new Date(p[0]), p[1]]);
      // shift expected so it begins at the same equity as bot's starting capital at startTs
      const live = (data?.live || []).map(p => [new Date(p[0]), p[1]]);
      // Build trade markers
      const winMarks = [];
      const lossMarks = [];
      (bot.recent_trades || []).filter(t => !t.is_open).forEach(t => {
        if (!t.close_timestamp) return;
        const m = { name: t.exit_reason, value: [new Date(t.close_timestamp).toISOString(), null], pair: t.pair, pct: t.profit_pct, abs: t.profit_abs };
        if ((t.profit_abs || 0) >= 0) winMarks.push(m);
        else lossMarks.push(m);
      });
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis',
          backgroundColor: COLORS.surface2, borderColor: COLORS.border, borderWidth: 1,
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
          splitLine: { lineStyle: { color: COLORS.hairline || COLORS.border, type: 'dashed', opacity: 0.4 } },
          scale: true,
        },
        series: [
          {
            name: 'backtest expected',
            type: 'line', data: expectedRebased,
            showSymbol: false, lineStyle: { color: COLORS.text3, type: 'dashed', width: 1.2 },
            itemStyle: { color: COLORS.text3 }, z: 1,
          },
          {
            name: 'live equity',
            type: 'line', data: live, smooth: false, showSymbol: false,
            lineStyle: { color: COLORS.accent, width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(34, 211, 238, 0.25)' },
                { offset: 1, color: 'rgba(34, 211, 238, 0.0)' },
              ]),
            },
            itemStyle: { color: COLORS.accent },
            markPoint: {
              symbol: 'circle', symbolSize: 8,
              data: [
                ...winMarks.map(m => ({
                  coord: m.value, value: '↑', itemStyle: { color: COLORS.pos, borderColor: COLORS.bg },
                  label: { show: false },
                  tooltip: { formatter: () => `${m.pair} · ${m.pct?.toFixed(2)}%` },
                })),
                ...lossMarks.map(m => ({
                  coord: m.value, value: '↓', itemStyle: { color: COLORS.neg, borderColor: COLORS.bg },
                  label: { show: false },
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
          backgroundColor: COLORS.surface2, borderColor: COLORS.border, borderWidth: 1,
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
          type: 'value', max: 0,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '{value}%' },
          splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.4 } },
        },
        series: [{
          type: 'line', data: dd, showSymbol: false, smooth: false,
          lineStyle: { color: COLORS.neg, width: 1.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(248, 113, 113, 0.0)' },
              { offset: 1, color: 'rgba(248, 113, 113, 0.35)' },
            ]),
          },
          markLine: {
            silent: true, symbol: 'none',
            lineStyle: { color: COLORS.warn, type: 'dashed', width: 1 },
            data: [{ yAxis: ddCap, label: { show: true, formatter: 'cap ' + ddCap.toFixed(1) + '%', color: COLORS.warn, fontSize: 10 } }],
          },
        }],
      }, true);
    },

    renderPerPair() {
      const chart = this._ensureChart('chart-perpair');
      if (!chart) return;
      const live = this.liveBots[0];
      const rows = (live?.per_pair || []).slice(0, 10);
      if (!rows.length) {
        chart.setOption({ ...ECHART_COMMON, series: [], xAxis: { type: 'value' }, yAxis: { type: 'category', data: [] } }, true);
        return;
      }
      const pairs = rows.map(r => r.pair);
      const pnls = rows.map(r => Number(r.pnl).toFixed(2));
      chart.setOption({
        ...ECHART_COMMON,
        animation: false,
        tooltip: {
          trigger: 'axis', axisPointer: { type: 'shadow' },
          backgroundColor: COLORS.surface2, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => '$' + Number(v).toFixed(2),
        },
        grid: { left: 70, right: 50, top: 12, bottom: 24 },
        xAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: COLORS.border } },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' },
          splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.3 } },
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
        chart.setOption({
          ...ECHART_COMMON,
          animation: false,
          tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: COLORS.border } },
            backgroundColor: COLORS.surface2, borderColor: COLORS.border, borderWidth: 1,
            textStyle: { color: COLORS.text, fontSize: 11 },
          },
          grid: { left: 55, right: 16, top: 16, bottom: 30 },
          xAxis: {
            type: 'category', data: dates,
            axisLine: { lineStyle: { color: COLORS.border } },
            axisLabel: { color: COLORS.text3, fontSize: 9, formatter: v => v.slice(5, 16).replace('T', ' ') },
          },
          yAxis: {
            scale: true,
            axisLine: { show: false }, axisTick: { show: false },
            axisLabel: { color: COLORS.text3, fontSize: 10 },
            splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.3 } },
          },
          series: [{
            type: 'candlestick', data: ohlc,
            itemStyle: {
              color: COLORS.pos, color0: COLORS.neg,
              borderColor: COLORS.pos, borderColor0: COLORS.neg,
              borderWidth: 1,
            },
            markLine: {
              silent: true, symbol: 'none',
              lineStyle: { width: 1.2 },
              data: [
                { yAxis: pos.open_rate, lineStyle: { color: COLORS.accent, type: 'solid' },
                  label: { show: true, formatter: 'entry ' + pos.open_rate, color: COLORS.accent, fontSize: 10, position: 'insideEndTop' } },
                { yAxis: pos.stop_loss_abs, lineStyle: { color: COLORS.neg, type: 'dashed' },
                  label: { show: true, formatter: 'stop ' + pos.stop_loss_abs, color: COLORS.neg, fontSize: 10, position: 'insideEndBottom' } },
                { yAxis: pos.current_rate, lineStyle: { color: COLORS.text2, type: 'dotted' },
                  label: { show: true, formatter: 'now ' + pos.current_rate, color: COLORS.text2, fontSize: 10 } },
              ],
            },
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
          backgroundColor: COLORS.surface2, borderColor: COLORS.border, borderWidth: 1,
          textStyle: { color: COLORS.text, fontSize: 11 },
          valueFormatter: v => v != null ? '$' + Number(v).toFixed(2) : '—',
        },
        legend: {
          data: ['live equity', 'backtest expected'],
          top: 0, right: 8, textStyle: { color: COLORS.text3, fontSize: 11 }, icon: 'roundRect', itemWidth: 10, itemHeight: 3,
        },
        grid: { left: 60, right: 18, top: 32, bottom: 30 },
        xAxis: { type: 'time', axisLine: { lineStyle: { color: COLORS.border } }, axisLabel: { color: COLORS.text3, fontSize: 10 } },
        yAxis: {
          type: 'value', scale: true,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: COLORS.text3, fontSize: 10, formatter: '${value}' },
          splitLine: { lineStyle: { color: COLORS.border, type: 'dashed', opacity: 0.4 } },
        },
        series: [
          { name: 'backtest expected', type: 'line', data: expected, showSymbol: false,
            lineStyle: { color: COLORS.text3, type: 'dashed', width: 1.2 } },
          { name: 'live equity', type: 'line', data: live, showSymbol: false,
            lineStyle: { color: COLORS.info, width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(96, 165, 250, 0.25)' },
                { offset: 1, color: 'rgba(96, 165, 250, 0.0)' },
              ]),
            },
          },
        ],
      }, true);
    },
  };
}
