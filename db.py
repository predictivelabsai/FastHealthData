"""FastHealthData data layer — SQLite.

A health research-data platform: research projects moving through a lifecycle
(register → data intake → analysis → outputs → closed), a metadata catalog of
datasets & variables (tagged with the standard they follow — OMOP CDM / HL7
FHIR / openEHR), access governance (RBAC roles + data-access requests &
approvals), an append-only audit log, a pseudonymisation stub, and a synthetic
cohort used only for the analytics view.

Everything is synthetic demo data — no real personal or health data (PHI).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = os.getenv("FASTHEALTHDATA_DB") or str(Path(__file__).parent / "fasthealthdata.sqlite")

# The fixed "now" so the demo timeline is stable and reproducible.
NOW = datetime(2026, 7, 17, 12, 0, 0)

# --- controlled vocabularies -------------------------------------------------

# Research-project lifecycle stages (Registered … Closed).
PROJECT_STAGES = ["Registered", "Data Intake", "Analysis", "Outputs", "Closed"]
ACTIVE_STAGES = ["Registered", "Data Intake", "Analysis", "Outputs"]

# RBAC roles (mirrors the SDMA governance model).
ROLES = ["Researcher", "Data Steward", "DPO", "Admin"]

# What each role may do — shown on the Access Governance page.
ROLE_PERMISSIONS = {
    "Researcher": ["Register projects", "Browse catalog", "Request dataset access", "Run analytics"],
    "Data Steward": ["Curate datasets & variables", "Approve/deny access requests", "Manage pseudonymisation"],
    "DPO": ["Review legal basis", "Audit access & the log", "Approve identifiable-data requests"],
    "Admin": ["Manage users & roles", "Configure the platform", "Full audit access"],
}

# Data standards the catalog understands (OMOP CDM / HL7 FHIR compatibility).
STANDARDS = ["OMOP CDM", "HL7 FHIR", "openEHR", "Custom"]

# GDPR legal basis for processing (Art. 6 + Art. 9 research condition).
LEGAL_BASES = [
    "Consent (Art. 6(1)(a))",
    "Public task (Art. 6(1)(e))",
    "Scientific research (Art. 9(2)(j))",
    "Legitimate interest (Art. 6(1)(f))",
]

# Disclosure sensitivity of a dataset.
SENSITIVITIES = ["Anonymised", "Pseudonymised", "Identifiable"]

ACCESS_STATUSES = ["Pending", "Approved", "Rejected"]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql, params=()):
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE,
    role        TEXT NOT NULL DEFAULT 'Researcher',
    org         TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY,
    code         TEXT UNIQUE,
    title        TEXT NOT NULL,
    description  TEXT,
    stage        TEXT NOT NULL DEFAULT 'Registered',
    lead_id      INTEGER REFERENCES users(id),
    legal_basis  TEXT,
    ethics_ref   TEXT,
    created      TEXT NOT NULL,
    updated      TEXT
);
CREATE TABLE IF NOT EXISTS datasets (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER REFERENCES projects(id),
    name          TEXT NOT NULL,
    standard      TEXT NOT NULL DEFAULT 'Custom',
    sensitivity   TEXT NOT NULL DEFAULT 'Pseudonymised',
    subject_count INTEGER NOT NULL DEFAULT 0,
    steward_id    INTEGER REFERENCES users(id),
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variables (
    id            INTEGER PRIMARY KEY,
    dataset_id    INTEGER NOT NULL REFERENCES datasets(id),
    name          TEXT NOT NULL,
    concept       TEXT,          -- human label / standard concept
    data_type     TEXT,          -- integer | float | date | categorical | boolean
    standard_code TEXT,          -- e.g. OMOP concept id or FHIR path
    is_pii        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS access_requests (
    id            INTEGER PRIMARY KEY,
    dataset_id    INTEGER NOT NULL REFERENCES datasets(id),
    project_id    INTEGER REFERENCES projects(id),
    requester_id  INTEGER NOT NULL REFERENCES users(id),
    purpose       TEXT,
    status        TEXT NOT NULL DEFAULT 'Pending',
    decided_by    TEXT,
    decided_on    TEXT,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY,
    actor     TEXT,
    action    TEXT NOT NULL,
    entity    TEXT,
    entity_id INTEGER,
    created   TEXT NOT NULL
);
-- Synthetic study cohort — powers the analytics view only. No real people.
CREATE TABLE IF NOT EXISTS cohort (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id),
    pseudonym   TEXT NOT NULL,
    age_band    TEXT,
    sex         TEXT,
    region      TEXT,
    condition   TEXT,
    enrolled    TEXT,
    outcome     TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_datasets_project ON datasets(project_id);
CREATE INDEX IF NOT EXISTS idx_vars_dataset     ON variables(dataset_id);
CREATE INDEX IF NOT EXISTS idx_access_status    ON access_requests(status);
CREATE INDEX IF NOT EXISTS idx_cohort_project   ON cohort(project_id);
"""


