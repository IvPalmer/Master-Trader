# Master-Trader homepage at `master-trader.grooveops.dev`

Drafted 2026-04-28. Not yet executed. Status: PLAN.

---

## Goal

Stand up a public-DNS landing page for master-trader that surfaces live bot performance (charts + summary stats) the way `health.grooveops.dev` surfaces a health snapshot or `rlm.grooveops.dev` surfaces label data. The Grafana dashboards already exist (`Master Dashboard` uid `gkcfzm`, 23 panels) — this plan exposes them safely + adds a curated front face.

## Current state (2026-04-28)

- VPS stack `compose-bypass-mobile-port-fbk1m6` (Dokploy compose, `IvPalmer/Master-Trader@vps-deploy`, composePath `./ft_userdata/docker-compose.prod.yml`).
- 6 containers: `ft-funding-fade` (LIVE, real money), `ft-keltner-bounce` (dry-run), `ft-grafana-bridge`, `ft-metrics-exporter`, `ft-prometheus`, `ft-grafana`.
- Network: `dokploy-network` (Traefik attaches via this).
- Grafana bound to `127.0.0.1:3030` on host. **Not tailnet-reachable** — docker port mapping is host-loopback only.
- Grafana anonymous Admin is on (`GF_AUTH_ANONYMOUS_ENABLED=true`, login form disabled). Suitable for SSH-tunnel use; **not** suitable for public exposure.
- Prometheus 9091 + metrics-exporter 9090 — both 127.0.0.1-bound, scraping freqtrade `/api/v1` via `ft-grafana-bridge` and the exporter.
- Dokploy compose IDs: `projectId=eDQBiyFzAnz22unUUBK_Y`, `composeId=gajntEdheyjvJKEVuUbbe`, `appName=compose-bypass-mobile-port-fbk1m6`.

## Constraints

1. **Real-money bot** — exposing Grafana publicly with anonymous Admin is unacceptable. Must auth-gate.
2. **Sensitivity asymmetric** — P/L magnitude is private; strategy logic is in a public repo so non-secret. Treat dashboards as private until decided otherwise.
3. **Wildcard TLS already provisioned** for `*.grooveops.dev` via Traefik + Cloudflare DNS-01, so adding a new subdomain is just a Traefik router.
4. **No new secrets** if avoidable — reuse Cloudflare Access (already used for ocdj per `docs/CLOUDFLARE-ACCESS-SETUP.md` in that repo).

## Three architectures

### Option A — Reverse-proxy Grafana directly (smallest surface)

`master-trader.grooveops.dev` → Traefik router → `ft-grafana:3000`. Disable Grafana anonymous, gate the entire domain with Cloudflare Access (email-magic-link policy or Google OAuth on `raphaelpalmer@gmail.com`).

- **Effort:** ~30 min. Add Traefik labels to `ft-grafana`, disable `GF_AUTH_ANONYMOUS_ENABLED`, enable `GF_AUTH_PROXY_*` so CF Access JWT email becomes the Grafana user. Add CF Access app + policy.
- **UX:** lands directly on the Master Dashboard. No marketing surface.
- **Pro:** zero new code, leverages existing 23-panel dashboard.
- **Con:** raw Grafana UI, not a "homepage". No public-facing read-only view.

### Option B — Custom landing + embedded panels (heavier)

Static Vite/Next page at `master-trader.grooveops.dev/`. Hero with live KPIs (Portfolio Total, P/L, Drawdown, Bots Online), embedded Grafana panel iframes (`/d-solo/...`) for the timeseries, links to strategy docs. Same CF Access gate.

- **Effort:** ~4–6 hr. Build the page, design tokens, embed via Grafana panel-share URLs, write a tiny Express/Caddy/Next API that proxies metrics-exporter for hero KPIs.
- **UX:** branded landing, curated, strategy summaries.
- **Pro:** matches the "homepage" feel of `health.grooveops.dev` style; can selectively expose a public-safe slice later.
- **Con:** maintenance overhead; another container to keep alive; CF Access still required because panels include real P/L.

### Option C — Landing + `/grafana` subroute (recommended)

`master-trader.grooveops.dev/` → custom landing page (static, Caddy or nginx serving a built React/Vite bundle). `master-trader.grooveops.dev/grafana/*` → reverse-proxied Grafana with `GF_SERVER_ROOT_URL` + `GF_SERVER_SERVE_FROM_SUB_PATH=true`. CF Access policy on the whole domain.

- **Effort:** ~2–3 hr. Add a `homepage` service to the compose (Caddy + bundled HTML). Configure Grafana sub-path. Add Traefik path-rule routers. CF Access on the domain.
- **UX:** branded landing with hero stats + “Open dashboards” button → full Grafana experience under `/grafana`.
- **Pro:** best of both — fast to build, full Grafana available, room to grow.
- **Con:** sub-path Grafana asset rewrites can be finicky; budget 30 min for CSS/asset URL debugging.

**Recommendation:** **Option C.** It’s the “homepage like the other projects” the brief asks for, while keeping the existing 23-panel dashboard as the workhorse. Option A is the fallback if time is short.

## Phasing

### Phase 0 — decisions (15 min, before any code)

