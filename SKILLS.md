# Skills

Capability reference for FastHealthData — an open-source health research-data
platform in the FastGov suite. Built on the shared FastHTML app shell (see
`FastHelpdesk/SKILLS.md` for the migration playbook this reuses).

---

## Capabilities

**Entry:** `python web_app.py` → http://localhost:5013
(login `admin@fasthealthdata.example` / `FastHealthData2026$`).

3-pane FastHTML layout: left nav · center work area · right AI rail.

### Pages

| View | Route | What it shows |
|---|---|---|
| Dashboard | `/` | KPIs (active projects, datasets, pending access, subjects), projects by stage, datasets by standard, pending-access worklist |
| Projects | `/projects?stage=` | Portfolio + register form; lifecycle Registered→Data Intake→Analysis→Outputs→Closed |
| Project | `/projects/{id}` | Description, datasets, legal basis, ethics ref, lifecycle stepper, stage changer |
| Metadata Catalog | `/catalog?standard=` | Datasets tagged OMOP CDM / HL7 FHIR / openEHR / Custom |
| Dataset | `/catalog/{id}` | Variables with concept codes, data types, PII flags |
| Access Governance | `/access?status=` | RBAC matrix, request form, approve/deny queue |
| Pseudonymisation | `/pseudonymise` | Identifier → pseudonym stub + live k-anonymity |
| Analytics | `/analytics` | Plotly charts over the synthetic cohort |
| Audit Log | `/audit` | Append-only governance events |
| AI Assistant | `/ai` | Landing; chat is the right rail |

### Data model (`db.py`)

`users · projects · datasets · variables · access_requests · audit_log ·
cohort · chat_messages`. Controlled vocabularies: `PROJECT_STAGES`, `ROLES`,
`ROLE_PERMISSIONS`, `STANDARDS`, `LEGAL_BASES`, `SENSITIVITIES`,
`ACCESS_STATUSES`. Rebuild with `python seed.py` (deterministic, no PHI).

### Governance primitives

- **`pseudonymise(raw)`** — deterministic, one-way salted SHA-256 pseudonym
  (`PSN-XXXXXXXXXX`). Demo stub; production uses an HSM/KMS-held HMAC key.
- **`k_anonymity(quasi_identifiers)`** — smallest equivalence-class size `k`
  over the cohort, plus how many subjects sit in classes < 5.
- **`log(actor, action, entity, id)`** — append-only audit; access decisions and
  stage changes call it live.

### AI assistant (`web/ai.py`)

- **Slash-commands** (no API key): `/projects [stage]` `/catalog [standard]`
  `/access [status]` `/cohort [condition|age|sex|region]` `/kanon` `/kpi` `/help`.
- **Free-form chat** streams from `MODEL_PROVIDER` (xai|openai|anthropic|google),
  grounded with a live `snapshot()` (portfolio, catalog, access queue, cohort,
  k-anonymity) so answers reflect the actual synthetic data and never invent
  subject-level records.

### Charts (`web/charts.py`)

Server emits a Plotly JSON spec; the browser renders it (Plotly.js from CDN in
`layout.py`). `bar` / `line` / `donut` / `grouped_bar` — no server plotting dep.

---

## FastGov positioning

FastHealthData is the health-research node of the FastGov suite. It reuses the
FastHTML shell, the key-optional multi-provider AI assistant, and the synthetic
self-seeding pattern shared across FastHelpdesk / FastCRM / FastInsights, and
adds the domain primitives a research-data platform needs: project lifecycle,
a standards-aware metadata catalog, RBAC access governance with audit, and
pseudonymisation / k-anonymity. It is also the live demonstrator for the
Lithuanian SDMA IS tender.
