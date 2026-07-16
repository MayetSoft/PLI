"""CLI and job entry points."""

import secrets
from datetime import timedelta

import pytest

from pli import cli, db as db_mod, jobs, rounds, scheduler
from pli.config import Settings
from pli.crypto import KeyStore
from pli.mailer import RecordingMailer


@pytest.fixture
def env(tmp_path, monkeypatch):
    pepper = secrets.token_hex(32)
    monkeypatch.setenv("PLI_PEPPER", pepper)
    monkeypatch.setenv("PLI_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("PLI_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("PLI_COHORT_ID", "dev")
    monkeypatch.setenv("PLI_MAILER", "memory")
    return Settings.from_env()


def iso(minutes):
    return (rounds.paris_now() + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


def test_cli_init_and_cohort_and_event(env, capsys):
    assert cli.main(["init-db"]) == 0
    assert cli.main([
        "create-cohort", "--id", "dev", "--label", "Dev",
        "--domains", "example.edu", "--min-cohort", "2",
    ]) == 0
    assert cli.main([
        "create-event", "--id", "conf", "--label", "Conf", "--join-code", "sesame",
        "--opens", iso(-5), "--closes", iso(60), "--reveal", iso(90),
    ]) == 0
    out = capsys.readouterr().out
    assert "db ready" in out and "cohort dev ready" in out and "/e/conf" in out


def test_cli_create_event_rejections(env):
    with pytest.raises(SystemExit):
        cli.main(["create-event", "--id", "Bad_Id!", "--label", "x", "--join-code", "c",
                  "--opens", iso(0), "--closes", iso(60), "--reveal", iso(90)])
    with pytest.raises(SystemExit):
        cli.main(["create-event", "--id", "ok", "--label", "x",
                  "--opens", iso(0), "--closes", iso(60), "--reveal", iso(90)])


def test_cli_moderation(env, capsys):
    cli.main(["init-db"])
    cli.main(["create-event", "--id", "party", "--label", "Party", "--join-code", "c",
              "--opens", iso(-5), "--closes", iso(60), "--reveal", iso(90)])

    from pli import organizers

    conn = db_mod.connect(env.db_path)
    organizers.flag_event(conn, env.pepper, "party", "spam", "fake", "9.9.9.9")
    conn.close()

    assert cli.main(["flags"]) == 0
    assert cli.main(["suspend", "--id", "party"]) == 0
    assert cli.main(["unsuspend", "--id", "party"]) == 0
    assert cli.main(["ban-organizer", "--email", "nobody@x.example"]) == 0
    out = capsys.readouterr().out
    assert "1 flag(s)" in out and "party suspended" in out
    assert "flags cleared" in out and "0 event(s) suspended" in out


def test_jobs_lifecycle(env):
    conn = db_mod.connect(env.db_path)
    db_mod.init_db(conn)
    db_mod.create_cohort(conn, "dev", "Dev", ["example.edu"], min_cohort=2)
    conn.close()

    assert jobs.run_close(env) == "no-open-round"      # nothing open yet
    assert jobs.run_reveal(env) == 0                   # nothing closed yet

    round_id = jobs.run_open(env)
    assert round_id >= 1
    assert jobs.run_close(env) == "voided"             # 0 participants < 2

    # A closed round with participants reveals (0 pairs here).
    conn = db_mod.connect(env.db_path)
    ks = KeyStore(env.keys_dir)
    rid = rounds.open_round(conn, ks, "dev", rounds.paris_now() + timedelta(days=7))
    conn.execute("UPDATE rounds SET status = 'closed' WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    assert jobs.run_reveal(env) == 0

    assert set(jobs.run_tick(env)) == {"opened", "closed", "revealed", "voided"}


def test_jobs_main(env, capsys):
    assert jobs.main(["nonsense"]) == 2
    assert jobs.main([]) == 2
    conn = db_mod.connect(env.db_path)
    db_mod.init_db(conn)
    db_mod.create_cohort(conn, "dev", "Dev", ["example.edu"], min_cohort=2)
    conn.close()
    assert jobs.main(["open"]) == 0
    assert jobs.main(["close"]) == 0
    assert jobs.main(["reveal"]) == 0
    assert jobs.main(["tick"]) == 0
    out = capsys.readouterr().out
    assert "open" in out and "close:" in out and "reveal:" in out and "opened=" in out


def test_scheduler_is_a_single_minute_tick(env):
    sched = scheduler.build_scheduler(env)
    job_names = [j.name for j in sched.get_jobs()]
    assert job_names == ["tick"]
    assert str(sched.get_jobs()[0].trigger.fields[6]) == "*"  # every minute
