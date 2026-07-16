"""HTTP surface. Four routes. Every response is deliberately uninformative:

- POST /join always returns the same page, eligible or not (I8).
- POST /declare always returns the same page, whatever the target (I2, I8).
- Nothing anywhere reflects match state before reveal (I3) — match state
  is never queried outside the reveal job at all.

Run uvicorn with --no-access-log. Application code logs nothing about
requests: no bodies, no addresses, no handles.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, rounds
from .config import Settings
from .crypto import KeyStore, handle, seal
from .mailer import Mail, Mailer, make_mailer
from .normalize import is_rfc_shaped, normalise_email
from .ratelimit import RateLimiter

TEMPLATES_DIR = Path(__file__).parent / "templates"

LINK_SUBJECT = "PLI — your sign-in link"
LINK_BODY = """Someone — hopefully you — asked to take part in this week's round.

{url}

The link works once and expires in 30 minutes. If you didn't ask for it,
delete this message; nothing else will happen.
"""

JOIN_IP_LIMIT = (5, 3600)      # 5/hour per IP
JOIN_ADDR_LIMIT = (3, 86400)   # 3/day per address


def create_app(
    settings: Settings | None = None,
    mailer: Mailer | None = None,
    keystore: KeyStore | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    mailer = mailer or make_mailer(settings)
    keystore = keystore or KeyStore(settings.keys_dir)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(settings.db_path)
        db.init_db(conn)
        conn.close()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.mailer = mailer
    app.state.keystore = keystore

    def get_conn() -> sqlite3.Connection:
        return db.connect(settings.db_path)

    def render(name: str, request: Request, **context) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name=name, context=context)

    def cohort_row(conn) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM cohorts WHERE id = ?", (settings.cohort_id,)
        ).fetchone()

    def session_participant(request: Request, conn) -> tuple[int, bytes] | None:
        """(round_id, handle) if the cookie is valid, its round is the
        current open round, and the handle is a participant of it."""
        value = request.cookies.get("pli_session")
        if not value:
            return None
        parsed = auth.verify_session(settings.pepper, value)
        if parsed is None:
            return None
        round_id, h = parsed
        open_round = rounds.current_open_round(conn, settings.cohort_id)
        if open_round is None or open_round["id"] != round_id:
            return None
        row = conn.execute(
            "SELECT 1 FROM participants WHERE round_id = ? AND handle = ?",
            (round_id, h),
        ).fetchone()
        return (round_id, h) if row else None

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        conn = get_conn()
        try:
            cohort = cohort_row(conn)
            latest = rounds.latest_round(conn, settings.cohort_id)
            status = latest["status"] if latest else "none"
            return render(
                "index.html",
                request,
                cohort=cohort,
                round_status=status,
                closes_at=latest["closes_at"] if latest else None,
                reveal_at=latest["reveal_at"] if latest else None,
                min_cohort=cohort["min_cohort"] if cohort else 100,
            )
        finally:
            conn.close()

    @app.post("/join", response_class=HTMLResponse)
    def join(request: Request, email: str = Form("")):
        """Always the same page. Eligibility, round state, rate limiting —
        none of it changes the response (I8)."""
        conn = get_conn()
        try:
            try:
                client_ip = request.client.host if request.client else "unknown"
                if not limiter.allow(f"ip:{client_ip}", *JOIN_IP_LIMIT):
                    raise _Silent()
                if not is_rfc_shaped(email):
                    raise _Silent()
                norm = normalise_email(email)
                cohort = cohort_row(conn)
                if cohort is None:
                    raise _Silent()
                domains = json.loads(cohort["email_domains"])
                if norm.rpartition("@")[2] not in domains:
                    raise _Silent()
                open_round = rounds.current_open_round(conn, settings.cohort_id)
                if open_round is None:
                    raise _Silent()
                h = handle(settings.pepper, norm)
                if not limiter.allow(f"addr:{h.hex()}", *JOIN_ADDR_LIMIT):
                    raise _Silent()
                round_key = keystore.load(open_round["id"])
                if round_key is None:
                    raise _Silent()
                with conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO participants (round_id, handle, contact) VALUES (?, ?, ?)",
                        (open_round["id"], h, seal(round_key, norm)),
                    )
                token = auth.issue_magic_link(conn, open_round["id"], h)
                mailer.send(
                    Mail(to=norm, subject=LINK_SUBJECT,
                         body=LINK_BODY.format(url=f"{settings.base_url}/s/{token}"))
                )
            except _Silent:
                pass
            except Exception:
                pass  # never let an internal error differentiate the response
            return render("joined.html", request)
        finally:
            conn.close()

    @app.get("/s/{token}", response_class=HTMLResponse)
    def signin(request: Request, token: str):
        conn = get_conn()
        try:
            parsed = auth.redeem_magic_link(conn, token)
            if parsed is None:
                return render("link_invalid.html", request)
            round_id, h = parsed
            open_round = rounds.current_open_round(conn, settings.cohort_id)
            if open_round is None or open_round["id"] != round_id:
                return render("link_invalid.html", request)
            response = RedirectResponse("/declare", status_code=303)
            response.set_cookie(
                "pli_session",
                auth.sign_session(settings.pepper, round_id, h),
                max_age=int(auth.SESSION_TTL.total_seconds()),
                httponly=True,
                samesite="lax",
                secure=settings.secure_cookies,
            )
            return response
        finally:
            conn.close()

    @app.get("/declare", response_class=HTMLResponse)
    def declare_form(request: Request):
        conn = get_conn()
        try:
            who = session_participant(request, conn)
            if who is None:
                return RedirectResponse("/", status_code=303)
            round_id, h = who
            used = conn.execute(
                "SELECT COUNT(*) AS n FROM declarations WHERE round_id = ? AND src = ?",
                (round_id, h),
            ).fetchone()["n"]
            return render("declare.html", request, remaining=rounds.MAX_DECLARATIONS - used)
        finally:
            conn.close()

    @app.post("/declare", response_class=HTMLResponse)
    def declare(request: Request, targets: list[str] = Form(default=[])):
        """Validates format only. Stores HMAC pairs. Same response
        regardless of anything (I2, I8). One-way door: nothing is
        retrievable afterwards."""
        conn = get_conn()
        try:
            who = session_participant(request, conn)
            if who is None:
                return RedirectResponse("/", status_code=303)
            round_id, h = who
            try:
                for target in targets[: rounds.MAX_DECLARATIONS]:
                    if not is_rfc_shaped(target):
                        continue
                    dst = handle(settings.pepper, normalise_email(target))
                    used = conn.execute(
                        "SELECT COUNT(*) AS n FROM declarations WHERE round_id = ? AND src = ?",
                        (round_id, h),
                    ).fetchone()["n"]
                    if used >= rounds.MAX_DECLARATIONS:
                        break
                    with conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO declarations (round_id, src, dst) VALUES (?, ?, ?)",
                            (round_id, h, dst),
                        )
            except Exception:
                pass  # the response must not vary
            return render("recorded.html", request)
        finally:
            conn.close()

    return app


class _Silent(Exception):
    """Raised to abandon /join processing without changing the response."""


def _default_app():
    return create_app()


try:  # module-level app for `uvicorn pli.app:app`; absent env is fine for tests
    app = _default_app()
except RuntimeError:  # PLI_PEPPER not configured
    app = None
