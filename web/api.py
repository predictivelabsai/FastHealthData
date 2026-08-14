"""Typed integration API for FastHealthData's synthetic research-data model."""
from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

import db


API_VERSION = "1.0.0"
PUBLIC_BASE_URL = os.getenv("FASTSME_PUBLIC_URL", "https://healthdata.fastsme.com").rstrip("/")
API_ACTOR = os.getenv("FASTHEALTHDATA_API_ACTOR", "integration-api")
COHORT_DIMENSIONS = frozenset({"condition", "age_band", "sex", "region", "outcome", "project_id"})
QUASI_IDENTIFIERS = frozenset({"age_band", "sex", "region", "condition", "outcome"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class Meta(BaseModel):
    total: int
    limit: int
    offset: int


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    product: str
    version: str
    database_ready: bool
    writes_enabled: bool
    synthetic_only: bool = True


class Project(BaseModel):
    id: int
    code: str | None = None
    title: str
    description: str | None = None
    stage: str
    lead_id: int | None = None
    legal_basis: str | None = None
    ethics_ref: str | None = None
    created: str
    updated: str | None = None
    lead_name: str | None = None
    lead_email: str | None = None
    n_datasets: int | None = None
    n_subjects: int | None = None


class ProjectCollection(BaseModel):
    data: list[Project]
    meta: Meta


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    code: str | None = Field(default=None, max_length=80)
    description: str = Field(default="", max_length=5000)
    lead_id: int | None = Field(default=None, gt=0)
    legal_basis: str = Field(default=db.LEGAL_BASES[2])


class ProjectStageUpdate(StrictModel):
    stage: Literal["Registered", "Data Intake", "Analysis", "Outputs", "Closed"]


class Dataset(BaseModel):
    id: int
    project_id: int | None = None
    name: str
    standard: str
    sensitivity: str
    subject_count: int
    steward_id: int | None = None
    created: str
    project: str | None = None
    steward_name: str | None = None
    n_vars: int | None = None


class DatasetCollection(BaseModel):
    data: list[Dataset]
    meta: Meta


class DatasetCreate(StrictModel):
    project_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=240)
    standard: Literal["OMOP CDM", "HL7 FHIR", "openEHR", "Custom"] = "Custom"
    sensitivity: Literal["Anonymised", "Pseudonymised", "Identifiable"] = "Pseudonymised"
    subject_count: int = Field(default=0, ge=0)
    steward_id: int | None = Field(default=None, gt=0)


class DatasetUpdate(StrictModel):
    standard: Literal["OMOP CDM", "HL7 FHIR", "openEHR", "Custom"]
    sensitivity: Literal["Anonymised", "Pseudonymised", "Identifiable"]
    subject_count: int = Field(ge=0)
    steward_id: int | None = Field(default=None, gt=0)


class Variable(BaseModel):
    id: int
    dataset_id: int
    name: str
    concept: str | None = None
    data_type: str | None = None
    standard_code: str | None = None
    is_pii: int


class VariableCollection(BaseModel):
    data: list[Variable]
    meta: Meta


class VariableCreate(StrictModel):
    name: str = Field(min_length=1, max_length=240)
    concept: str | None = Field(default=None, max_length=500)
    data_type: Literal["integer", "float", "date", "categorical", "boolean", "text"]
    standard_code: str | None = Field(default=None, max_length=500)
    is_pii: bool = False


class DatasetDetail(BaseModel):
    dataset: Dataset
    variables: list[Variable]


class AccessRequest(BaseModel):
    id: int
    dataset_id: int
    project_id: int | None = None
    requester_id: int
    purpose: str | None = None
    status: str
    decided_by: str | None = None
    decided_on: str | None = None
    created: str
    dataset: str | None = None
    sensitivity: str | None = None
    project: str | None = None
    requester: str | None = None
    requester_role: str | None = None


class AccessCollection(BaseModel):
    data: list[AccessRequest]
    meta: Meta


class AccessCreate(StrictModel):
    dataset_id: int = Field(gt=0)
    requester_id: int = Field(gt=0)
    purpose: str = Field(min_length=10, max_length=5000)


class AccessDecision(StrictModel):
    decision: Literal["Approved", "Rejected"]


class AuditEvent(BaseModel):
    id: int
    actor: str | None = None
    action: str
    entity: str | None = None
    entity_id: int | None = None
    created: str


class AuditCollection(BaseModel):
    data: list[AuditEvent]
    meta: Meta


class User(BaseModel):
    id: int
    name: str
    email: str | None = None
    role: str
    org: str | None = None
    is_active: int


class UserCollection(BaseModel):
    data: list[User]
    meta: Meta


class Breakdown(BaseModel):
    key: str | int | None
    count: int


class BreakdownResponse(BaseModel):
    dimension: str
    data: list[Breakdown]
    total: int


class OutcomeBreakdown(BaseModel):
    condition: str
    outcome: str
    count: int


class EnrollmentPoint(BaseModel):
    month: str
    count: int


class KAnonymityResponse(BaseModel):
    quasi_identifiers: list[str]
    k: int
    groups: int
    at_risk: int
    threshold: int = 5
    release_ready: bool
    smallest: list[dict[str, Any]]
    warning: str


class PseudonymiseRequest(StrictModel):
    identifier: str = Field(min_length=1, max_length=500)


class PseudonymiseResponse(BaseModel):
    pseudonym: str
    algorithm: str = "demo-salted-sha256"
    production_ready: bool = False
    warning: str


bearer = HTTPBearer(auto_error=False, scheme_name="FastHealthData API token")


def _configured_token() -> str:
    return os.getenv("FASTHEALTHDATA_API_TOKEN") or os.getenv("FASTSME_API_TOKEN") or ""


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
) -> None:
    configured = _configured_token()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "protected_api_disabled",
                "message": "Protected API operations are disabled until an API token is configured.",
                "details": {},
            },
        )
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(configured, supplied):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "invalid_token",
                "message": "A valid bearer token is required.",
                "details": {},
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def problem(status_code: int, code: str, message: str, **details):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details},
    )