def init_schema():
    with cursor() as conn:
        conn.executescript(SCHEMA)


def _ts(dt: datetime | None = None) -> str:
    return (dt or NOW).strftime("%Y-%m-%d %H:%M:%S")


# --- audit -------------------------------------------------------------------

def log(actor: str, action: str, entity: str = "", entity_id: int | None = None):
    with cursor() as conn:
        conn.execute(
            "INSERT INTO audit_log(actor,action,entity,entity_id,created) VALUES (?,?,?,?,?)",
            (actor, action, entity, entity_id, _ts(datetime.now())))


def audit(limit: int = 60):
    return rows("SELECT * FROM audit_log ORDER BY created DESC, id DESC LIMIT ?", (limit,))


# --- aggregate reads ---------------------------------------------------------

def kpis() -> dict:
    active_q = ",".join("?" * len(ACTIVE_STAGES))
    return {
        "active_projects": scalar(f"SELECT COUNT(*) FROM projects WHERE stage IN ({active_q})",
                                  tuple(ACTIVE_STAGES)) or 0,
        "total_projects": scalar("SELECT COUNT(*) FROM projects") or 0,
        "datasets": scalar("SELECT COUNT(*) FROM datasets") or 0,
        "variables": scalar("SELECT COUNT(*) FROM variables") or 0,
        "subjects": scalar("SELECT COUNT(*) FROM cohort") or 0,
        "pending_access": scalar("SELECT COUNT(*) FROM access_requests WHERE status='Pending'") or 0,
        "approved_access": scalar("SELECT COUNT(*) FROM access_requests WHERE status='Approved'") or 0,
        "identifiable": scalar("SELECT COUNT(*) FROM datasets WHERE sensitivity='Identifiable'") or 0,
    }


def counts_by(table: str, col: str) -> list[dict]:
    return rows(f"SELECT {col} k, COUNT(*) n FROM {table} GROUP BY {col}")


# --- projects ----------------------------------------------------------------

def projects(stage: str = "All"):
    where, params = "", ()
    if stage == "Active":
        where = f"WHERE p.stage IN ({','.join('?'*len(ACTIVE_STAGES))})"
        params = tuple(ACTIVE_STAGES)
    elif stage != "All":
        where, params = "WHERE p.stage=?", (stage,)
    return rows(
        f"""SELECT p.*, u.name lead_name,
                   (SELECT COUNT(*) FROM datasets d WHERE d.project_id=p.id) n_datasets,
                   (SELECT COUNT(*) FROM cohort c WHERE c.project_id=p.id) n_subjects
            FROM projects p LEFT JOIN users u ON u.id=p.lead_id
            {where} ORDER BY p.created DESC""", params)


def project(pid: int):
    return one(
        """SELECT p.*, u.name lead_name, u.email lead_email
           FROM projects p LEFT JOIN users u ON u.id=p.lead_id WHERE p.id=?""", (pid,))


