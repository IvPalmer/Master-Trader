export const meta = {
  name: 'dennis-may-2702-replication-validate',
  description: 'Validate the May 11-29 SCALP_CH (+2702%/+$64,394) copier backtest with REAL paid-channel entries, until trustworthy',
  phases: [
    { title: 'Dev', detail: 'verify token/scale per symbol, extract paid-channel management, run harness, write RESULTS_MAY' },
    { title: 'Review', detail: 'parallel adversarial reviewers (token-scale / sim-logic / exit-fidelity / stats-honesty)' },
    { title: 'Gate', detail: 'PM aggregates findings, converged or iterate' },
  ],
}
const DIR = 'research/insiders_april_replication'
const FINDINGS = {
  type: 'object', additionalProperties: false,
  properties: {
    issues: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { severity: { type: 'string', enum: ['P0','P1','P2'] }, title: { type: 'string' }, detail: { type: 'string' } },
      required: ['severity','title','detail'] } },
    reproduced: { type: 'boolean' },
    verdict: { type: 'string' },
  }, required: ['issues','reproduced','verdict'],
}

let feedback = `INITIAL BUILD for the MAY 11-29 SCALP_CH ledger (Dennis's actual "+2702% / +$64,394 /
"+120-130% at 5% risk" claim). Inputs in ${DIR}/: trades_may.json (31 real signals w/ posted
entry ranges+SL+TPs from the paid export, src_id = paid_messages.json id), paid_export/paid_messages.json
(the paid channel — has the management posts), prices_may/<SYM>.weex.jsonl + .binance.jsonl (1m cache,
May 9 - May 30). harness.py is the SAME validated engine; run it with env PRICES_DIR=${DIR}/prices_may.
Address ALL:
(1) **TOKEN/SCALE INTEGRITY (CRITICAL — do FIRST).** For EVERY trade, compare prices_may/<SYM>.weex.jsonl
    price at the signal minute vs the posted entry range in trades_may.json. They MUST match within a few %.
    If a symbol's cached price is ~10x off or unrelated (the known TRADOOR cmt_ redenomination failure mode),
    the cmt_<sym>usdt contract is the WRONG token/scale — flag P0, and drop or fix that line. Also cross-check
    WEEX vs Binance parity per symbol. The new alts (FF, VIRTUAL, EIGEN, USELESS, FIDA, NEAR, ETC, LTC, HYPE,
    SKY, TON) are the risk — verify each.
(2) Extract MANAGEMENT events from paid_export/paid_messages.json for each trade (close X%, "SL to breakeven",
    "close full", partial TP closes) by symbol + temporal proximity after the signal (src_id is the opener);
    add to events[] in trades_may.json. Many May signals scale out — model it.
(3) Run harness with PRICES_DIR=prices_may for posted+market entry x ladder+manage exit. Note: late-May trades
    (May 25-29) cannot fully forward-walk (cache ends May 30 = today); they close via management or tail-cap at
    data end — state this honestly, don't pretend they resolved.
(4) Write ${DIR}/RESULTS_MAY.md: per-trade sim (R and $) vs Dennis's claim, totals under each model, the
    COPIER-CAPTURE verdict vs his +120-130% account claim and +$64,394, coverage (sized/31), and explicit caveats.
RULE: entry/exit models FIXED, nothing tuned to hit +2702% / +120-130% / +$64,394. Hedge to the objective copyable rule.`

let result = null
for (let i = 0; i < 4; i++) {
  phase('Dev')
  const dev = await agent(
    `You are the DEV validating the MAY +2702% copier backtest. Working dir ${DIR}/ (offline; prices_may/ cached; do NOT fetch network).
Read SPEC.md, harness.py, trades_may.json, paid_export/paid_messages.json, price_cache_may_summary.json first.
Task:
${feedback}
Run the harness as: \`PRICES_DIR=${DIR}/prices_may python3 harness.py ${DIR}/trades_may.json\` (edit harness __main__ if needed to accept a trades-file arg; it already does). Edit trades_may.json (events, drop wrong-token lines) and write ${DIR}/RESULTS_MAY.md.
Return: what you changed, the headline copier total (posted+manage and market+manage, in R and account-%), coverage, and any symbol you dropped for bad token/scale.`,
    { label: `dev-may-iter${i}`, phase: 'Dev' }
  )
  phase('Review')
  const LENSES = [
    ['token-scale', `CRITICAL: for each trade verify prices_may/<SYM>.weex.jsonl price at the signal minute matches the posted entry range (within a few %). Any ~10x or unrelated mismatch = wrong cmt_ token (P0). Verify WEEX vs Binance parity. The obscure alts (FF, VIRTUAL, EIGEN, USELESS, FIDA, NEAR, ETC, LTC, HYPE, SKY, TON) are the risk.`],
    ['sim-logic', `Verify no look-ahead (mgmt walks from fill_ts, not signal minute — the pre-fill event guard), SL-first conservative, fractions sum to 1, long/short PnL sign, late-May trades honestly tail-capped at the May-30 data end (not pretend-resolved).`],
    ['exit-fidelity', `Cross-check 4-5 trades' events[] against the actual management posts in paid_export/paid_messages.json (right symbol, %, timestamp, src_id lineage). Verify scale-outs aren't invented; both ladder & manage reported.`],
    ['stats-honesty', `Overfitting check (NO tuning to +2702%/+120-130%/+$64,394 = P0). Coverage honesty (sized/31, late-May unresolved stated). Reproduce: run the harness yourself and confirm RESULTS_MAY.md totals match. Is the copier total honestly compared to his +120-130% ACCOUNT claim (not the meaningless +2702% sum-of-%)?`],
  ]
  const reviews = await parallel(LENSES.map(([k,p]) => () =>
    agent(`ADVERSARIAL REVIEWER (lens: ${k}) on the MAY +2702% backtest. Working dir ${DIR}/. Read harness.py, trades_may.json, RESULTS_MAY.md, paid_export/paid_messages.json, sample prices_may/. You may run \`PRICES_DIR=${DIR}/prices_may python3 harness.py ${DIR}/trades_may.json\`.
${p}
Try hard to REFUTE the result. Return structured findings (P0/P1/P2) + whether you reproduced the numbers.`,
      { label: `review-may-${k}`, phase: 'Review', schema: FINDINGS })))
  phase('Gate')
  const valid = reviews.filter(Boolean)
  const all = valid.flatMap(r => r.issues || [])
  const blocking = all.filter(f => f.severity === 'P0' || f.severity === 'P1')
  const reproduced = valid.every(r => r.reproduced)
  result = { iter: i, dev, blocking, all, reproduced, verdicts: valid.map(r => r.verdict) }
  log(`may iter ${i}: blocking=${blocking.length} reproduced=${reproduced}`)
  if (blocking.length === 0 && reproduced) { log(`MAY CONVERGED iter ${i}`); break }
  feedback = `Fix these BLOCKING issues (keep the rest intact):\n` +
    blocking.map(f => `- [${f.severity}] ${f.title}: ${f.detail}`).join('\n') +
    (reproduced ? '' : '\nALSO: a reviewer could not reproduce RESULTS_MAY.md — make it deterministic and matching.')
}
return result
