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
python -m pytest
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
python -m pli.jobs open    # Monday 00:00 Europe/Paris
python -m pli.jobs close   # Friday 23:59 — voids the round below min_cohort
python -m pli.jobs reveal  # Saturday 08:00 — mails pairs, deletes everything
```

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
