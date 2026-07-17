# PLI (codename)

A round-based mutual-declaration escrow. Two people privately name each
other; only then is either told. Nothing else is ever revealed, to anyone,
ever.

**Non-disclosure is the product.** The full spec, threat model, and the
reasoning behind every rejected feature live in [HANDOFF.md](HANDOFF.md).
Read it before touching anything. The invariant tests in
[`tests/test_invariants.py`](tests/test_invariants.py) *are* the spec; if a
change turns one red, the change is wrong.

## The mechanic

1. A round opens Monday 00:00 and closes Friday 23:59 (Europe/Paris).
2. During the round, a participant may name up to 3 people by email address.
3. Named people are never notified. Not on write, not at close, not ever.
4. Saturday 08:00, a batch job computes reciprocal pairs.
5. Reciprocal pairs — and only reciprocal pairs — each receive the other's
   email address. One message each.
6. Everything else is deleted, then the database is VACUUMed. The crush
   graph does not survive the reveal.

## Development

```sh
pip install -r requirements-dev.txt
python -m pytest --cov=pli    # coverage is enforced at 100%
```

Run locally (mail goes to stdout):

```sh
export PLI_PEPPER=$(python -c "import secrets; print(secrets.token_hex(32))")
export PLI_COHORT_ID=dev
export PLI_DB=data/pli.db PLI_KEYS_DIR=data/keys

python -m pli.cli create-cohort --id dev --label "Dev" --domains example.edu --min-cohort 2
python -m pli.jobs open
uvicorn pli.app:create_app --factory --no-access-log
```

Round jobs, runnable by APScheduler (`python -m pli.scheduler`, included in
docker-compose) or plain cron:

```sh
python -m pli.jobs tick    # advance everything that is due — run every minute
```

The scheduler is a single minute tick: the timeline lives in the data, not
the crontab. The original fixed commands (`open`/`close`/`reveal`) still
exist for a plain-cron deployment of a single weekly community.

## Events — same product, own timeline

The default community at the root URL runs the original weekly cadence:
opens Monday 00:00, closes Friday 23:59, reveals Saturday 08:00
(Europe/Paris). Nothing about it changed.

Organizers additionally run *events*: the identical mechanic on a custom
timeline — a conference running Wednesday-to-Friday with a reveal before
the closing party, a speed-dating night compressed into two hours.

Organizers are self-serve at `/org`: magic-link sign-in (no passwords),
create and configure events in the browser, get the share URL, watch the
signup count. Events can also be provisioned from the CLI:

```sh
python -m pli.cli create-event --id devconf-2026 --label "DevConf 2026" \
    --join-code sesame --min-cohort 20 \
    --opens "2026-09-10T09:00" --closes "2026-09-12T18:00" --reveal "2026-09-12T20:00"
```

- The event page is served at `/e/{id}` with the organizer's description.
  **Private** events (the default) are unlisted, reached only by the link
  the organizer circulates. **Public** events appear in the `/events`
  directory while a round is scheduled or open.
- Access is gated by email domains, a join code (for crowds with no
  shared domain — the code is stored as a keyed hash and a wrong code is
  indistinguishable from a right one in the response), or both.
- Organizers see round status and a signup count. They never see a
  roster, a declaration, or a match count — that data does not exist in a
  form anyone can show them, which is also the coercion defence.
- Custom email content is a plain-text note rendered inside the
  platform's fixed templates and explicitly attributed to the organizer —
  never a template editor. A template editor on a product that mails
  magic links is a phishing kit.
- **Guardrails on modification.** While a round is scheduled, everything
  is editable. Once it opens: the opening time is fixed, close and reveal
  can only be pushed later (people declared against the published times),
  and `min_cohort` freezes (it is a published pre-commitment — no
  adaptive lowering after seeing the count). The reveal can never precede
  the close. Cancelling voids the round: everything deleted, nothing
  revealed, nobody notified.
- **Every participant-side invariant applies per event, unchanged.** Same
  handlers, same escrow, same reveal job, same delete-and-VACUUM.
  Matching is scoped to a single round, so two rounds can never leak into
  each other.

