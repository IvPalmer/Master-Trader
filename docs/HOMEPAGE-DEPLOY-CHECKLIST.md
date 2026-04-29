# `master-trader.grooveops.dev` go-live checklist

Status: **PREPPED — awaiting user gate.** Branch `feat/homepage-option-a-prep` carries
Phase 2 hardening + Traefik labels. Nothing is live until the steps below run, in
order, after merging to `vps-deploy`.

> **Option A (this prep), not Option C.** Plan `docs/plans/MASTER-TRADER-HOMEPAGE.md`
> recommends C (custom landing + `/grafana` subroute). A is the bounded fallback —
> ~30 min reversible, exposes raw Grafana directly. **C is the eventual target;
> this lays the groundwork** (CF Access app, DNS record, Traefik router, hardening
> all reused unchanged). When promoting to C, only Phase 4 (homepage build) is
> additive.

> **Real-money guardrail.** `ft-funding-fade` runs LIVE money. **Do NOT push
> `feat/homepage-option-a-prep` → `vps-deploy` until CF Access is provisioned in
> Cloudflare** (step 2). Pushing first would briefly expose Grafana publicly with
> auth-proxy expecting a header that nothing is sending → effectively open.

---

## 1. Cloudflare DNS (manual, ~2 min)

Cloudflare dashboard → grooveops.dev zone → DNS:

- Add `A` record: `master-trader` → `159.112.191.120`
- Proxy status: **DNS only (grey cloud)**. CF Access JWT verification needs the
  origin reachable directly; CF proxy on top would interfere.
- TTL: Auto.

Verify:
```bash
dig +short master-trader.grooveops.dev
# expect: 159.112.191.120
```

DNS does NOT activate the site yet — Traefik router only fires once the merged
compose redeploys.

## 2. Cloudflare Access app + policy (manual, ~10 min)

Reuse the canonical walkthrough at `~/Work/Dev/ocdj/docs/CLOUDFLARE-ACCESS-SETUP.md`.
Differences for master-trader:

| Field | Value |
|---|---|
| Application name | `master-trader` |
| Application domain | `master-trader.grooveops.dev` (full host, no path filter) |
| Session duration | 24h (matches ocdj) |
| Identity provider | One-time PIN (email magic-link) |
| Policy 1 (Allow) | Emails include `raphaelpalmer@gmail.com` |
| Bypass policy | **None.** Every path is private. |

Critical: do NOT reuse the ocdj `/api/drain/*` bypass — master-trader has no
public-readable surface in V1.

## 3. Grafana admin password (manual, ~3 min)

```bash
# generate
openssl rand -base64 24

# store on Mac
mkdir -p ~/.secrets
cat > ~/.secrets/master-trader-grafana.env <<'EOF'
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=<paste-generated>
EOF
chmod 600 ~/.secrets/master-trader-grafana.env
```

Mirror to Dokploy: project `master-trader` → Environment → add the two vars.
(They are referenced via env-substitution by Grafana's image; the auth-proxy
mode already covers normal access — admin password is a break-glass for
local-port (127.0.0.1:3030) access during the verify window.)

## 4. Merge → trigger redeploy

```bash
cd ~/Work/Dev/master-trader
git checkout vps-deploy
git merge --ff-only feat/homepage-option-a-prep
git push origin vps-deploy
```

Dokploy webhook fires → rebuilds the compose stack. Watch:
- Dokploy UI → master-trader compose → Deployments tab.
- Container `ft-grafana` should restart cleanly.
- Other 5 containers untouched (no compose changes to them).

## 5. Verify (manual, browser + curl)

- Clean browser (incognito): `https://master-trader.grooveops.dev/`
  → expect Cloudflare Access magic-link prompt.
  → enter `raphaelpalmer@gmail.com`, click magic-link in inbox.
  → land on Grafana home → Master Dashboard (uid `gkcfzm`) auto-loads.
  → username top-right shows `raphaelpalmer@gmail.com` (auto-signed-up via
    `GF_AUTH_PROXY_AUTO_SIGN_UP=true`).
- Logged-out browser (different incognito):
  → CF Access blocks before reaching origin. No Grafana frame visible.
- Tunneled health check from Mac (still works because port binding kept):
  ```bash
  ssh -L 3030:127.0.0.1:3030 main-instance
  # then http://localhost:3030 → CF Access bypassed (intentional, breakable)
  ```
- `curl -I https://master-trader.grooveops.dev/` from anywhere unauthenticated
  → expect `302` to CF Access challenge URL.

## 6. After verification — drop the host port (follow-up commit)

Once steps 1–5 pass, the `127.0.0.1:3030:3000` binding is dead weight and
becomes a CF-Access bypass surface for anyone with VPS/SSH access. Drop it:

```bash
git checkout -b chore/drop-grafana-host-port
# remove the `ports:` block from the grafana service in docker-compose.prod.yml
git commit -am "chore: drop ft-grafana 127.0.0.1:3030 binding — CF Access verified"
git checkout vps-deploy
git merge --ff-only chore/drop-grafana-host-port
git push origin vps-deploy
```

After that redeploy: `docker port ft-grafana` on VPS shows nothing — Traefik on
`dokploy-network` is the only path in.

---

## Rollback (if any step fails)

```bash
cd ~/Work/Dev/master-trader
git checkout vps-deploy
git revert <merge-commit>
git push origin vps-deploy
```

DNS record can stay; without the Traefik router the host returns Traefik's
default 404 and CF Access still gates access. To fully back out:
- CF dashboard → Access → master-trader app → Delete.
- CF dashboard → DNS → delete `master-trader` A record.

## Post-go-live: promote to Option C

Plan: `docs/plans/MASTER-TRADER-HOMEPAGE.md` Phase 4. Builds a `homepage` service
(Caddy + static React/Vite bundle) in `ft_userdata/homepage/`, configures
Grafana sub-path (`GF_SERVER_ROOT_URL`, `GF_SERVER_SERVE_FROM_SUB_PATH=true`),
splits Traefik routers between `/` (homepage) and `/grafana/*` (Grafana). CF
Access app + policy from step 2 are unchanged.
