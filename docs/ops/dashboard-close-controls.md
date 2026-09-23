# Dashboard close-position control (#47)

Each open-position chart includes Close position, including expanded charts.
Confirming requests a full market exit through that bot's Freqtrade API. The
operator supplies that bot's API username/password in the dialog; credentials
are checked against the server configuration and never embedded in page data,
logged, or stored in browser storage. Cloudflare Access remains the perimeter;
the write endpoint independently checks credentials and HTTPS same-origin intent.
The controls do not change allocation settings or submit background exits.

The confirmation identifies bot, market, direction and remaining quantity.
The server reads fresh status, rejects changed identity/quantity and unfinished
entries, then durably reserves the request before posting. Repeated request IDs
return recorded status; different request IDs cannot duplicate an accepted,
uncertain or in-flight close for the same position epoch. Native Freqtrade close
handling manages its exit orders; receiver reconciliation observes manual closes.
No direct exchange API calls or target-ledger rewrites are performed here.

Accepted does not mean filled. Timeouts and upstream errors are uncertain, with
no automatic retry. The operator must check current orders/fills on the bot
before another action; uncertainty intentionally blocks further dashboard closes
for that position until separately reconciled. The button is not an emergency
fallback for an unavailable executor. An API-level fresh check cannot make the
snapshot and a later exchange fill atomic; final price/P&L may differ.

`DASHBOARD_ACTION_DB` defaults to `/var/lib/dashboard-actions/actions.sqlite`.
Production compose mounts the dedicated `dashboard_actions` volume there. Keep
this volume on recreation/rollback: it contains the private request audit and
restart-safe duplicate protection. It contains no operator passwords. Older
read-only dashboard code can be restored without changing trading bots.

Validation must use mocked executors. Never click Confirm market close during
production smoke testing. An older downloaded static preview cannot submit these
controls; use the HTTPS dashboard. This change does not activate the separate
Killers nearest-source TP policy.