## Embed widget

Organizers can embed the join flow directly in their event's own website.
The edit page provides the snippet:

```html
<iframe src="https://…/e/{event}/widget?theme=light&accent=1f4a5f&font=serif&lang=en"
        title="PLI" width="100%" height="380" style="border:0" loading="lazy"></iframe>
```

- Stylistic options, strictly validated (anything else falls back to the
  default): `theme` = `light`|`dark`, `accent` = 6-digit hex,
  `font` = `serif`|`sans`, `lang` = any supported language.
- It is an **iframe on purpose**: participants type their address inside
  our origin, where the host page cannot read it — no script tag to
  audit, no keystrokes leaving the frame.
- Only `/e/{id}/widget` is framable (`frame-ancestors *`); every other
  page keeps `frame-ancestors 'none'` + `X-Frame-Options: DENY`.
- The widget shows the round's state (scheduled / open with the join
  form / closed / concluded / voided / paused) and uses the same silent
  join core as the site: the confirmation view is byte-identical
  whatever was submitted.

## Organizer API, integrations, growth & trust surfaces

- **REST API** (`/api/v1/events`, Bearer token minted on the dashboard —
  hash-stored, shown once, rotation revokes): list/create/get/patch
  events, cancel, schedule new rounds. Same guardrails and billing gates
  as the console; returns a signup count and round status, never more.
- **iCal**: `GET /e/{id}/calendar.ics` — the round's public timeline
  (declaration window + reveal) as a subscribable calendar.
- **QR poster**: `GET /e/{id}/poster` — print-ready A5 with the QR baked
  in. The flyer is the growth channel; this makes it one click.
- **Widget auto-resize**: the widget reports its height to the embedding
  page via `postMessage` (height only, nothing else crosses the frame);
  parent-side listener snippet in the docs.
- **Custom domains (pro)**: the organizer CNAMEs `pact.their-conf.com`
  to the platform; the event answers at that host's root via an internal
  path rewrite, so every handler and invariant applies unchanged. Add
  the host to Traefik's certificate config when provisioning.
- **Outbound webhooks**: optional per-event HTTPS URL receiving round
  status changes (`opened`/`closed`/`voided`/`revealed`) signed with a
  per-event secret (`X-PLI-Signature`). Statuses only — never counts.
  Best-effort: a dead endpoint never delays a reveal.
- **Transparency page** (`/transparency`): reproducible-build attestation
  (`PLI_BUILD_COMMIT`, `PLI_IMAGE_DIGEST` — bake the commit in with
  `docker build --build-arg BUILD_COMMIT=$(git rev-parse HEAD)`) and a
  quarterly **warrant canary** (`PLI_CANARY_UPDATED`,
  `PLI_TRANSPARENCY_REQUESTS`). Renewal is the signal; see
  `docs/transparency.md`.
- **Institutional SSO attestation**: operator-configured OIDC per cohort
  (`pli.cli set-oidc`). The institution asserts membership; the verified
  address is then treated exactly like a typed one — hashed, sealed,
  destroyed at reveal — and the session starts without a magic-link
  mail. Nothing from the identity provider is retained.

## Abuse flags

Every event page carries an anonymous "Report this event" link (reasons:
impersonation, harassment, spam, other). One flag per reporter per event
(keyed IP hash, no reporter identity stored). At 3 independent flags the
event auto-suspends pending review: joins and declarations stop, and a
reveal falling due while suspended **voids** — deleted, revealing nothing,
because silence is the only safe failure mode here too. Operator tooling:

```sh
python -m pli.cli flags                     # review queue
python -m pli.cli suspend --id <event>
python -m pli.cli unsuspend --id <event>    # also clears its flags
python -m pli.cli ban-organizer --email <address>   # bans + suspends their events
```

## Deliverability, billing, legal, i18n

