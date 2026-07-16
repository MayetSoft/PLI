"""HTTP surface. Every response is deliberately uninformative:

- POST .../join always returns the same page, eligible or not (I8).
- POST .../declare always returns the same page, whatever the target (I2, I8).
- Nothing anywhere reflects match state before reveal (I3) — match state
  is never queried outside the reveal job at all.

The root path serves the default community (PLI_COHORT_ID) exactly as it
always has. Events — cohorts with their own timeline — live under
/e/{event-id}, unlisted, on the same handlers with the same invariants.

Run uvicorn with --no-access-log. Application code logs nothing about
requests: no bodies, no addresses, no handles.
"""

from __future__ import annotations

import hmac as hmac_mod
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, organizers, rounds
from .config import Settings
from .crypto import KeyStore, handle, seal
from .mailer import Mail, Mailer, make_mailer
from .normalize import is_rfc_shaped, normalise_email
from .ratelimit import RateLimiter

TEMPLATES_DIR = Path(__file__).parent / "templates"

LINK_SUBJECT = "PLI — your sign-in link"
LINK_BODY = """Someone — hopefully you — asked to take part in this round.

{url}
{note}
The link works once and expires in 30 minutes. If you didn't ask for it,
delete this message; nothing else will happen.
"""

ORG_LINK_SUBJECT = "PLI — organizer sign-in link"
ORG_LINK_BODY = """Someone — hopefully you — asked to sign in as an event organizer.

{url}

The link works once and expires in 30 minutes. If you didn't ask for it,
delete this message; nothing else will happen.
"""

JOIN_IP_LIMIT = (5, 3600)      # 5/hour per IP
JOIN_ADDR_LIMIT = (3, 86400)   # 3/day per address
FLAG_IP_LIMIT = (5, 3600)

EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    def get_conn() -> sqlite3.Connection:
        return db.connect(settings.db_path)

    def render(name: str, request: Request, status_code: int = 200, **context) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name=name, context=context, status_code=status_code
        )

    def get_cohort(conn, cohort_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM cohorts WHERE id = ?", (cohort_id,)).fetchone()

    def fmt_paris(iso: str) -> str:
        return datetime.fromisoformat(iso).astimezone(rounds.PARIS).strftime(
            "%A %d %B %Y at %H:%M (%Z)"
        )

    def mode_of(cohort: sqlite3.Row | None) -> str:
        return "event" if cohort is not None and cohort["schedule"] == "custom" else "weekly"

    def cookie_and_home(cohort_id: str) -> tuple[str, str]:
        """Cookie name and base path for a cohort. The default community
        keeps its original cookie and root paths; events are scoped under
        /e/{id} so concurrent participations don't collide."""
        if cohort_id == settings.cohort_id:
            return "pli_session", ""
        return f"pli_s_{cohort_id}", f"/e/{cohort_id}"

    # ---- shared handlers ------------------------------------------------

    def index_response(request: Request, conn, cohort: sqlite3.Row | None, base_path: str):
        latest = rounds.latest_round(conn, cohort["id"]) if cohort else None
        status = latest["status"] if latest else "none"
        return render(
            "index.html",
            request,
            mode=mode_of(cohort),
            base_path=base_path,
            label=cohort["label"] if cohort else "",
            description=cohort["description"] if cohort else "",
            suspended=bool(cohort and cohort["is_suspended"]),
            join_code_required=bool(cohort and cohort["join_code_hash"]),
            round_status=status,
            opens_fmt=fmt_paris(latest["opens_at"]) if latest else "",
            closes_fmt=fmt_paris(latest["closes_at"]) if latest else "",
            reveal_fmt=fmt_paris(latest["reveal_at"]) if latest else "",
            min_cohort=cohort["min_cohort"] if cohort else 100,
        )

    def join_response(request: Request, conn, cohort: sqlite3.Row | None, email: str, code: str):
        """Always the same page. Eligibility, join code, round state, rate
        limiting — none of it changes the response (I8)."""
        try:
            if cohort is None or cohort["is_suspended"]:
                raise _Silent()
            client_ip = request.client.host if request.client else "unknown"
            if not limiter.allow(f"ip:{client_ip}", *JOIN_IP_LIMIT):
                raise _Silent()
            if not is_rfc_shaped(email):
                raise _Silent()
            norm = normalise_email(email)
            domains = json.loads(cohort["email_domains"])
            if domains and norm.rpartition("@")[2] not in domains:
                raise _Silent()
            code_hash = cohort["join_code_hash"]
            if code_hash is not None:
                presented = handle(settings.pepper, "code:" + code.strip())
                if not hmac_mod.compare_digest(presented, bytes(code_hash)):
                    raise _Silent()
            open_round = rounds.current_open_round(conn, cohort["id"])
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
            intro = (cohort["mail_intro"] or "").strip()
            note = rounds.ORGANIZER_NOTE.format(intro=intro) if intro else ""
            mailer.send(
                Mail(to=norm, subject=LINK_SUBJECT,
                     body=LINK_BODY.format(url=f"{settings.base_url}/s/{token}", note=note))
            )
        except _Silent:
            pass
        except Exception:
            pass  # never let an internal error differentiate the response
        return render("joined.html", request)

    def session_participant(request: Request, conn, cookie_name: str, cohort_id: str):
        """(round_id, handle) if the cookie is valid, its round is open,
        belongs to this cohort, and the handle is a participant of it."""
        value = request.cookies.get(cookie_name)
        if not value:
            return None
        parsed = auth.verify_session(settings.pepper, value)
        if parsed is None:
            return None
        round_id, h = parsed
        round_row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
        if round_row is None or round_row["status"] != "open" or round_row["cohort_id"] != cohort_id:
            return None
        row = conn.execute(
            "SELECT 1 FROM participants WHERE round_id = ? AND handle = ?",
            (round_id, h),
        ).fetchone()
        return (round_id, h) if row else None

    def declare_form_response(request: Request, conn, cohort: sqlite3.Row | None):
        if cohort is None or cohort["is_suspended"]:
            return RedirectResponse("/", status_code=303)
        cookie_name, base_path = cookie_and_home(cohort["id"])
        who = session_participant(request, conn, cookie_name, cohort["id"])
        if who is None:
            return RedirectResponse(base_path or "/", status_code=303)
        round_id, h = who
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM declarations WHERE round_id = ? AND src = ?",
            (round_id, h),
        ).fetchone()["n"]
        return render(
            "declare.html", request,
            remaining=rounds.MAX_DECLARATIONS - used, base_path=base_path,
            mode=mode_of(cohort),
        )

    def declare_post_response(request: Request, conn, cohort: sqlite3.Row | None, targets: list[str]):
        """Validates format only. Stores HMAC pairs. Same response
        regardless of anything (I2, I8). One-way door: nothing is
        retrievable afterwards."""
        if cohort is None or cohort["is_suspended"]:
            return RedirectResponse("/", status_code=303)
        cookie_name, base_path = cookie_and_home(cohort["id"])
        who = session_participant(request, conn, cookie_name, cohort["id"])
        if who is None:
            return RedirectResponse(base_path or "/", status_code=303)
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
        return render("recorded.html", request, mode=mode_of(cohort))

    # ---- default community (unchanged behaviour) ------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        conn = get_conn()
        try:
            cohort = get_cohort(conn, settings.cohort_id) if settings.cohort_id else None
            if cohort is None:
                return render("landing.html", request)
            return index_response(request, conn, cohort, "")
        finally:
            conn.close()

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        return render("landing.html", request)

    @app.get("/events", response_class=HTMLResponse)
    def public_events(request: Request):
        """Public directory. Private events never appear anywhere; public
        events appear only while a round is scheduled or open."""
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT c.id, c.label, c.description, r.status AS round_status,"
                "       r.opens_at, r.closes_at"
                " FROM cohorts c JOIN rounds r ON r.cohort_id = c.id"
                " WHERE c.visibility = 'public' AND c.is_suspended = 0"
                "   AND r.status IN ('scheduled', 'open')"
                " ORDER BY r.opens_at",
            ).fetchall()
            events = [
                {
                    "id": r["id"],
                    "label": r["label"],
                    "description": r["description"],
                    "round_status": r["round_status"],
                    "opens_fmt": fmt_paris(r["opens_at"]),
                    "closes_fmt": fmt_paris(r["closes_at"]),
                }
                for r in rows
            ]
            return render("events.html", request, events=events)
        finally:
            conn.close()

    @app.post("/join", response_class=HTMLResponse)
    def join(request: Request, email: str = Form(""), code: str = Form("")):
        conn = get_conn()
        try:
            return join_response(request, conn, get_cohort(conn, settings.cohort_id), email, code)
        finally:
            conn.close()

    @app.get("/declare", response_class=HTMLResponse)
    def declare_form(request: Request):
        conn = get_conn()
        try:
            return declare_form_response(request, conn, get_cohort(conn, settings.cohort_id))
        finally:
            conn.close()

    @app.post("/declare", response_class=HTMLResponse)
    def declare(request: Request, targets: list[str] = Form(default=[])):
        conn = get_conn()
        try:
            return declare_post_response(request, conn, get_cohort(conn, settings.cohort_id), targets)
        finally:
            conn.close()

    # ---- events: same handlers, own timeline, unlisted -------------------

    def resolve_event(conn, event_id: str) -> sqlite3.Row | None:
        if not EVENT_ID_RE.match(event_id):
            return None
        return get_cohort(conn, event_id)

    @app.get("/e/{event_id}", response_class=HTMLResponse)
    def event_index(request: Request, event_id: str):
        if event_id == settings.cohort_id:
            return RedirectResponse("/", status_code=303)
        conn = get_conn()
        try:
            cohort = resolve_event(conn, event_id)
            if cohort is None:
                return render("not_found.html", request, status_code=404)
            return index_response(request, conn, cohort, f"/e/{event_id}")
        finally:
            conn.close()

    @app.post("/e/{event_id}/join", response_class=HTMLResponse)
    def event_join(request: Request, event_id: str, email: str = Form(""), code: str = Form("")):
        conn = get_conn()
        try:
            cohort = resolve_event(conn, event_id)
            if cohort is None or event_id == settings.cohort_id:
                return render("not_found.html", request, status_code=404)
            return join_response(request, conn, cohort, email, code)
        finally:
            conn.close()

    @app.get("/e/{event_id}/declare", response_class=HTMLResponse)
    def event_declare_form(request: Request, event_id: str):
        conn = get_conn()
        try:
            cohort = resolve_event(conn, event_id)
            if cohort is None or event_id == settings.cohort_id:
                return render("not_found.html", request, status_code=404)
            return declare_form_response(request, conn, cohort)
        finally:
            conn.close()

    @app.post("/e/{event_id}/declare", response_class=HTMLResponse)
    def event_declare(request: Request, event_id: str, targets: list[str] = Form(default=[])):
        conn = get_conn()
        try:
            cohort = resolve_event(conn, event_id)
            if cohort is None or event_id == settings.cohort_id:
                return render("not_found.html", request, status_code=404)
            return declare_post_response(request, conn, cohort, targets)
        finally:
            conn.close()

    # ---- abuse flags ------------------------------------------------------

    @app.get("/e/{event_id}/report", response_class=HTMLResponse)
    def report_form(request: Request, event_id: str):
        conn = get_conn()
        try:
            if resolve_event(conn, event_id) is None:
                return render("not_found.html", request, status_code=404)
            return render(
                "report.html", request,
                base_path=f"/e/{event_id}", reasons=organizers.FLAG_REASONS,
            )
        finally:
            conn.close()

    @app.post("/e/{event_id}/report", response_class=HTMLResponse)
    def report(request: Request, event_id: str, reason: str = Form("other"), detail: str = Form("")):
        conn = get_conn()
        try:
            if resolve_event(conn, event_id) is None:
                return render("not_found.html", request, status_code=404)
            client_ip = request.client.host if request.client else "unknown"
            if limiter.allow(f"flag:{client_ip}", *FLAG_IP_LIMIT):
                organizers.flag_event(conn, settings.pepper, event_id, reason, detail, client_ip)
            return render("reported.html", request)
        finally:
            conn.close()

    # ---- organizers --------------------------------------------------------

    def current_organizer(request: Request, conn) -> sqlite3.Row | None:
        value = request.cookies.get("pli_org")
        if not value:
            return None
        organizer_id = auth.verify_org_session(settings.pepper, value)
        if organizer_id is None:
            return None
        org = organizers.get_organizer(conn, organizer_id)
        if org is None or org["status"] != "active":
            return None
        return org

    def owned_event(conn, org: sqlite3.Row, event_id: str) -> sqlite3.Row | None:
        cohort = get_cohort(conn, event_id) if EVENT_ID_RE.match(event_id) else None
        if cohort is None or cohort["organizer_id"] != org["id"]:
            return None
        return cohort

    def form_values(cohort: sqlite3.Row | None, round_row: sqlite3.Row | None) -> dict:
        def local(iso: str) -> str:
            return datetime.fromisoformat(iso).astimezone(rounds.PARIS).strftime("%Y-%m-%dT%H:%M")

        if cohort is None:
            return {"visibility": "private", "min_cohort": 100}
        return {
            "label": cohort["label"],
            "description": cohort["description"],
            "mail_intro": cohort["mail_intro"],
            "visibility": cohort["visibility"],
            "domains": ", ".join(json.loads(cohort["email_domains"])),
            "join_code": "",
            "min_cohort": cohort["min_cohort"],
            "opens": local(round_row["opens_at"]) if round_row else "",
            "closes": local(round_row["closes_at"]) if round_row else "",
            "reveal": local(round_row["reveal_at"]) if round_row else "",
        }

    async def read_form(request: Request) -> dict:
        return {k: v for k, v in (await request.form()).items()}

    @app.get("/org", response_class=HTMLResponse)
    def org_home(request: Request):
        conn = get_conn()
        try:
            if current_organizer(request, conn) is not None:
                return RedirectResponse("/org/dashboard", status_code=303)
            return render("org_login.html", request)
        finally:
            conn.close()

    @app.post("/org/login", response_class=HTMLResponse)
    def org_login(request: Request, email: str = Form("")):
        """Same page whatever happens — organizer accounts are not
        enumerable either."""
        conn = get_conn()
        try:
            try:
                client_ip = request.client.host if request.client else "unknown"
                if not limiter.allow(f"orgip:{client_ip}", *JOIN_IP_LIMIT):
                    raise _Silent()
                if not is_rfc_shaped(email):
                    raise _Silent()
                norm = normalise_email(email)
                if not limiter.allow(f"orgaddr:{norm}", *JOIN_ADDR_LIMIT):
                    raise _Silent()
                existing = organizers.organizer_by_email(conn, norm)
                if existing is not None and existing["status"] != "active":
                    raise _Silent()
                token = auth.issue_org_link(conn, norm)
                mailer.send(
                    Mail(to=norm, subject=ORG_LINK_SUBJECT,
                         body=ORG_LINK_BODY.format(url=f"{settings.base_url}/org/s/{token}"))
                )
            except _Silent:
                pass
            except Exception:
                pass
            return render("org_check_inbox.html", request)
        finally:
            conn.close()

    @app.get("/org/s/{token}", response_class=HTMLResponse)
    def org_signin(request: Request, token: str):
        conn = get_conn()
        try:
            email = auth.redeem_org_link(conn, token)
            if email is None:
                return render("link_invalid.html", request)
            org = organizers.get_or_create_organizer(conn, email)
            if org["status"] != "active":
                return render("link_invalid.html", request)
            response = RedirectResponse("/org/dashboard", status_code=303)
            response.set_cookie(
                "pli_org",
                auth.sign_org_session(settings.pepper, org["id"]),
                max_age=int(auth.ORG_SESSION_TTL.total_seconds()),
                httponly=True,
                samesite="lax",
                secure=settings.secure_cookies,
            )
            return response
        finally:
            conn.close()

    @app.post("/org/logout")
    def org_logout(request: Request):
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("pli_org")
        return response

    @app.get("/org/dashboard", response_class=HTMLResponse)
    def org_dashboard(request: Request):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            events = organizers.organizer_events(conn, org["id"])
            return render(
                "org_dashboard.html", request,
                org=org, events=events, base_url=settings.base_url,
            )
        finally:
            conn.close()

    @app.get("/org/events/new", response_class=HTMLResponse)
    def org_event_new(request: Request):
        conn = get_conn()
        try:
            if current_organizer(request, conn) is None:
                return RedirectResponse("/org", status_code=303)
            return render(
                "org_event_form.html", request,
                action="/org/events", form=form_values(None, None),
                errors=[], round=None, editing=False,
            )
        finally:
            conn.close()

    @app.post("/org/events", response_class=HTMLResponse)
    async def org_event_create(request: Request):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            form = await read_form(request)
            event_id, errors = organizers.create_event(
                conn, keystore, settings.pepper, org["id"], form
            )
            if errors:
                return render(
                    "org_event_form.html", request,
                    action="/org/events", form=form, errors=errors,
                    round=None, editing=False,
                )
            return RedirectResponse(f"/org/events/{event_id}/edit", status_code=303)
        finally:
            conn.close()

    @app.get("/org/events/{event_id}/edit", response_class=HTMLResponse)
    def org_event_edit(request: Request, event_id: str):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            cohort = owned_event(conn, org, event_id)
            if cohort is None:
                return render("not_found.html", request, status_code=404)
            round_row = organizers.active_round(conn, event_id)
            return render(
                "org_event_form.html", request,
                action=f"/org/events/{event_id}/edit",
                form=form_values(cohort, round_row),
                errors=[], round=round_row, editing=True,
                event_id=event_id, base_url=settings.base_url,
                suspended=bool(cohort["is_suspended"]),
            )
        finally:
            conn.close()

    @app.post("/org/events/{event_id}/edit", response_class=HTMLResponse)
    async def org_event_update(request: Request, event_id: str):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            cohort = owned_event(conn, org, event_id)
            if cohort is None:
                return render("not_found.html", request, status_code=404)
            form = await read_form(request)
            errors = organizers.update_event(conn, keystore, settings.pepper, cohort, form)
            if errors:
                round_row = organizers.active_round(conn, event_id)
                return render(
                    "org_event_form.html", request,
                    action=f"/org/events/{event_id}/edit", form=form,
                    errors=errors, round=round_row, editing=True,
                    event_id=event_id, base_url=settings.base_url,
                    suspended=bool(cohort["is_suspended"]),
                )
            return RedirectResponse("/org/dashboard", status_code=303)
        finally:
            conn.close()

    @app.post("/org/events/{event_id}/cancel")
    def org_event_cancel(request: Request, event_id: str):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            cohort = owned_event(conn, org, event_id)
            if cohort is None:
                return render("not_found.html", request, status_code=404)
            organizers.cancel_event(conn, keystore, event_id)
            return RedirectResponse("/org/dashboard", status_code=303)
        finally:
            conn.close()

    @app.post("/org/events/{event_id}/round", response_class=HTMLResponse)
    async def org_event_new_round(request: Request, event_id: str):
        conn = get_conn()
        try:
            org = current_organizer(request, conn)
            if org is None:
                return RedirectResponse("/org", status_code=303)
            cohort = owned_event(conn, org, event_id)
            if cohort is None:
                return render("not_found.html", request, status_code=404)
            form = await read_form(request)
            errors = organizers.schedule_new_round(conn, keystore, event_id, form)
            if errors:
                return render(
                    "org_event_form.html", request,
                    action=f"/org/events/{event_id}/edit",
                    form=form_values(cohort, None), errors=errors,
                    round=None, editing=True, event_id=event_id,
                    base_url=settings.base_url,
                    suspended=bool(cohort["is_suspended"]),
                )
            return RedirectResponse("/org/dashboard", status_code=303)
        finally:
            conn.close()

    # ---- magic link (global: the round knows its cohort) -----------------

    @app.get("/s/{token}", response_class=HTMLResponse)
    def signin(request: Request, token: str):
        conn = get_conn()
        try:
            parsed = auth.redeem_magic_link(conn, token)
            if parsed is None:
                return render("link_invalid.html", request)
            round_id, h = parsed
            round_row = conn.execute(
                "SELECT * FROM rounds WHERE id = ?", (round_id,)
            ).fetchone()
            if round_row is None or round_row["status"] != "open":
                return render("link_invalid.html", request)
            cookie_name, base_path = cookie_and_home(round_row["cohort_id"])
            response = RedirectResponse(f"{base_path}/declare", status_code=303)
            response.set_cookie(
                cookie_name,
                auth.sign_session(settings.pepper, round_id, h),
                max_age=int(auth.SESSION_TTL.total_seconds()),
                httponly=True,
                samesite="lax",
                secure=settings.secure_cookies,
            )
            return response
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
