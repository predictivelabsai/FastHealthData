"""Center-pane page renderers for FastHealthData."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H3, H4, P, Span, A, Table, Thead, Tbody, Tr, Th, Td, Ul, Li,
    Strong, NotStr, Form, Input, Button, Textarea, Select, Option,
)

import db
from web import charts
from web.layout import kpi_card


def _pill(text, kind=""):
    return Span(text, cls="pill " + (kind or str(text)).lower().replace(" ", "").replace("/", "").replace("-", ""))


def _title(title, sub="", *actions):
    return Div(Div(H1(title), P(sub, cls="sub") if sub else None),
               Div(*actions) if actions else None, cls="page-title")


def _ago(ts):
    return (ts or "")[:16]


# ---------- dashboard -------------------------------------------------------

def dashboard():
    k = db.kpis()
    by_stage = {r["k"]: r["n"] for r in db.counts_by("projects", "stage")}
    max_s = max(by_stage.values(), default=1) or 1
    stage_funnel = [Div(Div(s, style="color:var(--text-dim);"),
                        Div(Div(cls="funnel-bar", style=f"width:{max(2,100*by_stage.get(s,0)/max_s):.0f}%;")),
                        Div(str(by_stage.get(s, 0)), cls="v"), cls="funnel-row")
                    for s in db.PROJECT_STAGES]

    by_std = {r["k"]: r["n"] for r in db.counts_by("datasets", "standard")}
    std_tbl = Table(Thead(Tr(Th("Standard"), Th("Datasets"))),
                    Tbody(*[Tr(Td(_pill(s)), Td(str(by_std.get(s, 0)))) for s in db.STANDARDS]), cls="tbl")

    pending = db.access_requests("Pending")
    req_tbl = Table(
        Thead(Tr(Th("#"), Th("Dataset"), Th("Requester"), Th("Sensitivity"), Th("Purpose"))),
        Tbody(*[Tr(Td(A(f"#{r['id']}", href="/access")), Td(r["dataset"] or "—"),
                   Td(r["requester"] or "—"), Td(_pill(r["sensitivity"] or "")),
                   Td((r["purpose"] or "")[:52], style="color:var(--text-dim);"))
                for r in pending[:8]] or [Tr(Td("No pending access requests 🎉", colspan="5"))]), cls="tbl")

    return (
        _title("Platform Dashboard", "Research projects, catalog, access governance — fully synthetic demo data."),
        Div(Span("🔒 Synthetic demo data only — no real personal or health data (PHI). "
                 "Subjects are pseudonymous synthetic records.", ), cls="callout"),
        Div(kpi_card("Active projects", k["active_projects"], f"{k['total_projects']} total"),
            kpi_card("Catalogued datasets", k["datasets"], f"{k['variables']} variables", tone="teal"),
            kpi_card("Pending access", k["pending_access"], f"{k['approved_access']} approved", tone="warn"),
            kpi_card("Cohort subjects", k["subjects"], "synthetic", tone="ok"),
            cls="kpi-grid"),
        Div(Div(Div(H3("Projects by lifecycle stage"), cls="card-header"), *stage_funnel, cls="card"),
            Div(Div(H3("Catalog — datasets by standard"), cls="card-header"), std_tbl, cls="card"), cls="grid-2"),
        Div(Div(H3("Access requests awaiting decision"),
                A("Open governance →", href="/access", cls="btn sm"), cls="card-header"), req_tbl, cls="card"),
    )


# ---------- projects --------------------------------------------------------

def projects_list(stage="Active"):
    seg = Div(*[A(s, href=f"/projects?stage={s}", cls="" + ("active" if stage == s else ""))
                for s in ["Active", "All", *db.PROJECT_STAGES]], cls="seg")
    projs = db.projects(stage)
    tbl = Table(
        Thead(Tr(Th("Code"), Th("Title"), Th("Stage"), Th("Lead"), Th("Datasets"), Th("Subjects"), Th("Legal basis"))),
        Tbody(*[Tr(
            Td(A(p["code"], href=f"/projects/{p['id']}")),
            Td(A(p["title"], href=f"/projects/{p['id']}")),
            Td(_pill(p["stage"])), Td(p["lead_name"] or "—"),
            Td(str(p["n_datasets"])), Td(f"{p['n_subjects']:,}"),
            Td((p["legal_basis"] or "—").split("(")[0], style="color:var(--text-mute);")
        ) for p in projs] or [Tr(Td("No projects match.", colspan="7"))]), cls="tbl")

    new = Form(
        Div(Input(name="title", placeholder="Project title", required=True, cls="field", style="flex:2;"),
            Input(name="code", placeholder="Code (optional)", cls="field", style="flex:1;"),
            style="display:flex;gap:8px;"),
        Textarea("", name="description", placeholder="Short description / research question…", cls="field", rows="2"),
        Div(Select(*[Option(u["name"], value=str(u["id"])) for u in db.users("Researcher")],
                   name="lead_id", cls="field", style="flex:1;"),
            Select(*[Option(b, value=b) for b in db.LEGAL_BASES], name="legal_basis", cls="field", style="flex:2;"),
            style="display:flex;gap:8px;"),
        Button("Register project", cls="btn primary", type="submit"),
        method="post", action="/projects/new")

    return (_title("Research Projects", f"{len(projs)} shown"), seg,
            Div(Div(H3("Register a new project"), cls="card-header"),
                P("New projects enter the lifecycle at the ", NotStr("<strong>Registered</strong>"),
                  " stage. Move them through Data Intake → Analysis → Outputs → Closed on the project page.",
                  cls="sub", style="margin-bottom:10px;"),
                new, cls="card"),
            Div(Div(H3("Portfolio"), cls="card-header"), tbl, cls="card"))


def _stage_select(pid, current):
    return Select(*[Option(s, value=s, selected=(s == current)) for s in db.PROJECT_STAGES],
                  name="stage", cls="mini-select",
                  **{"hx-post": f"/projects/{pid}/stage", "hx-target": "#project-main",
                     "hx-swap": "innerHTML", "hx-trigger": "change"})


def project_main(pid):
    p = db.project(pid)
    if not p:
        return Div(P("No such project."))
    dss = db.project_datasets(pid)
    ds_tbl = Table(
        Thead(Tr(Th("Dataset"), Th("Standard"), Th("Sensitivity"), Th("Variables"), Th("Subjects"), Th("Steward"))),
        Tbody(*[Tr(Td(A(d["name"], href=f"/catalog/{d['id']}")), Td(_pill(d["standard"])),
                   Td(_pill(d["sensitivity"])), Td(str(d["n_vars"])), Td(f"{d['subject_count']:,}"),
                   Td(d["steward_name"] or "—"))
                for d in dss] or [Tr(Td("No datasets registered yet.", colspan="6"))]), cls="tbl")

    stages_done = db.PROJECT_STAGES.index(p["stage"]) if p["stage"] in db.PROJECT_STAGES else 0
    lifecycle = Ul(*[Li(Div(Strong(s), " ",
                            Span("✓ done" if i < stages_done else ("● current" if i == stages_done else "pending"),
                                 style="color:var(--text-mute);")))
                     for i, s in enumerate(db.PROJECT_STAGES)], cls="timeline")

    info = Div(Div(H3("Project"), _pill(p["stage"]), cls="card-header"),
               Div(Span("Code", cls="k"), Span(p["code"] or "—"),
                   Span("Stage", cls="k"), _stage_select(pid, p["stage"]),
                   Span("Lead", cls="k"), Span(p["lead_name"] or "—"),
                   Span("Legal basis", cls="k"), Span(p["legal_basis"] or "—"),
                   Span("Ethics ref", cls="k"), Span(p["ethics_ref"] or "—"),
                   Span("Registered", cls="k"), Span(_ago(p["created"])),
                   Span("Updated", cls="k"), Span(_ago(p["updated"])),
                   cls="kv"), cls="card")

    return Div(
        Div(Div(Div(H3("Description"), cls="card-header"),
                P(p["description"] or "—"), cls="card"),
            Div(Div(H3(f"Datasets ({len(dss)})"), cls="card-header"), ds_tbl, cls="card")),
        Div(info, Div(Div(H3("Lifecycle"), cls="card-header"), lifecycle, cls="card")),
        cls="detail-grid")


def project_detail(pid):
    p = db.project(pid)
    if not p:
        return _title("Project not found"), P("No such project.")
    return (_title(p["title"], f"{p['code']} · Research project",
                   A("← All projects", href="/projects", cls="btn")),
            Div(project_main(pid), id="project-main"))


# ---------- catalog ---------------------------------------------------------

def catalog_list(standard="All"):
    seg = Div(*[A(s, href=f"/catalog?standard={s}", cls="" + ("active" if standard == s else ""))
                for s in ["All", *db.STANDARDS]], cls="seg")
    dss = [d for d in db.datasets() if standard == "All" or d["standard"] == standard]
    tbl = Table(
        Thead(Tr(Th("Dataset"), Th("Project"), Th("Standard"), Th("Sensitivity"), Th("Variables"),
                 Th("Subjects"), Th("Steward"))),
        Tbody(*[Tr(Td(A(d["name"], href=f"/catalog/{d['id']}")), Td((d["project"] or "—")[:28]),
                   Td(_pill(d["standard"])), Td(_pill(d["sensitivity"])), Td(str(d["n_vars"])),
                   Td(f"{d['subject_count']:,}"), Td(d["steward_name"] or "—"))
                for d in dss] or [Tr(Td("No datasets.", colspan="7"))]), cls="tbl")
    return (_title("Metadata Catalog",
                   f"{len(dss)} datasets · standards: OMOP CDM · HL7 FHIR · openEHR"),
            Div(NotStr("Datasets are catalogued against interoperability standards so variables map to shared "
                       "concepts (OMOP CDM concept ids, HL7 FHIR resource paths, openEHR archetypes). This makes "
                       "cohorts <strong>portable and reusable</strong> across studies."), cls="callout"),
            seg, Div(Div(H3("Datasets"), cls="card-header"), tbl, cls="card"))


def dataset_detail(did):
    d = db.dataset(did)
    if not d:
        return _title("Dataset not found"), P("No such dataset.")
    vs = db.variables_for(did)
    var_tbl = Table(
        Thead(Tr(Th("Variable"), Th("Concept"), Th("Type"), Th("Standard code"), Th("PII"))),
        Tbody(*[Tr(Td(Span(v["name"], cls="mono")), Td(v["concept"] or "—"), Td(v["data_type"] or "—"),
                   Td(Span(v["standard_code"] or "—", cls="mono")),
                   Td(Span("PII", cls="tag") if v["is_pii"] else Span("—", style="color:var(--text-mute);")))
                for v in vs] or [Tr(Td("No variables.", colspan="5"))]), cls="tbl")
    info = Div(Div(H3("Dataset"), _pill(d["standard"]), cls="card-header"),
               Div(Span("Project", cls="k"), Span(d["project"] or "—"),
                   Span("Standard", cls="k"), Span(d["standard"]),
                   Span("Sensitivity", cls="k"), _pill(d["sensitivity"]),
                   Span("Subjects", cls="k"), Span(f"{d['subject_count']:,}"),
                   Span("Variables", cls="k"), Span(str(len(vs))),
                   Span("Steward", cls="k"), Span(d["steward_name"] or "—"),
                   cls="kv"), cls="card")
    return (_title(d["name"], f"Dataset #{d['id']} · {d['standard']}",
                   A("← Catalog", href="/catalog", cls="btn")),
            Div(Div(Div(Div(H3(f"Variables ({len(vs)})"), cls="card-header"), var_tbl, cls="card")),
                Div(info), cls="detail-grid"))


# ---------- access governance -----------------------------------------------

def access_view(status="All"):
    roles_tbl = Table(
        Thead(Tr(Th("Role"), Th("Can"))),
        Tbody(*[Tr(Td(_pill(role)), Td(" · ".join(perms)))
                for role, perms in db.ROLE_PERMISSIONS.items()]), cls="tbl")

    seg = Div(*[A(s, href=f"/access?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["All", *db.ACCESS_STATUSES]], cls="seg")
    reqs = db.access_requests(status)

    def _row(r):
        actions = "—"
        if r["status"] == "Pending":
            actions = Div(
                Form(Button("Approve", cls="btn sm ok", type="submit"),
                     Input(type="hidden", name="decision", value="Approved"),
                     method="post", action=f"/access/{r['id']}/decide", style="display:inline;"),
                Form(Button("Reject", cls="btn sm danger", type="submit"),
                     Input(type="hidden", name="decision", value="Rejected"),
                     method="post", action=f"/access/{r['id']}/decide", style="display:inline;"),
                style="display:flex;gap:6px;")
        else:
            actions = Span(f"by {r['decided_by'] or '—'}", style="color:var(--text-mute);font-size:12px;")
        return Tr(Td(f"#{r['id']}"), Td(r["dataset"] or "—"),
                  Td(Span(r["requester"] or "—"), Div(_pill(r["requester_role"] or ""), style="margin-top:3px;")),
                  Td((r["purpose"] or "")[:60], style="color:var(--text-dim);"),
                  Td(_pill(r["sensitivity"] or "")), Td(_pill(r["status"])), Td(actions))

    req_tbl = Table(
        Thead(Tr(Th("#"), Th("Dataset"), Th("Requester"), Th("Purpose"), Th("Sensitivity"),
                 Th("Status"), Th("Decision"))),
        Tbody(*[_row(r) for r in reqs] or [Tr(Td("No requests.", colspan="7"))]), cls="tbl")

    # new-request form
    dss = db.datasets()
    new = Form(
        Div(Select(*[Option(f"{d['name']} · {d['standard']}", value=str(d["id"])) for d in dss],
                   name="dataset_id", cls="field", style="flex:2;"),
            Select(*[Option(f"{u['name']} ({u['role']})", value=str(u["id"])) for u in db.users("Researcher")],
                   name="requester_id", cls="field", style="flex:1;"),
            style="display:flex;gap:8px;"),
        Textarea("", name="purpose", placeholder="Purpose of processing (required for the audit trail)…",
                 cls="field", rows="2"),
        Button("Submit access request", cls="btn primary", type="submit"),
        method="post", action="/access/new")

    return (_title("Access Governance",
                   "Role-based access control, data-access requests, and approvals — every decision is audited."),
            Div(Div(Div(H3("Roles (RBAC)"), cls="card-header"), roles_tbl, cls="card"),
                Div(Div(H3("Request access to a dataset"), cls="card-header"), new, cls="card"), cls="grid-2"),
            seg, Div(Div(H3("Access request queue"),
                         Span(f"{len(reqs)} shown", style="color:var(--text-mute);font-size:12px;"),
                         cls="card-header"), req_tbl, cls="card"))


# ---------- pseudonymisation -------------------------------------------------

def pseudonymise_view(raw="", result=""):
    ka = db.k_anonymity()
    demo = Form(
        Div(Input(name="raw", value=raw, placeholder="Enter a direct identifier (e.g. national ID, MRN, email)…",
                  cls="field", style="flex:1;margin-bottom:0;"),
            Button("Pseudonymise", cls="btn primary", type="submit"),
            style="display:flex;gap:8px;align-items:center;"),
        method="post", action="/pseudonymise")
    result_block = None
    if result:
        result_block = Div(
            P(NotStr(f"Input <span class='mono'>{raw}</span> → pseudonym <span class='mono'>{result}</span>")),
            P("Deterministic and one-way: the same input always yields the same pseudonym, but the pseudonym "
              "cannot be reversed without the secret salt (held in an HSM/KMS in production, separate from the "
              "research data — GDPR Art. 4(5)).", cls="sub"),
            cls="card", style="border-left:4px solid var(--teal);")

    smallest = Table(
        Thead(Tr(Th("Age band"), Th("Sex"), Th("Region"), Th("Class size"))),
        Tbody(*[Tr(Td(g["age_band"]), Td(g["sex"]), Td(g["region"]),
                   Td(Span(str(g["n"]), style="color:var(--breach);font-weight:600;" if g["n"] < 5 else "")))
                for g in ka["smallest"]]), cls="tbl")

    return (_title("Pseudonymisation & k-anonymity",
                   "Demonstration service — replaces direct identifiers with stable pseudonyms and measures re-identification risk."),
            Div(NotStr("<strong>Demo stub.</strong> This illustrates the concept the platform enforces: identifiers "
                       "never enter the research zone in the clear. Real deployments use a keyed HMAC in a hardware "
                       "security module and keep the re-identification table under separate access control."),
                cls="callout warn"),
            Div(Div(H3("Pseudonymise an identifier"), cls="card-header"), demo, result_block, cls="card"),
            Div(Div(H3("k-anonymity over the synthetic cohort"), cls="card-header"),
                P(NotStr(f"Quasi-identifiers <span class='mono'>(age_band, sex, region)</span> yield "
                         f"<strong>k = {ka['k']}</strong> across {ka['groups']} equivalence classes. "
                         f"<strong>{ka['at_risk']}</strong> subjects fall in classes smaller than 5 "
                         f"(a common release threshold) and would need generalisation or suppression before sharing.")),
                H4("Smallest equivalence classes"), smallest, cls="card"))


# ---------- analytics -------------------------------------------------------

def analytics_view():
    by_cond = db.cohort_by("condition")
    by_age = db.cohort_by("age_band")
    enroll = db.enrollment_by_month()

    # outcomes stacked by condition
    oc = db.cohort_outcomes_by_condition()
    conditions = [r["k"] for r in by_cond]
    outcomes = ["Improved", "Stable", "Deteriorated", "Deceased"]
    series = {o: [0] * len(conditions) for o in outcomes}
    cidx = {c: i for i, c in enumerate(conditions)}
    for r in oc:
        if r["outcome"] in series and r["condition"] in cidx:
            series[r["outcome"]][cidx[r["condition"]]] = r["n"]

    return (_title("Cohort Analytics", "Aggregate views over the synthetic study cohort — no subject-level data leaves the platform."),
            Div(Div(Div(H3("Subjects by condition"), cls="card-header"),
                    charts.bar("chart-condition", [r["k"] for r in by_cond], [r["n"] for r in by_cond]), cls="card"),
                Div(Div(H3("Subjects by age band"), cls="card-header"),
                    charts.bar("chart-age", [r["k"] for r in by_age], [r["n"] for r in by_age],
                               color="#0694a2"), cls="card"), cls="grid-2"),
            Div(Div(Div(H3("Outcomes by condition"), cls="card-header"),
                    charts.grouped_bar("chart-outcomes", conditions, series, height=320), cls="card"),
                Div(Div(H3("Enrolment over time"), cls="card-header"),
                    charts.line("chart-enroll", [r["m"] for r in enroll], [r["n"] for r in enroll], height=320), cls="card"),
                cls="grid-2"))


# ---------- audit -----------------------------------------------------------

def audit_view():
    entries = db.audit()
    tbl = Table(
        Thead(Tr(Th("When"), Th("Actor"), Th("Action"), Th("Entity"))),
        Tbody(*[Tr(Td(_ago(e["created"]), style="color:var(--text-mute);"),
                   Td(Strong(e["actor"] or "—")), Td(NotStr(e["action"])),
                   Td(f"{e['entity']}#{e['entity_id']}" if e["entity_id"] else (e["entity"] or "—"),
                      style="color:var(--text-mute);"))
                for e in entries] or [Tr(Td("No audit entries yet.", colspan="4"))]), cls="tbl")
    return (_title("Audit Log", f"{len(entries)} most recent events — append-only"),
            Div(NotStr("Every governance action (project stage changes, access decisions, requests, "
                       "pseudonymisation-key rotations) is recorded here immutably. Approvals in this demo append "
                       "live entries — try approving a request in Access Governance."), cls="callout"),
            Div(Div(H3("Recent activity"), cls="card-header"), tbl, cls="card"))