- **Bounce/complaint webhooks** — point the mail provider at
  `POST /webhooks/mail/{PLI_MAIL_WEBHOOK_TOKEN}` (Postmark payload shape
  or generic `{"type","email"}`). Addresses land on a **suppression
  list** as keyed hashes and are never mailed again — no magic links, no
  match mail (the other half of a pair is still served). Manual entry:
  `python -m pli.cli suppress --email …`.
- **Billing (Stripe)** — `PLI_BILLING=off` (default) leaves everything
  free. `PLI_BILLING=stripe` enforces plans: free = one event at a time,
  private only; pro = unlimited events + public listing. Participants
  are never gated or capped on any plan. Upgrade goes through hosted
  Stripe Checkout (no card data here, PCI SAQ-A); plan changes arrive by
  signed webhook at `/webhooks/stripe`.
- **Moderation** — public listing is a **greylist**: requesting it puts
  the event in a review queue (`pli.cli queue` / `approve` / `reject`);
  the directory shows approved events only, and pending events remain
  reachable by their link. The **blacklist** (`blacklist-add`, exact
  address or whole domain) silently blocks organizer sign-in. Flags
  auto-suspend at threshold as before.
- **Legal** — `/legal/privacy`, `/legal/terms`, `/legal/dpa` in English
  and French, rendered with the SASU's identity from `PLI_COMPANY_*`.
  GDPR working papers (Art. 30 register, retention register, DPIA,
  sub-processors) live in `docs/gdpr/`. **All of it is a serious draft,
  not legal advice — have French counsel review before launch.**
- **i18n** — participant pages ship in English, French, German, Spanish,
  Portuguese, and Scots (`?lang=fr|de|es|pt|sco`, persisted in a cookie,
  Accept-Language honoured). The catalogue is completeness-tested. The
  non-French translations are machine-drafted: **have native speakers
  review them**, especially every sentence carrying a safety promise.
  Organizer console is English-only for now.
- **Accessibility** — skip link, landmarks, labelled controls,
  focus-visible outlines, WCAG AA contrast, `lang` attribute per page.

## The public face

With no default community configured, `/` is a landing page explaining
the concept, linking the public directory (`/events`) and organizer
sign-in (`/org`). With `PLI_COHORT_ID` set, `/` serves that community
exactly as v1 did and the landing page lives at `/about`.

## Deployment

```sh
cp .env.example .env   # fill in pepper, cohort, host, SMTP
docker compose up -d --build
docker compose exec pli python -m pli.cli create-cohort \
    --id iut-mmi-2026 --label "IUT MMI 2026" --domains etu.uca.fr --min-cohort 100
```

## Operational invariants — not optional

- **No backups of the data volume.** Ever. A backup is a crush graph that
  survived the reveal. If the file is lost mid-round, the round is void —
  that is the designed failure mode.
- **No access logs.** The app logs nothing about requests; uvicorn runs
  with `--no-access-log`; disable or filter Traefik access logs for this
  router. A timestamped access log correlated with a reveal is a partial
  graph.
- **Mail:** dedicated domain on a transactional provider with message
  retention/archiving disabled. Never the shared Postfix infrastructure.
- **`PLI_PEPPER`** exists only as an environment variable on the host.
  Never in the DB, the image, or git. Rotating it mid-round orphans every
  handle — treat it as fixed for the life of a round.
- Round keys live as files under `PLI_KEYS_DIR`, are destroyed at reveal,
  and must be excluded from any host-level backup along with the DB.

## Trust model (v1, stated honestly)

Addresses are stored as `HMAC-SHA256(pepper, email)` handles plus
`AES-256-GCM(round_key, email)` contact blobs. A database dump alone
reveals nothing. The operator, who holds the pepper, could technically
reconstruct the graph of a live round. The graph is destroyed Saturday
morning. The source is public. That is the trust being extended — say
exactly this in the privacy notice, and never claim more (in particular,
never "end-to-end encrypted"). The v2 design (a Callisto-style OPRF split
across two non-colluding operators) is documented in HANDOFF.md §6 and is
blocked on an organisational prerequisite, not a technical one.