- [ ] Pick A / B / C.
- [ ] Pick auth: CF Access email policy (just `raphaelpalmer@gmail.com`) vs CF Access Google-OAuth vs Grafana basic-auth-only-no-CF. **Default: CF Access email magic-link, single allowed identity.**
- [ ] Decide if any panel should be public-readable later (e.g. high-level "bots online" status). For V1, treat everything as private.

### Phase 1 — DNS + Traefik (15 min)

- [ ] Cloudflare DNS: `A master-trader.grooveops.dev → 159.112.191.120`, proxied OFF (Traefik handles TLS via DNS-01 already; CF proxy interferes with CF Access JWT verification anyway — verify against ocdj setup).
- [ ] In Dokploy, add the domain to the master-trader compose service that will receive traffic. For Option C this is the new `homepage` service plus a path-rule for `ft-grafana`.

### Phase 2 — Grafana hardening (20 min, REQUIRED for any of A/B/C)

- [ ] Set in `ft_userdata/docker-compose.prod.yml` Grafana env:
  - `GF_AUTH_ANONYMOUS_ENABLED=false`
  - `GF_AUTH_DISABLE_LOGIN_FORM=false` (or keep disabled if using auth-proxy)
  - Add `GF_AUTH_PROXY_ENABLED=true`, `GF_AUTH_PROXY_HEADER_NAME=Cf-Access-Authenticated-User-Email`, `GF_AUTH_PROXY_HEADER_PROPERTY=username`, `GF_AUTH_PROXY_AUTO_SIGN_UP=true`, `GF_AUTH_PROXY_WHITELIST=<traefik container CIDR>` (auth-proxy only trusts the proxy).
  - For Option C: `GF_SERVER_ROOT_URL=https://master-trader.grooveops.dev/grafana/`, `GF_SERVER_SERVE_FROM_SUB_PATH=true`.
- [ ] Provision an admin user via env (`GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` from Dokploy env, write into `~/.secrets/master-trader-grafana.env`).
- [ ] Bind change: drop the `127.0.0.1:3030:3000` host port (no longer needed; Traefik on `dokploy-network` reaches the container directly). Avoids any chance of bypassing CF Access.

### Phase 3 — Cloudflare Access policy (10 min)

Reuse the click-walkthrough at `~/Work/Dev/ocdj/docs/CLOUDFLARE-ACCESS-SETUP.md` (10-step setup). Differences:
- Application name: `master-trader`.
- Domain: `master-trader.grooveops.dev` (full host, no path filter — gate everything).
- Policy 1 (Allow): emails-include `raphaelpalmer@gmail.com`. Add a second email later if needed.
- No bypass policy (unlike ocdj where `/api/drain/*` was bypassed) — every path is private.

### Phase 4 — Homepage build (Option C only, 1–2 hr)

- [ ] New dir `ft_userdata/homepage/` in repo. Tiny Vite + React + Tailwind app, single page.
- [ ] Hero: pull JSON from `/api/metrics` (a 30-line Express/Caddy proxy on the same container that fetches from `metrics-exporter:9090/metrics`, parses Prom text, returns curated JSON). Fields: portfolio total, today's P/L, drawdown, open trades count, bots online.
- [ ] Sections: bot cards (FundingFade live / KeltnerBounce dry-run with status pill, last-trade time), strategy short-blurbs (link to repo `docs/`), "Open full dashboards" CTA → `/grafana`.
- [ ] `Dockerfile` multi-stage: build → Caddy serving static + reverse-proxying `/grafana/*` → `ft-grafana:3000` and `/api/metrics` → internal node script.
- [ ] Add `homepage` service to compose, attached to `dokploy-network`, with Traefik labels: host rule `master-trader.grooveops.dev`, no path filter (Caddy handles internal routing).

### Phase 5 — Verify

- [ ] `https://master-trader.grooveops.dev/` from a clean browser → CF Access login prompt → magic-link → landing page.
- [ ] `/grafana/` loads Master Dashboard with the email as the auto-signed-up Grafana user.
- [ ] Logged-out browser → CF Access blocks before reaching either origin.
- [ ] `curl -I` from a non-logged-in client returns CF Access redirect (302/200 with `cf-access` cookie set).
- [ ] No 127.0.0.1:3030 binding remains (`docker port ft-grafana` shows nothing — Traefik-only).

## Open questions

1. **Public-readable slice?** A "Bots Online" status badge could go on the truly-public side of CF Access (bypass policy on `/status.json`). Defer to V2 unless wanted now.
2. **Grafana data lifetime.** Prometheus retention is currently default (15d?). For meaningful timeseries on the homepage, confirm retention or extend.
3. **Webhook stays on Mac?** Per session-log 2026-04-27, FundingFade still POSTs to Mac `100.92.77.68:8088` (claude-assistant). Out of scope for this plan but a related cleanup once claude-assistant migrates.

## Effort summary

| Option | Effort | Result |
|---|---|---|
| A — proxy Grafana only | 30 min + CF Access | Live but bare; raw Grafana UI on the public host |
| B — custom landing + embeds | 4–6 hr | Full bespoke homepage |
| **C — landing + `/grafana` subroute** | **2–3 hr** | **Branded homepage, full Grafana under sub-path** |

## Sequencing recommendation

If user wants this live this week: **A first** (30 min, gets safe public access + correct DNS + CF Access wired), then iterate to **C** when there’s time. Option A’s Traefik labels and CF Access app are reused unchanged in C; Phase 4 (homepage build) is the only addition.
