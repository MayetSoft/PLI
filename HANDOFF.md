# HANDOFF.md — "PLI" (codename)

A round-based mutual-declaration escrow. Two people privately name each other; only
then is either told. Nothing else is ever revealed, to anyone, ever.

Codename `PLI` throughout (from *pli cacheté* — a sealed envelope lodged with a
notary, opened only on a defined condition). Replace before launch.

---

## 0. Prime directive

**Non-disclosure is the product. Every other feature is negotiable; this one is not.**

If a design choice trades a bit of confidentiality for growth, engagement, or
convenience — reject it. There is no growth worth the failure mode here. The
failure mode is a person learning they were not loved, or a person receiving
unwanted romantic contact they cannot stop.

When in doubt during implementation: **emit silence.**

---

## 1. The mechanic

1. A round opens Monday 00:00 and closes Friday 23:59 (Europe/Paris).
2. During the round, a participant may name **up to 3 people** by email address.
3. Named people are **never notified**. Not on write, not at close, not ever.
4. Saturday 08:00, a batch job computes reciprocal pairs.
5. Reciprocal pairs — and only reciprocal pairs — each receive the other's email.
6. Everything else is deleted. The crush graph does not survive the reveal.
7. Next Monday, a new round. Prior rounds leave no residue.

That's the whole product. No profiles. No photos. No chat. No browsing. No feed.
No scores. No "you have 2 pending." On match, both parties get an email address
and the conversation is theirs.

---

## 2. Non-negotiable invariants

Implement these as **tests first**. They are the spec; the code is an
implementation detail.

| # | Invariant | Test |
|---|---|---|
| I1 | A named non-participant receives zero communication of any kind | Assert no mail queued for any target address absent from `participants` |
| I2 | No user-visible state changes on write | POST /declare returns identical response whether or not target reciprocates |
| I3 | No signal before reveal | No endpoint returns match-derived data before `reveal_at` |
| I4 | Declarations are immutable within a round | No DELETE/PATCH on declarations. Cap of 3 is non-refillable. |
| I5 | Absence is indistinguishable from non-participation | Close-of-round mail is byte-identical for "played, no match" and "did not play" |
| I6 | The crush graph does not survive reveal | After reveal job, `declarations` for that round is empty. Assert row count 0. |
| I7 | Under threshold, nothing runs | If participants < `MIN_COHORT`, void round, delete all, notify nobody of anything but "no round this week" |
| I8 | No enumeration | Declaring toward an address reveals nothing about whether that address is registered |

**I1, I5 and I8 are the ones that will be tempting to break. Do not break them.**

### I5 in detail — the one most builds get wrong

If the no-match email says "sorry, no matches this week," you have told someone
they were not loved. That is the exact harm the product exists to prevent.

Therefore: **either send nothing at all to non-matched participants, or send a
message that a non-participant would also plausibly receive.** The safest
implementation is *send nothing*. Silence is the only safe null.

Matched pairs get mail. Nobody else does. That asymmetry is unavoidable — a
matched person knows they matched — but it must not extend one bit further.

---

## 3. What is explicitly out of scope

Do not implement these. They were considered and rejected:

- ❌ **Notifying named non-participants** ("someone has a crush on you"). Inverts
  the prime directive. Creates a harassment channel with a delivery guarantee,
  a coercion vector, and an out-of-band probing oracle. Also: unsolicited direct
  communication to a non-consenting individual (ePrivacy + GDPR).
- ❌ **Friend-forwarding / matchmaker relay.** To ask C to forward to B you must
  disclose B as a target and imply A as a source. Leaks the confession to a
  third party and recruits them to apply social pressure. No version of this
  is safe.
- ❌ **Contact-list upload.** Third-party personal data, no legal basis. CNIL is
  unambiguous. Users type an address they already know.
- ❌ **Social login for friend graphs.** Meta and LinkedIn no longer expose them;
  X's API is priced out. Mastodon OAuth (mutuals-only, as `TheDavidDelta/crash`
  does) is the only viable variant — park it as a possible v2, not v1.
- ❌ **Un-declare.** Creates a probing oracle: declare → undeclare → infer.
- ❌ **Any counter, badge, streak, or engagement surface.**

---

## 4. Stack

Match the existing infrastructure:

- **Python 3.12 / FastAPI**
- **Jinja2 + HTMX** — server-rendered. No SPA. No client-side state.
- **SQLite** (WAL). Single file. The dataset is tiny and ephemeral by design.
- **APScheduler** or a plain cron container for the reveal job.
- **Docker + Traefik**, labels consistent with the existing stack.
- **Mail:** a dedicated domain and a transactional provider (Postmark / Scaleway
  TEM / OVH). **Do not send from the existing Postfix/Netcup infrastructure** —
  that mail reputation carries unrelated commercial traffic and must not be
  exposed to this.

No Redis, no Celery, no Postgres. If you reach for one, the design has drifted.

---

## 5. Data model

```sql
CREATE TABLE rounds (
  id            INTEGER PRIMARY KEY,
  cohort_id     TEXT NOT NULL,
  opens_at      TEXT NOT NULL,
  closes_at     TEXT NOT NULL,
  reveal_at     TEXT NOT NULL,
  status        TEXT NOT NULL,  -- open | closed | revealed | voided
  UNIQUE(cohort_id, opens_at)
);

CREATE TABLE cohorts (
  id            TEXT PRIMARY KEY,      -- e.g. 'iut-mmi-2026'
  label         TEXT NOT NULL,
  email_domains TEXT NOT NULL,         -- JSON array, e.g. ["etu.uca.fr"]
  min_cohort    INTEGER NOT NULL DEFAULT 100
);

-- One row per verified participant per round. Deleted at reveal.
CREATE TABLE participants (
  round_id      INTEGER NOT NULL REFERENCES rounds(id),
  handle        BLOB NOT NULL,         -- HMAC(pepper, normalised_email)
  contact       BLOB NOT NULL,         -- AES-GCM(round_key, email) — released only on match
  PRIMARY KEY (round_id, handle)
);

-- The escrow. Deleted at reveal, unconditionally.
CREATE TABLE declarations (
  round_id      INTEGER NOT NULL REFERENCES rounds(id),
  src           BLOB NOT NULL,         -- HMAC(pepper, normalised_email of declarer)
  dst           BLOB NOT NULL,         -- HMAC(pepper, normalised_email of target)
  PRIMARY KEY (round_id, src, dst)
);

CREATE TABLE magic_links (
  token_hash    BLOB PRIMARY KEY,
  round_id      INTEGER NOT NULL,
  handle        BLOB NOT NULL,
  expires_at    TEXT NOT NULL,
  used_at       TEXT
);
```

Note what is **absent**: no `users` table, no persistent identity, no history, no
`created_at` on declarations (a timestamp is a side channel — it correlates
declarations with sessions and narrows the graph). Participation does not persist
across rounds. Someone who plays every week for a year leaves no trail.

### Email normalisation

Lowercase, strip whitespace, strip `+tag` suffixes, apply Gmail dot-folding **only
if** the cohort domain is Gmail. Normalisation must be identical for `src` and
`dst` or reciprocity silently fails. **Write property tests for this.** This is
where the bug will be.

---

## 6. Cryptography — be honest about what it buys

### v1 (build this)

- `pepper`: 32 random bytes, **environment variable only**, never in the DB, never
  in the image, never in git.
- `handle = HMAC-SHA256(pepper, normalised_email)`
- `round_key`: 32 random bytes per round, held in memory / env for the round's
  lifetime, destroyed after reveal.
- `contact = AES-256-GCM(round_key, email)` — the only path back to a real address.

**What this protects against:** a database dump. An attacker with `pli.db` and
without the pepper has a graph of opaque 32-byte blobs and no roster to test
against. They cannot invert it.

**What this does NOT protect against:** you. The operator holds the pepper and can
compute `handle` for any candidate address. With a bounded cohort (a few hundred
known institutional addresses) the operator can brute-force the entire graph in
milliseconds.

**State this plainly in the privacy notice.** Do not claim cryptographic
guarantees the architecture does not deliver. The v1 trust model is:

> The operator can technically reconstruct the graph. The operator is one person.
> The graph is destroyed Saturday morning. The source code is public. That is the
> trust you are extending. If that is not enough, do not play.

That is an honest, defensible position. "End-to-end encrypted" would be a lie, and
getting caught in it would be terminal.

### v2 (design note — do not build yet)