def paginate(items: list[dict], limit: int, offset: int) -> tuple[list[dict], Meta]:
    return items[offset : offset + limit], Meta(total=len(items), limit=limit, offset=offset)


api = FastAPI(
    title="FastHealthData API",
    version=API_VERSION,
    description=(
        "Typed access to FastHealthData's synthetic research-project lifecycle, "
        "standards-aware metadata catalog, governed access workflow, disclosure "
        "signals, aggregate analytics, and append-only audit evidence.\n\n"
        "**Synthetic data only.** Public endpoints expose only synthetic catalog "
        "and aggregate data. Governance records and every mutation require a bearer token."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    servers=[{"url": f"{PUBLIC_BASE_URL}/api", "description": "Production"}],
    contact={"name": "FastSME", "url": "https://fastsme.com"},
    license_info={"name": "MIT"},
)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "HEAD", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)


@api.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {
        "code": "http_error", "message": str(exc.detail), "details": {}
    }
    return JSONResponse(status_code=exc.status_code, content={"error": detail}, headers=exc.headers)


@api.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "The request did not match the API schema.",
                "details": {"errors": jsonable_encoder(exc.errors())},
            }
        },
    )


@api.get("/", tags=["System"])
def index() -> dict[str, str]:
    return {
        "name": "FastHealthData API",
        "version": API_VERSION,
        "documentation": f"{PUBLIC_BASE_URL}/developers",
        "swagger": f"{PUBLIC_BASE_URL}/api/docs",
        "openapi": f"{PUBLIC_BASE_URL}/api/openapi.json",
    }


@api.get("/v1/health", response_model=Health, tags=["System"])
def health() -> Health:
    try:
        ready = db.scalar("SELECT 1") == 1
    except Exception:
        ready = False
    return Health(
        status="ok" if ready else "degraded",
        product="FastHealthData",
        version=API_VERSION,
        database_ready=ready,
        writes_enabled=bool(_configured_token()),
    )


@api.get("/v1/summary", tags=["Portfolio"])
def summary() -> dict[str, Any]:
    result = db.kpis()
    result["by_stage"] = [{"key": row["k"], "count": row["n"]} for row in db.counts_by("projects", "stage")]
    result["by_standard"] = [{"key": row["k"], "count": row["n"]} for row in db.counts_by("datasets", "standard")]
    return result


