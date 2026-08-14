"""Public human-readable developer entry point for the integration API."""
from __future__ import annotations

from starlette.responses import HTMLResponse


def developer_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastHealthData Developers</title>
<style>
:root{--blue:#1e6fb8;--dark:#1b2733;--green:#1f9d72;--muted:#667085;--line:#d9e4ef}
*{box-sizing:border-box}body{margin:0;font:15px/1.6 Inter,system-ui,sans-serif;color:var(--dark);background:#f7fafc}
header,main{width:min(1080px,calc(100% - 40px));margin:auto}header{display:flex;justify-content:space-between;align-items:center;padding:22px 0}
a{color:var(--blue)}.brand{font-size:20px;font-weight:800;text-decoration:none}.back{text-decoration:none;font-weight:650}
.hero{padding:62px 0 42px}.kicker{color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
h1{margin:12px 0;font-size:clamp(38px,6vw,66px);line-height:1.02;letter-spacing:-.045em}.lede{max-width:780px;color:var(--muted);font-size:19px}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:25px}.button{padding:10px 15px;border-radius:999px;background:var(--blue);color:white;text-decoration:none;font-weight:700}.button.alt{background:white;color:var(--blue);border:1px solid var(--line)}
section{margin:20px 0 44px}.card{padding:24px;border:1px solid var(--line);border-radius:16px;background:white}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
h2{font-size:26px}h3{margin:0 0 7px}.card p{margin:0;color:var(--muted)}code{padding:2px 6px;border-radius:5px;background:#edf5fb;color:#17568f}
table{width:100%;border-collapse:collapse;background:white;border:1px solid var(--line)}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#edf5fb}
.note{padding:17px 20px;border-left:4px solid var(--green);background:#eef9f5}@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header><a class="brand" href="/">FastHealthData</a><a class="back" href="/login">Open platform →</a></header>
<main><div class="hero"><span class="kicker">Integration API · v1</span><h1>Governed health research data, as a typed API.</h1>
<p class="lede">Projects, standards-aware metadata, access decisions, audit evidence, disclosure signals, and aggregate synthetic cohort analytics. No PHI is present in the public demo.</p>
<div class="actions"><a class="button" href="/api/docs">Swagger UI</a><a class="button alt" href="/api/redoc">ReDoc</a><a class="button alt" href="/api/openapi.json">OpenAPI JSON</a></div></div>
<section><h2>Access model</h2><div class="grid">
<div class="card"><h3>Public synthetic reads</h3><p>Portfolio summary, projects, catalog metadata, variables, roles, and aggregate cohort analytics.</p></div>
<div class="card"><h3>Bearer-token governance</h3><p>Project registration and lifecycle changes, users, access requests and decisions, audit events, pseudonymisation, and k-anonymity signals.</p></div>
</div></section>
<section><h2>API groups</h2><table><thead><tr><th>Group</th><th>Representative endpoints</th><th>Policy</th></tr></thead><tbody>
<tr><td>System & portfolio</td><td><code>/v1/health</code> · <code>/v1/summary</code></td><td>Public synthetic</td></tr>
<tr><td>Projects</td><td><code>/v1/projects</code> · <code>/v1/projects/{id}/stage</code></td><td>Public read · token write</td></tr>
<tr><td>Metadata catalog</td><td><code>/v1/datasets</code> · <code>/v1/datasets/{id}/variables</code></td><td>Public read · token register/update</td></tr>
<tr><td>Access governance</td><td><code>/v1/access-requests</code> · <code>/{id}/decision</code></td><td>Token required</td></tr>
<tr><td>Analytics</td><td><code>/v1/analytics/cohort</code> · <code>/outcomes</code> · <code>/enrollment</code></td><td>Aggregates only</td></tr>
<tr><td>Disclosure control</td><td><code>/v1/disclosure/k-anonymity</code> · <code>/v1/pseudonymise</code></td><td>Token required · demo signals</td></tr>
<tr><td>Audit</td><td><code>/v1/audit</code></td><td>Token required</td></tr>
</tbody></table></section>
<section class="note"><strong>Production boundary.</strong> The pseudonymisation and k-anonymity endpoints demonstrate workflow contracts, not production disclosure control. Production requires HSM/KMS-backed keying, separately governed re-identification material, stronger identity/RBAC, and formal release review.</section>
</main></body></html>""")
