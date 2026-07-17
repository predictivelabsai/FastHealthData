"""FastHealthData AI assistant — slash-commands + grounded multi-provider chat.

Slash-commands resolve locally against SQLite (no API key). Free-form chat is
streamed from a configurable provider and grounded with a live snapshot of the
platform (projects, catalog, access queue, cohort) so answers reflect the actual
synthetic data. Never claims the data is real.
"""
from __future__ import annotations

import json
import os

import db

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")


def snapshot() -> str:
    k = db.kpis()
    by_stage = {r["k"]: r["n"] for r in db.counts_by("projects", "stage")}
    by_std = {r["k"]: r["n"] for r in db.counts_by("datasets", "standard")}
    by_cond = {r["k"]: r["n"] for r in db.cohort_by("condition")}
    ka = db.k_anonymity()
    lines = [
        "CURRENT PLATFORM SNAPSHOT (synthetic demo data — no real PHI):",
        f"- Projects: {k['total_projects']} ({k['active_projects']} active). "
        f"Datasets: {k['datasets']} ({k['variables']} variables catalogued). Cohort subjects: {k['subjects']}.",
        f"- Access requests: {k['pending_access']} pending, {k['approved_access']} approved. "
        f"Identifiable datasets: {k['identifiable']}.",
        "Projects by stage: " + ", ".join(f"{s} {by_stage.get(s,0)}" for s in db.PROJECT_STAGES),
        "Datasets by standard: " + ", ".join(f"{s} {by_std.get(s,0)}" for s in db.STANDARDS),
        "Cohort by condition: " + ", ".join(f"{c} {n}" for c, n in by_cond.items()),
        f"k-anonymity over (age_band, sex, region): k={ka['k']} "
        f"({ka['at_risk']} subjects in classes smaller than 5).",
    ]
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the FastHealthData assistant, embedded in an open-source health research-data
platform. Help researchers, data stewards and DPOs find projects, understand the metadata catalog
(OMOP CDM / HL7 FHIR / openEHR), track data-access requests and approvals, and reason about the
synthetic study cohort. Be concise and practical; use Markdown (short tables, bold figures) when it
helps. ALL data is synthetic demo data — never claim it is real, and never invent subject-level
identifiers. Base answers on the PLATFORM SNAPSHOT below; if something isn't in it, say so plainly."""


def _table(headers, rows_):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def handle_command(text: str):
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])

    if cmd in ("help", "?"):
        return ("**FastHealthData shortcuts**\n\n"
                "- `/projects [stage]` — research projects & lifecycle\n"
                "- `/catalog [standard]` — datasets in the metadata catalog\n"
                "- `/access [status]` — data-access request queue\n"
                "- `/cohort [condition|age|sex|region]` — synthetic cohort breakdown\n"
                "- `/kanon` — k-anonymity over the cohort\n"
                "- `/kpi` — headline numbers\n\nOr ask a question in plain English.")

    if cmd == "kpi":
        k = db.kpis()
        return _table(["Metric", "Value"], [
            ["Active projects", k["active_projects"]], ["Total projects", k["total_projects"]],
            ["Datasets", k["datasets"]], ["Variables", k["variables"]],
            ["Cohort subjects", k["subjects"]], ["Pending access", k["pending_access"]],
            ["Approved access", k["approved_access"]], ["Identifiable datasets", k["identifiable"]]])

    if cmd == "projects":
        stage = arg.title() if arg else "All"
        rows_ = db.projects(stage if stage in db.PROJECT_STAGES else "All")
        if not rows_:
            return "No projects found."
        return "**Projects**\n\n" + _table(
            ["Code", "Title", "Stage", "Datasets", "Subjects"],
            [[p["code"], p["title"][:38], p["stage"], p["n_datasets"], p["n_subjects"]] for p in rows_])

    if cmd == "catalog":
        rows_ = [d for d in db.datasets() if not arg or arg.lower() in (d["standard"] or "").lower()]
        if not rows_:
            return "No datasets found."
        return "**Metadata catalog**\n\n" + _table(
            ["Dataset", "Standard", "Sensitivity", "Vars", "Subjects"],
            [[d["name"][:34], d["standard"], d["sensitivity"], d["n_vars"], f"{d['subject_count']:,}"] for d in rows_[:15]])

    if cmd == "access":
        status = arg.title() if arg else "All"
        rows_ = db.access_requests(status if status in db.ACCESS_STATUSES else "All")
        if not rows_:
            return "No access requests found."
        return "**Access requests**\n\n" + _table(
            ["#", "Dataset", "Requester", "Purpose", "Status"],
            [[f"#{r['id']}", (r["dataset"] or "—")[:24], (r["requester"] or "—")[:20],
              (r["purpose"] or "")[:34], r["status"]] for r in rows_[:15]])

    if cmd == "cohort":
        col = {"age": "age_band", "sex": "sex", "region": "region"}.get(arg.lower(), "condition")
        rows_ = db.cohort_by(col)
        if not rows_:
            return "No cohort data."
        return f"**Cohort by {col}**\n\n" + _table(
            [col, "Subjects"], [[r["k"], r["n"]] for r in rows_])

    if cmd in ("kanon", "k", "kanonymity"):
        ka = db.k_anonymity()
        head = (f"**k-anonymity** over (age_band, sex, region): **k = {ka['k']}** across "
                f"{ka['groups']} equivalence classes; {ka['at_risk']} subjects sit in classes smaller than 5.\n\n")
        return head + _table(
            ["Age band", "Sex", "Region", "Size"],
            [[g["age_band"], g["sex"], g["region"], g["n"]] for g in ka["smallest"]])

    return f"Unknown command `/{cmd}`. Try `/help`."


async def stream_chat(message: str):
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return
    system = SYSTEM_PROMPT + "\n\n" + snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


async def _provider_stream(system, message):
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": model, "stream": True,
                                           "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                     json={"model": model, "max_tokens": 1500, "stream": True,
                                           "system": system, "messages": [{"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok: yield tok
                        except json.JSONDecodeError:
                            pass
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            tok = json.loads(line[6:])["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). Set it to xai/openai/anthropic/google "
               "in `.env`. Slash-commands like `/projects` work without a key.")


def _no_key(provider):
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. Add it to `.env` and restart. "
            "Slash-commands (`/projects`, `/access`, `/cohort`, `/kanon` …) work without any key.")
