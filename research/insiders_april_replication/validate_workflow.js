export const meta = {
  name: 'dennis-april-replication-validate',
  description: 'Harden + adversarially validate the Dennis April-ledger copier backtest until trustworthy (PM>Dev>review loop on offline cached data)',
  phases: [
    { title: 'Dev', detail: 'build/refine sim: follow posted management exits, no-SL handling, re-run' },
    { title: 'Review', detail: 'parallel adversarial reviewers (data / sim-logic / exit-fidelity / stats-honesty)' },
    { title: 'Gate', detail: 'PM aggregates findings, decides converged or iterate' },
  ],
}

const DIR = 'research/insiders_april_replication'

const FINDINGS = {
  type: 'object',
  additionalProperties: false,
  properties: {
    issues: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['P0', 'P1', 'P2'] },
          title: { type: 'string' },
          detail: { type: 'string' },
        },
        required: ['severity', 'title', 'detail'],
      },
    },
    reproduced: { type: 'boolean', description: 'did re-running harness.py give the same numbers as RESULTS.md' },
    verdict: { type: 'string' },
  },
  required: ['issues', 'reproduced', 'verdict'],
}

let feedback = `INITIAL BUILD. Address ALL:
(1) EXIT MODEL = follow Dennis's POSTED management. Extract per-trade management timeline
    (close X%, "stoploss to breakeven", "close full", "TP1 reached close 25%") from
    raw_free_messages.json by symbol + temporal proximity after the signal; add as an
    events[] array on each trade in trades.json. Upgrade harness to process these events
    at their timestamps (partial close at event-time price, SL move, full close), walking
    for SL between events. ALSO keep a mechanical TP-ladder variant for comparison and
    report BOTH (if they diverge, the discretion matters — say so).
(2) NO-SL trades (11/23 have no posted SL): declare a stop assumption explicitly (e.g.
    exclude from the risk-sized total but include in a "follow-management, no-hard-stop"
    diagnostic). Never hide them — report coverage (how many of 23 are sized).
(3) Confirm ZEC + LAB are cached (prices/ZEC.weex.jsonl etc.); re-run on the COMPLETE cache.
(4) Write RESULTS.md: per-trade table (sim R and $ vs Dennis's claim) under each entry
    model x exit model; totals; coverage; the copier-capture verdict; explicit caveats.
RULES: do NOT tune any assumption to hit +$22,119 (fit-to-scoreboard = fail). Entry models
(posted/edge/market) are FIXED. Hedge all conclusions to "the objective copyable rule".`

let result = null
for (let i = 0; i < 4; i++) {
  phase('Dev')
  const dev = await agent(
    `You are the DEV on the Dennis April-ledger copier backtest. Working dir: ${DIR}/ (offline; prices/ are cached — do NOT fetch network).
Read SPEC.md, harness.py, trades.json, raw_free_messages.json, price_cache_summary.json first.
Then do this task:
${feedback}
Edit harness.py and trades.json as needed, run \`python3 harness.py\` (from ${DIR}/), and write/refresh ${DIR}/RESULTS.md.
Return a concise summary: what you changed, the headline numbers (copier net under market-entry + follow-management), and coverage (sized/23).`,
    { label: `dev-iter${i}`, phase: 'Dev' }
  )

  phase('Review')
  const LENSES = [
    ['data-integrity', `Verify price-data correctness: each trade's symbol maps to the right cmt_/Binance pair, NO price-scale (1000x) error, candles cover each trade's window, and WEEX vs Binance agree (parity). Flag any trade silently using wrong/no data.`],
    ['sim-logic', `Verify sim correctness: NO look-ahead (entry fill only from candles at/after the signal minute; management applied at event timestamps), SL-first-within-candle is conservative, TP-ladder fractions sum to 1.0, SL->breakeven after TP1, long-vs-short PnL sign correct, tail/no-fill/no-sl handled.`],
    ['exit-fidelity', `Verify the exit model FAITHFULLY follows Dennis's posted management rather than inventing exits. Cross-check 3-4 trades' events[] in trades.json against the actual posts in raw_free_messages.json (right symbol, right %, right timestamp). Check winners are not over/under-counted. Confirm both the management and mechanical-TP-ladder variants are reported.`],
    ['stats-honesty', `Check for fit-to-scoreboard / overfitting (any assumption tuned to reach +$22,119 = P0). Check coverage honesty (sized vs 23, no-SL handling declared), conclusions hedged, and REPRODUCIBILITY: re-run \`python3 harness.py\` yourself and confirm RESULTS.md numbers match.`],
  ]
  const reviews = await parallel(LENSES.map(([k, p]) => () =>
    agent(
      `You are an ADVERSARIAL REVIEWER (lens: ${k}) on the Dennis April backtest. Working dir ${DIR}/.
Read harness.py, trades.json, RESULTS.md, raw_free_messages.json, and sample prices/. You MAY re-run \`python3 harness.py\`.
${p}
Try hard to REFUTE the result or find an error. Default to skepticism. Return structured findings (P0=invalidates result, P1=material, P2=minor) and whether you reproduced the numbers.`,
      { label: `review-${k}`, phase: 'Review', schema: FINDINGS }
    )
  ))

  phase('Gate')
  const valid = reviews.filter(Boolean)
  const allFindings = valid.flatMap(r => (r.issues || []).map(x => ({ ...x, lens: 'review' })))
  const blocking = allFindings.filter(f => f.severity === 'P0' || f.severity === 'P1')
  const reproduced = valid.every(r => r.reproduced)
  result = { iter: i, devSummary: dev, blocking, allFindings, reproduced, reviewerVerdicts: valid.map(r => r.verdict) }
  log(`iter ${i}: blocking=${blocking.length} reproduced=${reproduced}`)
  if (blocking.length === 0 && reproduced) { log(`CONVERGED at iter ${i}`); break }
  feedback = `Fix these BLOCKING issues found in review (and keep everything else intact):\n` +
    blocking.map(f => `- [${f.severity}] ${f.title}: ${f.detail}`).join('\n') +
    (reproduced ? '' : '\nALSO: a reviewer could not reproduce RESULTS.md numbers by re-running — make the run fully deterministic and ensure RESULTS.md matches harness.py output.')
}
return result
