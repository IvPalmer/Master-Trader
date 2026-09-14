# Carry shadow correction, accounting v2

Research only: short Hyperliquid perpetual + matching Binance spot long.
The entry (40% trailing-24h annualized funding), exit (10% trailing-12h),
three-position limit, six-hour repost window and study fees remain unchanged.
No exchange order endpoint is called by this tracker or replay.

`tracker.py` is the version-controlled replacement for the previously VPS-only
shadow tracker. Deploy to the existing shadow directory alongside monitor.py.
`replay.py SOURCE NEW_OUTPUT` replays the archived hourly decision timestamps
from monitor.log, using archived BBO and settled funding. It requires a new
output directory and never writes the source archive. Run on the VPS.

Corrections:
- A paper fill must follow the current posting timestamp and precede expiration.
- Closing the short buys at the ask; closing spot sells at the bid.
- Quote lookup rejects future observations and stale latest quotes, and handles
  gzip archives across midnight. Funding is deduplicated and cut off at decision time.
- Weekly exposure clips each position to the reporting interval and includes
  still-open positions. Realized cash is not labeled weekly total return.
- Weekly annualized yields are unavailable until boundary valuations exist.
  First-post success among filled orders is not labeled an overall maker fill rate.
- Corrupt state fails visibly instead of silently resetting the paper history.

The replay reports completed-episode return on matched modeled capital-time,
and full-period provisioned-capital return only when there are no open episodes.
Annualization is descriptive, not a forecast. Additional 5/10 bps per fill are
sensitivity scenarios, not estimates of actual execution costs.

## Promotion remains blocked

The archived quote timestamps are batch-start timestamps, not atomic executable
cross-venue observations. Funding ingestion times were not recorded. Trade-through
is a fill proxy; top-of-book quantities are recorded but not enforced by this
legacy model. Fees and fixed funding notional are modeled, not actual account
charges; $1500 required capital per $1000 hedge is an unverified assumption.
Consequently a positive corrected result is not sufficient for a trading bot.

Before any funded executor: validate per-leg observation/arrival times and depth,
model same-base-quantity legs, funding on marked notional, actual account fees,
collateral and hedge-failure handling; then re-evaluate the original preregistered
criteria on fresh evidence. Keep the original archive and v1 results withdrawn.
Do not optimize thresholds against this correction replay.

`check_depth.py SOURCE REPLAY` screens archived top-of-book quantities against
the modeled same-base-quantity legs. Versioned results and input checksums are in
`results/`; the full source archive stays on the VPS. The corrected 2026-09-14
replay returns 9.20% annualized on modeled deployed capital, below the 12% hurdle,
and 20/36 legs fail the best-quote depth screen. No funded executor is justified.