The real construction is **Callisto's**: an OPRF held by a *separate,
non-colluding operator*. The client blinds the target identifier; the OPRF node
evaluates without learning it; the matching node stores the result without holding
the key. Neither party alone can reconstruct the graph.

- Rajan, Qin, Archer, Boneh, Lepoint, Varia — *Callisto: A Cryptographic Approach
  to Detecting Serial Perpetrators of Sexual Misconduct*, ACM COMPASS 2018,
  doi:10.1145/3209811.3212699. PDF: `par.nsf.gov/servlets/purl/10061833`
- White paper: `projectcallisto.org/cryptographic-approach`
- Adjacent literature: private set intersection (PSI), oblivious PRF, socialist
  millionaire problem.

Structurally identical problem: *N parties name a target; reveal iff k parties
name the same target; leak nothing otherwise, not even to the server operator.*
Callisto sets k=2 on a shared third party. PLI sets k=2 on each other.

**The blocker is organisational, not technical.** It requires a second operator in
a genuinely separate trust domain who will run a node and not collude. Until that
person exists, v2 is theatre. Do not half-build it.

---

## 7. Flows

### Sign-up (Monday–Friday)

```
GET  /              → round status, countdown, the rules, the trust model
POST /join          → { email } ; must match cohort's email_domains
                      → always returns the same page: "if that address is
                        eligible, check your inbox"  ← never confirm eligibility
                      → rate-limited per IP and per address
GET  /s/{token}     → single-use, 30min TTL, marks used_at, sets session cookie
                      scoped to this round only
```

### Declare

```
GET  /declare       → form: up to 3 email addresses. Shows count remaining.
POST /declare       → validates format only. Does NOT validate existence.
                      Stores HMAC pair. No confirmation of target status.
                      → "Recorded. Nothing more will happen until Saturday."
                      → Same response regardless of anything.
```

Declaring toward an address that never signs up must be **indistinguishable** from
declaring toward one that does. No "hmm, we don't recognise that address." No
autocomplete. No validation beyond RFC-shape.

**After submitting, the declarations are not retrievable.** The user cannot see
their own list. This is deliberate: you cannot be coerced into showing what you
cannot retrieve. Warn clearly before submit — this is a one-way door.

### Close (Friday 23:59)

Set `status = closed`. If `COUNT(participants) < min_cohort`: void the round,
delete everything, publish "no round this week" on the homepage. Notify nobody
individually. A voided round must be indistinguishable from a quiet one.

### Reveal (Saturday 08:00)

```sql
SELECT a.src, a.dst FROM declarations a
JOIN declarations b
  ON a.src = b.dst AND a.dst = b.src AND a.round_id = b.round_id
WHERE a.round_id = ? AND a.src < a.dst;
```

For each pair: decrypt both `contact` values, send each party the other's address.
One email. No metadata. No "you both crushed each other on Tuesday."

Then, **unconditionally and in the same transaction**:

```sql
DELETE FROM declarations WHERE round_id = ?;
DELETE FROM participants WHERE round_id = ?;
DELETE FROM magic_links  WHERE round_id = ?;
UPDATE rounds SET status = 'revealed' WHERE id = ?;
```

Destroy `round_key`. Run `VACUUM` — SQLite leaves deleted pages recoverable
otherwise, and "we deleted it" must be true at the page level, not just the row
level. **Write a test that greps the raw DB file for a known plaintext address
after reveal and asserts absence.**

The delete must run even if mail delivery fails. Order: compute pairs → send →
delete, with delete in a `finally`. A failed send is a bad week. A surviving graph
is a catastrophe.

### Retention

- Application logs: **no request bodies, no email addresses, no handles.** Log
  status codes and timings only.
- Traefik access logs: strip or disable for this service. A timestamped access log
  correlated with a reveal is a partial graph.
- Mail provider: disable message retention / archiving. Their logs are your logs.
- Backups: **none.** There must be no backup of this database. A backup is a graph
  that survived the reveal. If the file is lost mid-round, the round is void.

---

## 8. Rate limits & abuse

- `POST /join`: 5/hour per IP, 3/day per address.
- `POST /declare`: hard cap 3 per participant per round, enforced in the primary
  key and in application logic.
- Magic links: single use, 30 min TTL.
- No CAPTCHA. If you need one, the cohort is too big or too public.

