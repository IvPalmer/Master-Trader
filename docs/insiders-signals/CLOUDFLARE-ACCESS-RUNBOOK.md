# Adding Eduardo to Cloudflare Access for `master-trader.grooveops.dev`

2-minute task. Repeat for any future collaborator who needs dashboard
read access.

## Current setup (verified 2026-05-19)

- Domain: `master-trader.grooveops.dev`
- Cloudflare Access team domain: `grooveops.cloudflareaccess.com`
- Auth model: email one-time PIN (magic link)
- Session TTL: 24h
- Cert path: Let's Encrypt via Traefik (Cloudflare in front)

## Steps

1. Log into Cloudflare → Zero Trust dashboard at https://one.dash.cloudflare.com/
2. Pick the `grooveops` team (the one that owns the `grooveops.cloudflareaccess.com` namespace)
3. Left sidebar → **Access** → **Applications**
4. Find the application whose **Application Domain** is `master-trader.grooveops.dev`
5. Click **Edit** → tab **Policies**
6. Either:
   - **Add a new policy**: name "trader-readers", action "Allow", include rule "Emails" → list Eduardo's email + any other invitees
   - OR **edit the existing allow policy**: add Eduardo's email to its Emails rule
7. **Save**

Eduardo can now visit `https://master-trader.grooveops.dev` → enter his
email → get a magic-link email from Cloudflare → click → in.

## Verifying

Curl the dashboard URL with an `Authorization` header set OR just have
Eduardo confirm he sees the dashboard after clicking the link. No
server-side change needed on our end — Cloudflare handles the auth gate.

## Removing access (when phase 2 makes the Eduardo-hop obsolete)

Same path: Access → Applications → master-trader → Policies → edit the
Allow policy → remove Eduardo's email → Save. Effect is immediate; his
existing session expires within 24h.

## What if we add lots of collaborators later?

Switch from "list of emails" to a **Google Workspace / GitHub group** as
the policy's identity source. Cloudflare Access integrates with both
out of the box. Don't bother for v1; just maintain the email list.