@api.get("/v1/projects", response_model=ProjectCollection, tags=["Projects"])
def list_projects(
    stage: str = Query(default="All"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectCollection:
    if stage not in ["All", "Active", *db.PROJECT_STAGES]:
        problem(422, "invalid_stage", "Unknown project stage.", allowed=["All", "Active", *db.PROJECT_STAGES])
    items = db.projects(stage)
    if q:
        needle = q.casefold()
        items = [row for row in items if needle in f"{row.get('code','')} {row.get('title','')} {row.get('description','')}".casefold()]
    page, meta = paginate(items, limit, offset)
    return ProjectCollection(data=page, meta=meta)


@api.post(
    "/v1/projects", response_model=Project, status_code=201,
    dependencies=[Depends(require_token)], tags=["Projects"],
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}},
)
def create_project(payload: ProjectCreate) -> Project:
    if payload.legal_basis not in db.LEGAL_BASES:
        problem(422, "invalid_legal_basis", "Unknown legal basis.", allowed=db.LEGAL_BASES)
    if payload.lead_id is not None and not db.one("SELECT id FROM users WHERE id=? AND is_active=1", (payload.lead_id,)):
        problem(404, "lead_not_found", "The requested project lead was not found.", id=payload.lead_id)
    try:
        project_id = db.create_project(
            payload.title, payload.code, payload.description, payload.lead_id,
            payload.legal_basis, actor=API_ACTOR,
        )
    except sqlite3.IntegrityError as exc:
        problem(409, "project_conflict", "A project with this code already exists.")
    created = db.project(int(project_id)) if project_id else None
    if not created:
        problem(422, "invalid_project", "The project could not be registered.")
    return Project(**created)


@api.get("/v1/projects/{project_id}", response_model=Project, tags=["Projects"])
def get_project(project_id: int) -> Project:
    item = db.project(project_id)
    if not item:
        problem(404, "not_found", "Project not found.", id=project_id)
    return Project(**item)


@api.patch(
    "/v1/projects/{project_id}/stage", response_model=Project,
    dependencies=[Depends(require_token)], tags=["Projects"],
)
def update_project_stage(project_id: int, payload: ProjectStageUpdate) -> Project:
    if not db.project(project_id):
        problem(404, "not_found", "Project not found.", id=project_id)
    if not db.set_project_stage(project_id, payload.stage, actor=API_ACTOR):
        problem(422, "invalid_stage", "The project stage was not changed.")
    return Project(**db.project(project_id))