The bounded cohort *is* the abuse control. A verified institutional email in a
closed domain, a hard cap of 3, and a weekly reset means the worst-case attacker
gets 3 silent declarations per week that produce nothing unless reciprocated.
That's a floor, not a hole.

---

## 9. Launch parameters (not code, but they constrain it)

- **One bounded community. One deadline.** It's an *event*, not a site.
  Time-boxing manufactures density and eliminates churn — there's nothing to
  churn from.
- **Pre-commitment threshold, published:** "if fewer than N sign up, we run
  nothing and delete everything." Removes the fear of being one of six people on
  a dead site, and gives a dignified way to fail. `min_cohort` default 100.
  (Marriage Pact's founders used exactly this reasoning: under 100 and the
  matches aren't any good.)
- **Someone inside the community fronts it. Not the operator.** Never a cohort
  where the operator holds authority, grades, or a career stake.
- **Delete on reveal** is the differentiator, the GDPR posture (Art. 9
  special-category data — this cannot sit at rest), and a good sentence on a
  landing page. All three.
- **Ship the mechanic. Nothing else.**

### Cost

Two emails per participant per round. A thousand participants is two thousand
emails a week — free tier anywhere, or free self-hosted. The cost only explodes if
you message people who didn't sign up, which is the thing that is out of scope.
**There is no funding problem in this design.** If one appears, the design drifted.

---

## 10. Build order

1. Invariant tests I1–I8. **Red first.** They are the spec.
2. Schema + normalisation + property tests on normalisation.
3. Crypto helpers (`handle`, `seal`, `unseal`) + round-trip tests.
4. Magic-link auth.
5. Declare flow.
6. Reveal job + the deletion test (grep the raw file).
7. Close/void job.
8. Templates. Plain, quiet, no illustration, no hearts, no gradient. The tone is
   a notary's office, not a dating app. Sober typography, a lot of white space,
   one accent colour. It should look like it takes itself seriously, because it
   should.
9. Docker + Traefik + cron.

Stop at 9. Do not add features.

---

## Appendix A — the reasoning this spec came from

*(Retained deliberately. If a future contributor wants to add the notification
feature, this is why they must not.)*

### On the threat model being the design

The failure modes are all social, not technical:

| Attack | Fix |
|---|---|
| Shotgun (declare on everyone, wait for hits) | Hard cap: 3. Non-refillable per round. |
| Probing oracle (declare → undeclare → infer) | Locked until round close. No mid-round signal at all. |
| Roster enumeration (who's on this thing?) | You must be able to name someone who never signed up. Their inclusion is only revealed if they named you. |
| Impersonation / fake accounts | Verified email in a bounded domain. |
| Timing leak | Batch reveal. Everyone learns at the same instant. Never on-write. |
| Coercion ("show me your phone") | No list visible after submit. You can't show what you can't retrieve. |
| Absence-as-signal | If nobody matched, the message must be indistinguishable from "you didn't play." |

That last one is subtle and most builds get it wrong. If the no-match email says
"sorry, no matches," you've told someone they were not loved, which is the exact
harm you set out to prevent. Silence is the only safe null.

### On why the notification feature is fatal

Naming a non-participant is fine. **Notifying them is the entire harm.**

- It's a harassment channel with a delivery guarantee — repeatable weekly, forever.
- It's a coercion vector: "did you get my notification? why didn't you reciprocate?"
- It's an out-of-band probing oracle: send, then observe whether the target
  suddenly signs up.
- It's unsolicited direct communication to a non-consenting individual, carrying
  romantic content, requiring third-party contact data with no legal basis.

The pending declaration sits in escrow and dies silently at round close. That is
not a limitation. That is the feature.

### On virality

Growth comes from a flyer, word of mouth, and "my friends are doing it" — the
documented mechanism by which the Marriage Pact reached 58% of Stanford's student
body in under a week from a single viral flyer. It does not come from the system
cold-contacting anyone. The viral mechanic and the safety property are in direct
conflict; the safety property wins, because without it there is no reason for this
to exist.

### On the two constraints inherited from `TheDavidDelta/crash`

Max 3 declarations, and no un-declaring for the duration. Those two constraints
are the entire product. Without the cap it's a slot machine. Without the lock it's
an oracle. Anyone who builds this without both has built something worse than
nothing.