def project_datasets(pid: int):
    return rows(
        """SELECT d.*, u.name steward_name,
                  (SELECT COUNT(*) FROM variables v WHERE v.dataset_id=d.id) n_vars
           FROM datasets d LEFT JOIN users u ON u.id=d.steward_id
           WHERE d.project_id=? ORDER BY d.name""", (pid,))


def set_project_stage(pid: int, stage: str, actor: str = "admin") -> bool:
    if stage not in PROJECT_STAGES:
        return False
    with cursor() as conn:
        conn.execute("UPDATE projects SET stage=?, updated=? WHERE id=?", (stage, _ts(datetime.now()), pid))
    log(actor, f"Project stage → {stage}", "project", pid)
    return True


def create_project(title, code, description, lead_id, legal_basis, actor="admin") -> int | None:
    title = (title or "").strip()
    if not title:
        return None
    with cursor() as conn:
        conn.execute(
            """INSERT INTO projects(code,title,description,stage,lead_id,legal_basis,created,updated)
               VALUES (?,?,?,?,?,?,?,?)""",
            ((code or "").strip() or f"PRJ-{int(datetime.now().timestamp())%100000}",
             title, (description or "").strip(),
             "Registered", int(lead_id) if lead_id else None,
             legal_basis if legal_basis in LEGAL_BASES else LEGAL_BASES[2],
             _ts(datetime.now()), _ts(datetime.now())))
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log(actor, f"Registered project “{title}”", "project", pid)
    return pid


# --- catalog -----------------------------------------------------------------

def datasets():
    return rows(
        """SELECT d.*, p.title project, u.name steward_name,
                  (SELECT COUNT(*) FROM variables v WHERE v.dataset_id=d.id) n_vars
           FROM datasets d LEFT JOIN projects p ON p.id=d.project_id
           LEFT JOIN users u ON u.id=d.steward_id ORDER BY d.name""")


def dataset(did: int):
    return one(
        """SELECT d.*, p.title project, u.name steward_name
           FROM datasets d LEFT JOIN projects p ON p.id=d.project_id
           LEFT JOIN users u ON u.id=d.steward_id WHERE d.id=?""", (did,))


def variables_for(did: int):
    return rows("SELECT * FROM variables WHERE dataset_id=? ORDER BY is_pii DESC, name", (did,))


def create_dataset(project_id, name, standard, sensitivity, subject_count,
                   steward_id=None, actor="admin") -> int:
    with cursor() as conn:
        conn.execute(
            """INSERT INTO datasets(project_id,name,standard,sensitivity,subject_count,steward_id,created)
               VALUES (?,?,?,?,?,?,?)""",
            (project_id, name, standard, sensitivity, subject_count, steward_id,
             _ts(datetime.now())),
        )
        dataset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log(actor, f"Registered dataset “{name}”", "dataset", dataset_id)
    return dataset_id


def update_dataset(dataset_id, *, standard, sensitivity, subject_count,
                   steward_id=None, actor="admin") -> bool:
    with cursor() as conn:
        changed = conn.execute(
            """UPDATE datasets
               SET standard=?, sensitivity=?, subject_count=?, steward_id=?
               WHERE id=?""",
            (standard, sensitivity, subject_count, steward_id, dataset_id),
        ).rowcount
    if changed:
        log(actor, "Updated dataset governance metadata", "dataset", dataset_id)
    return bool(changed)


def create_variable(dataset_id, name, concept, data_type, standard_code,
                    is_pii=False, actor="admin") -> int:
    with cursor() as conn:
        conn.execute(
            """INSERT INTO variables(dataset_id,name,concept,data_type,standard_code,is_pii)
               VALUES (?,?,?,?,?,?)""",
            (dataset_id, name, concept, data_type, standard_code, int(bool(is_pii))),
        )
        variable_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log(actor, f"Catalogued variable “{name}”", "variable", variable_id)
    return variable_id


