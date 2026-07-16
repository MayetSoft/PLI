"""The non-negotiable invariants I1–I8 (HANDOFF.md §2).

These tests are the spec; the application code is an implementation
detail. If a change makes one of these red, the change is wrong.
"""

import sqlite3

from fastapi.testclient import TestClient

from conftest import (
    COHORT,
    DOMAIN,
    close_round,
    connect,
    declare,
    reveal_round,
    round_id,
    signup,
)

ALICE = f"alice@{DOMAIN}"
BOB = f"bob@{DOMAIN}"
CAROL = f"carol@{DOMAIN}"
DAVE = f"dave@{DOMAIN}"
# Never signs up. Eligible domain, so silence is not explainable by ineligibility.
GHOST = f"ghost@{DOMAIN}"
OUTSIDER = "outsider@elsewhere.example"


def test_i1_named_non_participant_receives_nothing(app, mailer):
    """I1: a named non-participant receives zero communication of any kind."""
    alice = signup(app, mailer, ALICE)
    declare(alice, GHOST, OUTSIDER)
    # A real match, so the reveal actually sends mail to somebody.
    bob = signup(app, mailer, BOB)
    carol = signup(app, mailer, CAROL)
    declare(bob, CAROL)
    declare(carol, BOB)

    close_round(app)
    reveal_round(app, mailer)

    assert all(m.to not in (GHOST, OUTSIDER) for m in mailer.sent)
    matched = {m.to for m in mailer.sent if "/s/" not in m.body}
    assert matched == {BOB, CAROL}


def test_i2_write_response_independent_of_reciprocity(app, mailer):
    """I2: POST /declare returns an identical response whether or not the
    target reciprocates."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    carol = signup(app, mailer, CAROL)

    r_not_reciprocal = declare(bob, ALICE)        # alice has not named bob
    r_reciprocal = declare(alice, BOB)            # bob has already named alice
    r_never_registered = declare(carol, OUTSIDER)  # target does not exist at all

    assert r_not_reciprocal.status_code == r_reciprocal.status_code == r_never_registered.status_code
    assert r_not_reciprocal.content == r_reciprocal.content == r_never_registered.content


def test_i3_no_signal_before_reveal(app, mailer):
    """I3: before reveal, no endpoint returns match-derived data. A matched
    participant's view is byte-identical to an unmatched one's."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    carol = signup(app, mailer, CAROL)
    declare(alice, BOB)
    declare(bob, ALICE)      # alice and bob are now a reciprocal pair in escrow
    declare(carol, GHOST)    # carol is not

    for path in ("/", "/declare"):
        matched_view = alice.get(path)
        unmatched_view = carol.get(path)
        assert matched_view.content == unmatched_view.content

    # And no mail moved at write time.
    assert all("/s/" in m.body for m in mailer.sent)


def test_i4_declarations_immutable_cap_non_refillable(app, mailer):
    """I4: no DELETE/PATCH on declarations; the cap of 3 does not refill."""
    dave = signup(app, mailer, DAVE)
    declare(dave, f"one@{DOMAIN}")
    declare(dave, f"two@{DOMAIN}")
    declare(dave, f"three@{DOMAIN}")
    declare(dave, f"four@{DOMAIN}")          # over cap: silently not stored
    declare(dave, f"one@{DOMAIN}")           # duplicate: no effect

    conn = connect(app)
    n = conn.execute("SELECT COUNT(*) AS n FROM declarations").fetchone()["n"]
    conn.close()
    assert n == 3

    assert dave.request("DELETE", "/declare").status_code == 405
    assert dave.request("PATCH", "/declare").status_code == 405


def test_i5_absence_indistinguishable_from_non_participation(app, mailer):
    """I5: after close+reveal, what a played-but-unmatched participant
    receives is byte-identical to what a non-player receives: nothing."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    carol = signup(app, mailer, CAROL)   # plays, is not matched
    signup(app, mailer, DAVE)            # signs in, never declares
    declare(alice, BOB)
    declare(bob, ALICE)
    declare(carol, ALICE)                # unreciprocated

    sent_before = len(mailer.sent)
    close_round(app)
    reveal_round(app, mailer)

    post_reveal = mailer.sent[sent_before:]
    to_carol = [m for m in post_reveal if m.to == CAROL]   # played, no match
    to_dave = [m for m in post_reveal if m.to == DAVE]     # did not play
    to_ghost = [m for m in post_reveal if m.to == GHOST]   # never signed up
    assert to_carol == to_dave == to_ghost == []
    assert {m.to for m in post_reveal} == {ALICE, BOB}


def test_i6_crush_graph_does_not_survive_reveal(app, mailer):
    """I6: after the reveal job, the round's rows are gone. All of them."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    declare(alice, BOB, GHOST)
    declare(bob, ALICE)

    close_round(app)
    rid = round_id(app)
    reveal_round(app, mailer)

    conn = connect(app)
    for table in ("declarations", "participants", "magic_links"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    assert conn.execute("SELECT status FROM rounds WHERE id = ?", (rid,)).fetchone()["status"] == "revealed"
    conn.close()
    assert app.state.keystore.load(rid) is None


def test_i7_under_threshold_nothing_runs(app, mailer):
    """I7: under min_cohort the round is voided, everything is deleted,
    nobody is notified of anything but 'no round this week'."""
    conn = connect(app)
    conn.execute("UPDATE cohorts SET min_cohort = 100 WHERE id = ?", (COHORT,))
    conn.commit()
    conn.close()

    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)
    declare(alice, BOB)
    declare(bob, ALICE)      # mutual — and it must still never surface

    sent_before = len(mailer.sent)
    assert close_round(app) == "voided"
    assert reveal_round(app, mailer) == 0   # reveal on a voided round is a no-op

    assert mailer.sent[sent_before:] == []
    conn = connect(app)
    for table in ("declarations", "participants", "magic_links"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    conn.close()

    page = TestClient(app).get("/")
    assert "No round this week" in page.text


def test_i8_no_enumeration_via_declare(app, mailer):
    """I8: declaring toward a registered address is indistinguishable from
    declaring toward an unregistered one."""
    alice = signup(app, mailer, ALICE)
    bob = signup(app, mailer, BOB)

    r_registered = declare(alice, BOB)        # bob is a participant
    r_unregistered = declare(bob, OUTSIDER)   # outsider is not
    assert r_registered.status_code == r_unregistered.status_code
    assert r_registered.content == r_unregistered.content


def test_i8_no_enumeration_via_join(app, mailer):
    """I8 corollary: /join never confirms eligibility."""
    client = TestClient(app)
    r_eligible = client.post("/join", data={"email": f"someone@{DOMAIN}"})
    r_ineligible = client.post("/join", data={"email": "someone@gmail.com"})
    r_garbage = client.post("/join", data={"email": "not-an-email"})
    assert r_eligible.status_code == r_ineligible.status_code == r_garbage.status_code
    assert r_eligible.content == r_ineligible.content == r_garbage.content
