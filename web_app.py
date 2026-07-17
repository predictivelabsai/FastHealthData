"""FastHealthData — an open-source health research-data platform built with FastHTML.

A server-side, HTMX-driven platform to manage health research projects and their
data across the lifecycle: project registration → data intake → analysis →
outputs, a metadata catalog (OMOP CDM / HL7 FHIR / openEHR), access governance
(RBAC + data-access requests & approvals + audit), a pseudonymisation stub, and
cohort analytics — with an AI assistant grounded in the (synthetic) platform data.

Everything runs on synthetic data only — no real personal or health data (PHI).

Run:
    python web_app.py            # http://localhost:5013

Login: admin@fasthealthdata.example / FastHealthData2026$  (override via .env)
"""
from __future__ import annotations

import os
import json
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, Form, Input, Button, NotStr,
    RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fasthealthdata")

VALID_EMAIL = os.getenv("FASTHEALTHDATA_ADMIN_EMAIL", "admin@fasthealthdata.example")
VALID_PASSWORD = os.getenv("FASTHEALTHDATA_ADMIN_PASSWORD", "FastHealthData2026$")
ENV_LABEL = os.getenv("FASTHEALTHDATA_ENV_LABEL", "FastHealthData")
SECRET = os.getenv("FASTHEALTHDATA_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTHEALTHDATA_PORT", "5013"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


def _user(session):
    return session.get("user")


def _thread(session):
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _login_card(error="", email=""):
    return Title("FastHealthData — Sign in"), Style(LAYOUT_CSS), Div(
        Form(H1("FastHealthData"), P("Sign in to the health research-data platform"),
             Input(name="email", type="email", placeholder="Email", value=email, required=True),
             Input(name="password", type="password", placeholder="Password", required=True),
             P(error, cls="error") if error else None,
             Button("Sign in", cls="btn primary", type="submit"),
             P(NotStr("Demo: <code>admin@fasthealthdata.example</code> / <code>FastHealthData2026$</code>"), cls="hint"),
             method="post", action="/login", cls="login-card"), cls="login-wrap")


@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


# --- overview ---------------------------------------------------------------

@rt("/")
def get(session):
    return _guard(session, "dashboard", views.dashboard)


# --- projects ---------------------------------------------------------------

@rt("/projects")
def get(session, stage: str = "Active"):
    return _guard(session, "projects", lambda: views.projects_list(stage))


@rt("/projects/new")
def post(session, title: str = "", code: str = "", description: str = "",
         lead_id: str = "", legal_basis: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_project(title, code, description, lead_id or None, legal_basis, actor=_user(session))
    return RedirectResponse("/projects", status_code=303)


@rt("/projects/{pid}")
def get(session, pid: int):
    return _guard(session, "projects", lambda: views.project_detail(pid))


@rt("/projects/{pid}/stage")
def post(session, pid: int, stage: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.set_project_stage(pid, stage, actor=_user(session))
    return views.project_main(pid)


# --- catalog ----------------------------------------------------------------

@rt("/catalog")
def get(session, standard: str = "All"):
    return _guard(session, "catalog", lambda: views.catalog_list(standard))


@rt("/catalog/{did}")
def get(session, did: int):
    return _guard(session, "catalog", lambda: views.dataset_detail(did))


# --- access governance ------------------------------------------------------

@rt("/access")
def get(session, status: str = "All"):
    return _guard(session, "access", lambda: views.access_view(status))


@rt("/access/new")
def post(session, dataset_id: str = "", requester_id: str = "", purpose: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_access_request(dataset_id, requester_id, purpose, actor=_user(session))
    return RedirectResponse("/access", status_code=303)


@rt("/access/{rid}/decide")
def post(session, rid: int, decision: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.decide_access(rid, decision, actor=_user(session))
    return RedirectResponse("/access", status_code=303)


# --- pseudonymisation -------------------------------------------------------

@rt("/pseudonymise")
def get(session):
    return _guard(session, "pseudonymise", views.pseudonymise_view)


@rt("/pseudonymise")
def post(session, raw: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    result = db.pseudonymise(raw)
    return _guard(session, "pseudonymise", lambda: views.pseudonymise_view(raw, result))


# --- analytics & audit ------------------------------------------------------

@rt("/analytics")
def get(session):
    return _guard(session, "analytics", views.analytics_view)


@rt("/audit")
def get(session):
    return _guard(session, "audit", views.audit_view)


# --- AI landing + guide -----------------------------------------------------

@rt("/ai")
def get(session):
    body = (views._title("AI Assistant", "Chat lives in the right rail. Ask in plain English or use slash-commands."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3><ul style='line-height:1.8;'>"
                "<li>“How many access requests are pending?”</li>"
                "<li>“How many subjects per condition?”</li>"
                "<li>“Which datasets follow the OMOP CDM standard?”</li>"
                "<li>“Summarise the project portfolio.”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands resolve instantly with no API key: "
                "<code>/projects</code> <code>/catalog</code> <code>/access</code> "
                "<code>/cohort</code> <code>/kanon</code> <code>/kpi</code> <code>/help</code></p></div>")))
    return _guard(session, "ai", body)


@rt("/guide")
def get(session):
    body = (views._title("User Guide", "How to drive FastHealthData"), Div(NotStr("""
<div class='card'><h3>Dashboard</h3><p>Portfolio KPIs (active projects, catalogued datasets, pending access,
cohort subjects), projects by lifecycle stage, datasets by standard, and the access-request worklist.</p></div>
<div class='card'><h3>Projects</h3><p>Register a research project and move it through the lifecycle —
<em>Registered → Data Intake → Analysis → Outputs → Closed</em>. Each project lists its datasets, legal basis
and ethics reference.</p></div>
<div class='card'><h3>Metadata Catalog</h3><p>Datasets tagged with the interoperability standard they follow
(OMOP CDM, HL7 FHIR, openEHR). Open a dataset to see its variables, concept codes, and which fields are PII.</p></div>
<div class='card'><h3>Access Governance</h3><p>RBAC roles (Researcher / Data Steward / DPO / Admin),
data-access requests with a purpose, and approve/deny decisions — all written to the audit log.</p></div>
<div class='card'><h3>Pseudonymisation</h3><p>A demo stub that turns a direct identifier into a stable, one-way
pseudonym, plus a live k-anonymity measure over the synthetic cohort.</p></div>
<div class='card'><h3>Analytics</h3><p>Aggregate Plotly charts over the synthetic cohort — by condition, age band,
outcome and enrolment. No subject-level data leaves the platform.</p></div>
<div class='card'><h3>AI Assistant</h3><p>The right rail chats over a live snapshot of the platform.
Set <code>MODEL_PROVIDER</code> + an API key in <code>.env</code> for free-form chat; slash-commands always work.</p></div>
""")))
    return _guard(session, "guide", body)


# --- chat -------------------------------------------------------------------

@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about projects, datasets, access requests or the synthetic cohort — or tap a question below.",
             cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)
    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            if chunk.startswith("data: "):
                try:
                    tok = json.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()
    else:
        db.init_schema()  # idempotent


_ensure_db()

if __name__ == "__main__":
    logger.info("FastHealthData on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTHEALTHDATA_RELOAD", "0") == "1")