# --- access governance -------------------------------------------------------

def access_requests(status: str = "All"):
    where, params = "", ()
    if status != "All":
        where, params = "WHERE ar.status=?", (status,)
    return rows(
        f"""SELECT ar.*, d.name dataset, d.sensitivity, p.title project, u.name requester, u.role requester_role
            FROM access_requests ar
            LEFT JOIN datasets d ON d.id=ar.dataset_id
            LEFT JOIN projects p ON p.id=ar.project_id
            LEFT JOIN users u ON u.id=ar.requester_id
            {where} ORDER BY (ar.status='Pending') DESC, ar.created DESC""", params)


def decide_access(rid: int, decision: str, actor: str = "admin") -> bool:
    if decision not in ("Approved", "Rejected"):
        return False
    with cursor() as conn:
        conn.execute("UPDATE access_requests SET status=?, decided_by=?, decided_on=? WHERE id=?",
                     (decision, actor, _ts(datetime.now()), rid))
    log(actor, f"Access request #{rid} {decision.lower()}", "access_request", rid)
    return True


def create_access_request(dataset_id, requester_id, purpose, actor="admin") -> int | None:
    ds = dataset(int(dataset_id)) if dataset_id else None
    if not ds:
        return None
    with cursor() as conn:
        conn.execute(
            """INSERT INTO access_requests(dataset_id,project_id,requester_id,purpose,status,created)
               VALUES (?,?,?,?,?,?)""",
            (ds["id"], ds["project_id"], int(requester_id), (purpose or "").strip() or "(no purpose stated)",
             "Pending", _ts(datetime.now())))
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log(actor, f"Requested access to “{ds['name']}”", "access_request", rid)
    return rid


def users(role: str = None):
    if role:
        return rows("SELECT * FROM users WHERE role=? AND is_active=1 ORDER BY name", (role,))
    return rows("SELECT * FROM users WHERE is_active=1 ORDER BY role, name")


# --- pseudonymisation stub ---------------------------------------------------

PSEUDO_SALT = os.getenv("FASTHEALTHDATA_PSEUDO_SALT", "fasthealthdata-demo-salt")


def pseudonymise(raw: str) -> str:
    """Deterministic, one-way pseudonym for a direct identifier.

    Demo only: a salted SHA-256 digest rendered as PSN-XXXXXXXXXX. In production
    the salt/key lives in an HSM or KMS, is access-controlled, and the mapping
    table is held separately from the research data (GDPR Art. 4(5)).
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    digest = hashlib.sha256((PSEUDO_SALT + "|" + raw.lower()).encode()).hexdigest()
    return "PSN-" + digest[:10].upper()


def k_anonymity(quasi_identifiers=("age_band", "sex", "region")) -> dict:
    """Smallest equivalence-class size (k) over the synthetic cohort for the
    given quasi-identifiers — the standard k-anonymity measure."""
    cols = ", ".join(quasi_identifiers)
    groups = rows(f"SELECT {cols}, COUNT(*) n FROM cohort GROUP BY {cols} ORDER BY n ASC")
    if not groups:
        return {"k": 0, "groups": 0, "at_risk": 0, "smallest": []}
    k = groups[0]["n"]
    at_risk = sum(g["n"] for g in groups if g["n"] < 5)
    return {"k": k, "groups": len(groups), "at_risk": at_risk, "smallest": groups[:6]}


# --- analytics (synthetic cohort) -------------------------------------------

def cohort_by(col: str):
    return rows(f"SELECT {col} k, COUNT(*) n FROM cohort GROUP BY {col} ORDER BY {col}")


def cohort_outcomes_by_condition():
    return rows(
        """SELECT condition, outcome, COUNT(*) n FROM cohort
           GROUP BY condition, outcome ORDER BY condition, outcome""")


def enrollment_by_month():
    return rows(
        """SELECT substr(enrolled,1,7) m, COUNT(*) n FROM cohort
           GROUP BY m ORDER BY m""")