@api.get("/v1/projects/{project_id}/datasets", response_model=DatasetCollection, tags=["Projects", "Catalog"])
def list_project_datasets(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetCollection:
    if not db.project(project_id):
        problem(404, "not_found", "Project not found.", id=project_id)
    items = db.project_datasets(project_id)
    page, meta = paginate(items, limit, offset)
    return DatasetCollection(data=page, meta=meta)


@api.get("/v1/datasets", response_model=DatasetCollection, tags=["Catalog"])
def list_datasets(
    standard: str = Query(default="All"),
    sensitivity: str = Query(default="All"),
    project_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetCollection:
    if standard not in ["All", *db.STANDARDS]:
        problem(422, "invalid_standard", "Unknown catalog standard.", allowed=["All", *db.STANDARDS])
    if sensitivity not in ["All", *db.SENSITIVITIES]:
        problem(422, "invalid_sensitivity", "Unknown sensitivity.", allowed=["All", *db.SENSITIVITIES])
    items = db.datasets()
    if standard != "All":
        items = [row for row in items if row["standard"] == standard]
    if sensitivity != "All":
        items = [row for row in items if row["sensitivity"] == sensitivity]
    if project_id is not None:
        items = [row for row in items if row["project_id"] == project_id]
    if q:
        needle = q.casefold()
        items = [row for row in items if needle in f"{row.get('name','')} {row.get('project','')}".casefold()]
    page, meta = paginate(items, limit, offset)
    return DatasetCollection(data=page, meta=meta)


@api.get("/v1/datasets/{dataset_id}", response_model=DatasetDetail, tags=["Catalog"])
def get_dataset(dataset_id: int) -> DatasetDetail:
    item = db.dataset(dataset_id)
    if not item:
        problem(404, "not_found", "Dataset not found.", id=dataset_id)
    variables = db.variables_for(dataset_id)
    return DatasetDetail(dataset=Dataset(**item), variables=[Variable(**row) for row in variables])


@api.post(
    "/v1/datasets", response_model=DatasetDetail, status_code=201,
    dependencies=[Depends(require_token)], tags=["Catalog"],
)
def create_dataset(payload: DatasetCreate) -> DatasetDetail:
    if not db.project(payload.project_id):
        problem(404, "project_not_found", "Project not found.", id=payload.project_id)
    if payload.steward_id is not None:
        steward = db.one(
            "SELECT id FROM users WHERE id=? AND role IN ('Data Steward','Admin') AND is_active=1",
            (payload.steward_id,),
        )
        if not steward:
            problem(404, "steward_not_found", "An active Data Steward or Admin was not found.", id=payload.steward_id)
    duplicate = db.one(
        "SELECT id FROM datasets WHERE project_id=? AND lower(name)=lower(?)",
        (payload.project_id, payload.name.strip()),
    )
    if duplicate:
        problem(409, "dataset_conflict", "This project already has a dataset with that name.", id=duplicate["id"])
    dataset_id = db.create_dataset(
        payload.project_id, payload.name.strip(), payload.standard,
        payload.sensitivity, payload.subject_count, payload.steward_id,
        actor=API_ACTOR,
    )
    return get_dataset(dataset_id)


@api.patch(
    "/v1/datasets/{dataset_id}", response_model=DatasetDetail,
    dependencies=[Depends(require_token)], tags=["Catalog"],
)
def update_dataset(dataset_id: int, payload: DatasetUpdate) -> DatasetDetail:
    if not db.dataset(dataset_id):
        problem(404, "not_found", "Dataset not found.", id=dataset_id)
    if payload.steward_id is not None:
        steward = db.one(
            "SELECT id FROM users WHERE id=? AND role IN ('Data Steward','Admin') AND is_active=1",
            (payload.steward_id,),
        )
        if not steward:
            problem(404, "steward_not_found", "An active Data Steward or Admin was not found.", id=payload.steward_id)
    db.update_dataset(
        dataset_id, standard=payload.standard, sensitivity=payload.sensitivity,
        subject_count=payload.subject_count, steward_id=payload.steward_id,
        actor=API_ACTOR,
    )
    return get_dataset(dataset_id)


@api.get("/v1/datasets/{dataset_id}/variables", response_model=VariableCollection, tags=["Catalog"])
def list_variables(
    dataset_id: int,
    pii_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> VariableCollection:
    if not db.dataset(dataset_id):
        problem(404, "not_found", "Dataset not found.", id=dataset_id)
    items = db.variables_for(dataset_id)
    if pii_only:
        items = [row for row in items if row["is_pii"]]
    page, meta = paginate(items, limit, offset)
    return VariableCollection(data=page, meta=meta)


@api.post(
    "/v1/datasets/{dataset_id}/variables", response_model=Variable, status_code=201,
    dependencies=[Depends(require_token)], tags=["Catalog"],
)
def create_variable(dataset_id: int, payload: VariableCreate) -> Variable:
    if not db.dataset(dataset_id):
        problem(404, "not_found", "Dataset not found.", id=dataset_id)
    duplicate = db.one(
        "SELECT id FROM variables WHERE dataset_id=? AND lower(name)=lower(?)",
        (dataset_id, payload.name.strip()),
    )
    if duplicate:
        problem(409, "variable_conflict", "This dataset already has a variable with that name.", id=duplicate["id"])
    variable_id = db.create_variable(
        dataset_id, payload.name.strip(), payload.concept, payload.data_type,
        payload.standard_code, payload.is_pii, actor=API_ACTOR,
    )
    return Variable(**db.one("SELECT * FROM variables WHERE id=?", (variable_id,)))


@api.get("/v1/roles", tags=["Governance"])
def roles() -> dict[str, list[str]]:
    return db.ROLE_PERMISSIONS


@api.get(
    "/v1/users", response_model=UserCollection,
    dependencies=[Depends(require_token)], tags=["Governance"],
)
def list_users(
    role: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserCollection:
    if role is not None and role not in db.ROLES:
        problem(422, "invalid_role", "Unknown role.", allowed=db.ROLES)
    items = db.users(role)
    page, meta = paginate(items, limit, offset)
    return UserCollection(data=page, meta=meta)


@api.get(
    "/v1/access-requests", response_model=AccessCollection,
    dependencies=[Depends(require_token)], tags=["Access governance"],
)
def list_access_requests(
    request_status: str = Query(default="All", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AccessCollection:
    if request_status not in ["All", *db.ACCESS_STATUSES]:
        problem(422, "invalid_status", "Unknown access-request status.", allowed=["All", *db.ACCESS_STATUSES])
    items = db.access_requests(request_status)
    page, meta = paginate(items, limit, offset)
    return AccessCollection(data=page, meta=meta)


@api.get(
    "/v1/access-requests/{request_id}", response_model=AccessRequest,
    dependencies=[Depends(require_token)], tags=["Access governance"],
)
def get_access_request(request_id: int) -> AccessRequest:
    item = next((row for row in db.access_requests("All") if row["id"] == request_id), None)
    if not item:
        problem(404, "not_found", "Access request not found.", id=request_id)
    return AccessRequest(**item)


@api.post(
    "/v1/access-requests", response_model=AccessRequest, status_code=201,
    dependencies=[Depends(require_token)], tags=["Access governance"],
)
def create_access_request(payload: AccessCreate) -> AccessRequest:
    if not db.dataset(payload.dataset_id):
        problem(404, "dataset_not_found", "Dataset not found.", id=payload.dataset_id)
    if not db.one("SELECT id FROM users WHERE id=? AND is_active=1", (payload.requester_id,)):
        problem(404, "requester_not_found", "Requester not found.", id=payload.requester_id)
    request_id = db.create_access_request(
        payload.dataset_id, payload.requester_id, payload.purpose, actor=API_ACTOR
    )
    item = next((row for row in db.access_requests("All") if row["id"] == request_id), None)
    if not item:
        problem(422, "invalid_access_request", "The access request could not be created.")
    return AccessRequest(**item)


@api.post(
    "/v1/access-requests/{request_id}/decision", response_model=AccessRequest,
    dependencies=[Depends(require_token)], tags=["Access governance"],
)
def decide_access_request(request_id: int, payload: AccessDecision) -> AccessRequest:
    current = db.one("SELECT * FROM access_requests WHERE id=?", (request_id,))
    if not current:
        problem(404, "not_found", "Access request not found.", id=request_id)
    if current["status"] != "Pending":
        problem(409, "already_decided", "Only pending access requests can be decided.", status=current["status"])
    db.decide_access(request_id, payload.decision, actor=API_ACTOR)
    item = next(row for row in db.access_requests("All") if row["id"] == request_id)
    return AccessRequest(**item)


@api.get(
    "/v1/audit", response_model=AuditCollection,
    dependencies=[Depends(require_token)], tags=["Audit"],
)
def audit_log(
    entity: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditCollection:
    items = db.audit(limit=5000)
    if entity:
        items = [row for row in items if row.get("entity") == entity]
    page, meta = paginate(items, limit, offset)
    return AuditCollection(data=page, meta=meta)


@api.get("/v1/analytics/cohort", response_model=BreakdownResponse, tags=["Aggregate analytics"])
def cohort_breakdown(
    group_by: str = Query(default="condition"),
) -> BreakdownResponse:
    if group_by not in COHORT_DIMENSIONS:
        problem(422, "invalid_dimension", "Unknown cohort dimension.", allowed=sorted(COHORT_DIMENSIONS))
    items = [Breakdown(key=row["k"], count=row["n"]) for row in db.cohort_by(group_by)]
    return BreakdownResponse(dimension=group_by, data=items, total=sum(item.count for item in items))


@api.get("/v1/analytics/outcomes", response_model=list[OutcomeBreakdown], tags=["Aggregate analytics"])
def outcomes() -> list[OutcomeBreakdown]:
    return [OutcomeBreakdown(condition=row["condition"], outcome=row["outcome"], count=row["n"])
            for row in db.cohort_outcomes_by_condition()]


@api.get("/v1/analytics/enrollment", response_model=list[EnrollmentPoint], tags=["Aggregate analytics"])
def enrollment() -> list[EnrollmentPoint]:
    return [EnrollmentPoint(month=row["m"], count=row["n"]) for row in db.enrollment_by_month()]


@api.get(
    "/v1/disclosure/k-anonymity", response_model=KAnonymityResponse,
    dependencies=[Depends(require_token)], tags=["Disclosure control"],
)
def k_anonymity(
    quasi_identifiers: str = Query(default="age_band,sex,region"),
) -> KAnonymityResponse:
    identifiers = [part.strip() for part in quasi_identifiers.split(",") if part.strip()]
    if not identifiers or len(identifiers) > 5 or len(set(identifiers)) != len(identifiers):
        problem(422, "invalid_quasi_identifiers", "Provide one to five unique quasi-identifiers.")
    invalid = sorted(set(identifiers) - QUASI_IDENTIFIERS)
    if invalid:
        problem(422, "invalid_quasi_identifiers", "Unsupported quasi-identifiers.", invalid=invalid,
                allowed=sorted(QUASI_IDENTIFIERS))
    result = db.k_anonymity(tuple(identifiers))
    return KAnonymityResponse(
        quasi_identifiers=identifiers,
        **result,
        release_ready=result["k"] >= 5,
        warning="k-anonymity is a synthetic demo signal, not a disclosure-control guarantee.",
    )


@api.post(
    "/v1/pseudonymise", response_model=PseudonymiseResponse,
    dependencies=[Depends(require_token)], tags=["Disclosure control"],
)
def pseudonymise(payload: PseudonymiseRequest) -> PseudonymiseResponse:
    result = PseudonymiseResponse(
        pseudonym=db.pseudonymise(payload.identifier),
        warning=(
            "Demo only: production pseudonymisation requires a keyed HMAC in HSM/KMS "
            "and separately governed re-identification material."
        ),
    )
    db.log(API_ACTOR, "Pseudonymised identifier via API", "pseudonymisation")
    return result
