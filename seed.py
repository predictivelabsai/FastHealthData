"""Generate a fully synthetic FastHealthData database (deterministic, no PHI).

Nothing here is real. Subjects are pseudonymous synthetic records; buyer/staff
names are invented; the cohort is randomly generated so the analytics view has
something to draw. Rebuild any time with `python seed.py`.
"""
from __future__ import annotations

import random
from datetime import timedelta

import db
from db import pseudonymise

RNG = random.Random(20260717)
NOW = db.NOW


def _dt(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


USERS = [
    ("Dr. Rasa Petraitytė", "rasa.petraityte@example.org", "Researcher", "Faculty of Medicine"),
    ("Dr. Tomas Jankauskas", "tomas.jankauskas@example.org", "Researcher", "Cardiology Research Unit"),
    ("Prof. Elena Novak", "elena.novak@example.org", "Researcher", "Public Health Institute"),
    ("Marius Vaitkus", "marius.vaitkus@example.org", "Data Steward", "Data Management Office"),
    ("Aistė Kazlauskaitė", "aiste.kazlauskaite@example.org", "Data Steward", "Data Management Office"),
    ("Dr. Hanna Laine", "hanna.laine@example.org", "DPO", "Data Protection Office"),
    ("Sofia Andersson", "sofia.andersson@example.org", "Admin", "IT & Platform"),
]

# (title, code, description, legal_basis_index, stage)
PROJECTS = [
    ("Type 2 Diabetes Outcomes Cohort", "T2D-COH-01",
     "Retrospective cohort linking glycaemic control to cardiovascular outcomes across primary-care records.",
     2, "Analysis"),
    ("Post-COVID Cardiac MRI Registry", "PCMR-02",
     "Prospective imaging registry characterising myocardial changes after SARS-CoV-2 infection.",
     0, "Data Intake"),
    ("Oncology Real-World Evidence — Colorectal", "ORWE-CRC-03",
     "Real-world treatment pathways and survival for stage II–III colorectal cancer.",
     2, "Analysis"),
    ("Maternal & Neonatal Quality Indicators", "MNQI-04",
     "Population-level indicators of maternal and neonatal care quality for benchmarking.",
     1, "Outputs"),
    ("Antimicrobial Resistance Surveillance", "AMR-SURV-05",
     "Linked microbiology and prescribing data to monitor resistance trends.",
     1, "Registered"),
    ("Stroke Rehabilitation Pathways", "STRK-REHAB-06",
     "Functional-recovery trajectories after ischaemic stroke by rehabilitation model.",
     2, "Analysis"),
    ("Paediatric Asthma Digital Biomarkers", "PADB-07",
     "Wearable-derived biomarkers for asthma control in children — feasibility study.",
     0, "Data Intake"),
    ("Chronic Kidney Disease Progression", "CKD-PROG-08",
     "Modelling eGFR decline and dialysis onset from routine laboratory data.",
     2, "Closed"),
]

# Dataset templates per standard; (name, standard, sensitivity)
DATASET_TEMPLATES = [
    ("Primary-care encounters (OMOP)", "OMOP CDM", "Pseudonymised"),
    ("Laboratory results (OMOP measurement)", "OMOP CDM", "Pseudonymised"),
    ("FHIR Observation bundle", "HL7 FHIR", "Pseudonymised"),
    ("FHIR Patient demographics", "HL7 FHIR", "Pseudonymised"),
    ("openEHR clinical notes archetype", "openEHR", "Pseudonymised"),
    ("Imaging metadata index", "Custom", "Anonymised"),
    ("Consent & enrolment register", "Custom", "Identifiable"),
    ("Prescribing extract (OMOP drug_exposure)", "OMOP CDM", "Pseudonymised"),
]

# Variable catalog per standard.
VARIABLES = {
    "OMOP CDM": [
        ("person_id", "Person (pseudonymised)", "integer", "OMOP:1147314", 0),
        ("condition_concept_id", "Condition occurrence", "integer", "OMOP:condition_occurrence", 0),
        ("measurement_value", "Measurement value", "float", "OMOP:measurement.value_as_number", 0),
        ("drug_concept_id", "Drug exposure", "integer", "OMOP:drug_exposure", 0),
        ("year_of_birth", "Year of birth", "integer", "OMOP:person.year_of_birth", 0),
    ],
    "HL7 FHIR": [
        ("Patient.identifier", "Pseudonymised subject id", "categorical", "FHIR:Patient.identifier", 1),
        ("Observation.code", "Observation LOINC code", "categorical", "FHIR:Observation.code", 0),
        ("Observation.valueQuantity", "Observation value", "float", "FHIR:Observation.valueQuantity", 0),
        ("Patient.birthDate", "Birth date", "date", "FHIR:Patient.birthDate", 1),
        ("Condition.code", "Condition (SNOMED CT)", "categorical", "FHIR:Condition.code", 0),
    ],
    "openEHR": [
        ("ehr_id", "EHR identifier", "categorical", "openEHR:EHR.ehr_id", 1),
        ("blood_pressure.systolic", "Systolic BP", "float", "openEHR:OBSERVATION.blood_pressure", 0),
        ("problem_diagnosis", "Problem / diagnosis", "categorical", "openEHR:EVALUATION.problem", 0),
    ],
    "Custom": [
        ("subject_pseudonym", "Subject pseudonym", "categorical", "local:pseudonym", 1),
        ("enrolment_date", "Enrolment date", "date", "local:enrolled_on", 0),
        ("study_arm", "Study arm", "categorical", "local:arm", 0),
        ("region", "Region (coarsened)", "categorical", "local:region", 0),
    ],
}

AGE_BANDS = ["0-17", "18-34", "35-49", "50-64", "65-79", "80+"]
SEXES = ["Female", "Male"]
REGIONS = ["North", "South", "East", "West", "Central"]
CONDITIONS = ["Diabetes", "Hypertension", "CKD", "Stroke", "Cancer", "Asthma", "None"]
OUTCOMES = ["Improved", "Stable", "Deteriorated", "Deceased"]

ACCESS_PURPOSES = [
    "Secondary analysis of glycaemic outcomes for a peer-reviewed publication.",
    "Feature engineering for a risk-prediction model (approved protocol).",
    "Cohort characterisation for a grant application.",
    "Data-quality assessment before analysis stage sign-off.",
    "Cross-linkage feasibility check under the DPO-approved DPIA.",
]


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("chat_messages", "audit_log", "cohort", "access_requests",
                  "variables", "datasets", "projects", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany(
            "INSERT INTO users(name,email,role,org,is_active) VALUES (?,?,?,?,1)", USERS)
        user_rows = conn.execute("SELECT id,name,role FROM users").fetchall()

    researchers = [u["id"] for u in user_rows if u["role"] == "Researcher"]
    stewards = [u["id"] for u in user_rows if u["role"] == "Data Steward"]
    all_ids = [u["id"] for u in user_rows]

    # projects
    proj_ids = []
    for title, code, desc, lb, stage in PROJECTS:
        created = RNG.randint(30, 400)
        pid = None
        with db.cursor() as conn:
            conn.execute(
                """INSERT INTO projects(code,title,description,stage,lead_id,legal_basis,ethics_ref,created,updated)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (code, title, desc, stage, RNG.choice(researchers), db.LEGAL_BASES[lb],
                 f"IRB-2026-{RNG.randint(100,999)}", _dt(created), _dt(RNG.randint(1, created))))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        proj_ids.append(pid)

    # datasets + variables
    dataset_ids = []
    for pid in proj_ids:
        for name, standard, sens in RNG.sample(DATASET_TEMPLATES, RNG.randint(2, 4)):
            subj = RNG.randint(120, 5200)
            with db.cursor() as conn:
                conn.execute(
                    """INSERT INTO datasets(project_id,name,standard,sensitivity,subject_count,steward_id,created)
                       VALUES (?,?,?,?,?,?,?)""",
                    (pid, name, standard, sens, subj, RNG.choice(stewards), _dt(RNG.randint(5, 300))))
                did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                dataset_ids.append(did)
                vs = VARIABLES.get(standard, VARIABLES["Custom"])
                conn.executemany(
                    "INSERT INTO variables(dataset_id,name,concept,data_type,standard_code,is_pii) VALUES (?,?,?,?,?,?)",
                    [(did, n, c, dt, sc, pii) for (n, c, dt, sc, pii) in vs])

    # access requests
    statuses = (["Pending"] * 5) + (["Approved"] * 7) + (["Rejected"] * 2)
    for i in range(14):
        did = RNG.choice(dataset_ids)
        ds = db.dataset(did)
        st = statuses[i]
        decided_by = decided_on = None
        if st != "Pending":
            decider = RNG.choice(["Marius Vaitkus (Data Steward)", "Dr. Hanna Laine (DPO)"])
            decided_by, decided_on = decider, _dt(RNG.randint(1, 40))
        with db.cursor() as conn:
            conn.execute(
                """INSERT INTO access_requests(dataset_id,project_id,requester_id,purpose,status,decided_by,decided_on,created)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (did, ds["project_id"], RNG.choice(researchers), RNG.choice(ACCESS_PURPOSES),
                 st, decided_by, decided_on, _dt(RNG.randint(2, 90))))

    # synthetic cohort (analytics + k-anonymity)
    cohort = []
    n = 900
    for i in range(n):
        pid = RNG.choice(proj_ids)
        # skew a little so charts look real, not uniform
        age = RNG.choices(AGE_BANDS, weights=[6, 14, 18, 24, 22, 16])[0]
        sex = RNG.choice(SEXES)
        region = RNG.choice(REGIONS)
        cond = RNG.choices(CONDITIONS, weights=[18, 20, 10, 8, 9, 12, 23])[0]
        outcome = RNG.choices(OUTCOMES, weights=[38, 34, 20, 8])[0]
        enrolled = _dt(RNG.randint(1, 540))[:10]
        pseud = pseudonymise(f"subject-{pid}-{i:05d}")
        cohort.append((pid, pseud, age, sex, region, cond, enrolled, outcome))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO cohort(project_id,pseudonym,age_band,sex,region,condition,enrolled,outcome) "
            "VALUES (?,?,?,?,?,?,?,?)", cohort)

    # a little audit history
    audit_seed = [
        ("Sofia Andersson", "Platform initialised", "system", None),
        ("Marius Vaitkus", "Curated OMOP measurement dataset", "dataset", dataset_ids[0]),
        ("Dr. Hanna Laine", "Reviewed legal basis for T2D-COH-01", "project", proj_ids[0]),
        ("Aistė Kazlauskaitė", "Rotated pseudonymisation salt (quarterly)", "system", None),
    ]
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO audit_log(actor,action,entity,entity_id,created) VALUES (?,?,?,?,?)",
            [(a, act, e, eid, _dt(RNG.randint(1, 60))) for (a, act, e, eid) in audit_seed])

    print(f"FastHealthData seeded → {db.DB_PATH}")
    print(f"  {len(USERS)} users · {len(proj_ids)} projects · {len(dataset_ids)} datasets · "
          f"14 access requests · {n} synthetic subjects")


if __name__ == "__main__":
    build()
