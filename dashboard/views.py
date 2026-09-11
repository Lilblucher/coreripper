"""Premium dashboard API  sections, tool grouping, saved results, export.

Every endpoint is Premium-only (core.decorators.premium_required → 401 if
logged out, 402 if logged-in-but-not-premium) and strictly scoped to
request.user, so one user can never read or mutate another's dashboard.

Plain Django JSON views (project convention  no DRF), csrf_exempt because
auth is the cross-origin bearer token, not a session cookie.
"""

import csv
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.decorators import premium_required
from core.views import _quota_check, _run_completion

from .models import DashboardProject, DashboardSection, DashboardSectionTool, SavedResult

FIX_SYSTEM = (
    "You are a sysadmin assistant inside a network diagnostics dashboard. Given a "
    "tool's result and a detected problem, write the specific configuration or code "
    "change needed to fix it. Reply with ONLY the config/code, no prose, no markdown "
    "fences, no explanation  it is pasted directly into a code block for the user."
)

REPORT_SYSTEM = (
    "You write a short, plain-English client report summarizing findings from a set "
    "of network/security diagnostic tool results. Plain prose paragraphs, no markdown "
    "headers or bullet lists. Call out any problems found and what to do about them; "
    "if nothing is wrong, say so plainly."
)

ASSISTANT_SYSTEM_BASE = (
    "You are CoreRipper's in-dashboard assistant, chatting with a Premium subscriber "
    "about their tool results, pinned tools, and how to use the site. Be concise, direct, "
    "and confident  you have complete, accurate knowledge of CoreRipper's real current "
    "feature set (given below), so never hedge, guess, or invent a tool/panel/button name "
    "that isn't in it. If something genuinely isn't a CoreRipper feature, say so plainly "
    "rather than making one up. You cannot run tools yourself  if asked to perform an "
    "action, tell the user exactly which real tool or panel to use and what to enter, using "
    "the exact names below."
)

CATEGORY_LABELS = {"dev-tools": "Developer Tools", "ai-tools": "AI Tools", "network-tools": "Network Tools"}

# Hand-written since these are dashboard/monitors-app *behaviors*, not rows in
# the Tool registry  the dynamic catalog below only covers the tools
# themselves. Keep this in sync with dashboard.html / monitors/models.py if
# either changes; this is what stops the assistant hallucinating things like
# a nonexistent "Monitor Setup" tool instead of the real Monitoring panel.
DASHBOARD_FEATURES_KNOWLEDGE = (
    "DASHBOARD FEATURES (Premium-only, all real and live):\n"
    "- Workbench: a shared target field runs every pinned/selected tool at once; results "
    "land in one shared stream, organized into user-created sections (\"+ New section\"), "
    "filterable by category (All / Developer / AI Productivity / Network).\n"
    "- Saved Results tab: results explicitly saved from the stream; exportable per-result or "
    "per-project as CSV/JSON via the export buttons.\n"
    "- Generate Fix: on a result card with a detected problem, produces a ready-to-paste "
    "config/code fix.\n"
    "- Generate Report: turns a project's saved results into a plain-English client summary.\n"
    "- Monitoring panel (right rail, \"Monitoring\" header with a chevron to expand/collapse, "
    "\"+ Add monitor\" button  this is the ONLY way to set up recurring monitoring, there is "
    "no separate \"Monitor Setup\" tool): schedules recurring re-checks of ONE of these 5 tools "
    "only  SSL Certificate Checker, SSL Expiration Checker, Ping Tool, HTTP Status Checker, "
    "DNS Lookup. The target field takes a BARE HOSTNAME OR IP (e.g. \"example.com\"), never a "
    "full URL with \"https://\" or a trailing slash  that makes every check fail immediately. "
    "Check interval choices: 15 min, 30 min, 1 hour, 6 hours, 24 hours, weekly. Email alerts go "
    "automatically to the account's login email; WhatsApp alerts are optional and need a phone "
    "number. Important: a monitor's very first-ever check never sends an alert even if it's "
    "already failing (there's no prior state yet to compare against)  alerts only fire on an "
    "actual CHANGE from the previous check (e.g. ok→alert, or alert→ok). Each monitor can be "
    "paused/resumed/deleted and has an expandable alert history.\n"
    "- Access tiers: Guest (3 free tool calls, no login required), Free (logged in, daily quota, "
    "local-tier tools only), Premium (every tool including API-tier ones, plus every dashboard "
    "feature above)."
)


def _build_site_knowledge():
    """Grounds the assistant in CoreRipper's actual live tool catalog, pulled
    fresh from the Tool registry so it can never drift out of sync with what's
    really deployed (same principle as this project's seed_tools.py  trust
    the real registry, not a hardcoded guess). Cached briefly since the
    catalog barely ever changes mid-session."""
    from django.core.cache import cache

    from core.models import Tool

    cached = cache.get("dashboard_assistant_site_knowledge")
    if cached is not None:
        return cached

    by_category = {}
    for t in Tool.objects.filter(status="operational").order_by("category", "name"):
        by_category.setdefault(t.category, []).append(t.name)

    lines = ["REAL TOOL CATALOG (current, live  never invent a tool name not in this list):"]
    for cat, names in by_category.items():
        lines.append(f"- {CATEGORY_LABELS.get(cat, cat)}: " + ", ".join(names))
    lines.append("")
    lines.append(DASHBOARD_FEATURES_KNOWLEDGE)

    knowledge = "\n".join(lines)
    cache.set("dashboard_assistant_site_knowledge", knowledge, 300)
    return knowledge


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _section_json(section):
    return {
        "id": section.id,
        "name": section.name,
        "order": section.order,
        "tools": [
            {"id": t.id, "tool_key": t.tool_key, "order": t.order}
            for t in section.tools.all()
        ],
    }


def _result_json(r):
    return {
        "id": r.id,
        "tool_key": r.tool_key,
        "target": r.target,
        "label": r.label,
        "result": r.result_json,
        "created_at": r.created_at.isoformat(),
    }


def _project_json(project):
    return {
        "id": project.id,
        "name": project.name,
        "target": project.target,
        "created_at": project.created_at.isoformat(),
        "results": [_result_json(r) for r in project.results.all()],
    }


# --- Sections ---------------------------------------------------------------

@csrf_exempt
@premium_required
@require_http_methods(["GET", "POST"])
def sections_view(request):
    if request.method == "GET":
        sections = (
            DashboardSection.objects.filter(user=request.user)
            .prefetch_related("tools")
        )
        return JsonResponse({"sections": [_section_json(s) for s in sections]})

    body, error = _parse_json_body(request)
    if error:
        return error
    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "missing_field", "message": "'name' is required."}, status=400)
    section = DashboardSection.objects.create(
        user=request.user, name=name[:100], order=body.get("order", 0)
    )
    return JsonResponse(_section_json(section), status=201)


@csrf_exempt
@premium_required
@require_http_methods(["PATCH", "DELETE"])
def section_detail_view(request, section_id):
    section = get_object_or_404(DashboardSection, id=section_id, user=request.user)
    if request.method == "DELETE":
        section.delete()
        return JsonResponse({"status": "deleted"})

    body, error = _parse_json_body(request)
    if error:
        return error
    if "name" in body:
        section.name = (body.get("name") or "").strip()[:100] or section.name
    if "order" in body:
        section.order = body.get("order") or 0
    section.save(update_fields=["name", "order"])
    return JsonResponse(_section_json(section))


@csrf_exempt
@premium_required
@require_http_methods(["POST"])
def section_tools_view(request, section_id):
    section = get_object_or_404(DashboardSection, id=section_id, user=request.user)
    body, error = _parse_json_body(request)
    if error:
        return error
    tool_key = (body.get("tool_key") or "").strip()
    if not tool_key:
        return JsonResponse({"error": "missing_field", "message": "'tool_key' is required."}, status=400)
    tool, _ = DashboardSectionTool.objects.get_or_create(
        section=section, tool_key=tool_key, defaults={"order": body.get("order", 0)}
    )
    return JsonResponse(_section_json(section), status=201)


@csrf_exempt
@premium_required
@require_http_methods(["DELETE"])
def section_tool_detail_view(request, section_id, tool_key):
    section = get_object_or_404(DashboardSection, id=section_id, user=request.user)
    DashboardSectionTool.objects.filter(section=section, tool_key=tool_key).delete()
    return JsonResponse(_section_json(section))


# --- Saved results ----------------------------------------------------------

@csrf_exempt
@premium_required
@require_http_methods(["GET", "POST"])
def results_view(request):
    if request.method == "GET":
        results = SavedResult.objects.filter(user=request.user)
        return JsonResponse({"results": [_result_json(r) for r in results]})

    body, error = _parse_json_body(request)
    if error:
        return error
    tool_key = (body.get("tool_key") or "").strip()
    result_json = body.get("result")
    if not tool_key or result_json is None:
        return JsonResponse(
            {"error": "missing_field", "message": "'tool_key' and 'result' are required."},
            status=400,
        )
    result = SavedResult.objects.create(
        user=request.user,
        tool_key=tool_key,
        target=(body.get("target") or "")[:255],
        result_json=result_json,
        label=(body.get("label") or "")[:100],
    )
    return JsonResponse(_result_json(result), status=201)


@csrf_exempt
@premium_required
@require_http_methods(["DELETE"])
def result_detail_view(request, result_id):
    result = get_object_or_404(SavedResult, id=result_id, user=request.user)
    result.delete()
    return JsonResponse({"status": "deleted"})


def _saved_results_pdf(user, results, *, title, target, filename):
    """PDF export of SavedResult rows. Shares build_report_pdf with the project
    report so a one-off result download and a full client report are visibly the
    same document family, just with no narrative section on this path."""
    from core.pdf import build_report_pdf

    pdf = build_report_pdf(
        title=title,
        target=target,
        narrative="",
        results=[
            {
                "tool_key": r.tool_key,
                "target": r.target,
                "created_at": r.created_at,
                "result_json": r.result_json,
            }
            for r in results
        ],
        prepared_for=(user.get_full_name() or "").strip() or user.email,
    )
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _csv_response(rows, filename):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(resp)
    writer.writerow(["id", "tool_key", "target", "label", "created_at", "result_json"])
    for r in rows:
        writer.writerow([
            r.id, r.tool_key, r.target, r.label, r.created_at.isoformat(),
            json.dumps(r.result_json, ensure_ascii=False),
        ])
    return resp


@premium_required
@require_http_methods(["GET"])
def result_export_view(request, result_id):
    result = get_object_or_404(SavedResult, id=result_id, user=request.user)
    fmt = request.GET.get("format", "json")
    if fmt == "csv":
        return _csv_response([result], f"coreripper-result-{result.id}.csv")
    if fmt == "pdf":
        return _saved_results_pdf(
            request.user, [result],
            title=result.label or f"{result.tool_key} check",
            target=result.target,
            filename=f"coreripper-result-{result.id}.pdf",
        )
    resp = JsonResponse(_result_json(result))
    resp["Content-Disposition"] = f'attachment; filename="coreripper-result-{result.id}.json"'
    return resp


@premium_required
@require_http_methods(["GET"])
def results_export_view(request):
    results = list(SavedResult.objects.filter(user=request.user))
    fmt = request.GET.get("format", "json")
    if fmt == "csv":
        return _csv_response(results, "coreripper-results.csv")
    if fmt == "pdf":
        return _saved_results_pdf(
            request.user, results,
            title="Saved results",
            target="",
            filename="coreripper-results.pdf",
        )
    resp = JsonResponse({"results": [_result_json(r) for r in results]})
    resp["Content-Disposition"] = 'attachment; filename="coreripper-results.json"'
    return resp


# --- Projects (Workbench "Save as Project") ---------------------------------

@csrf_exempt
@premium_required
@require_http_methods(["GET", "POST"])
def projects_view(request):
    if request.method == "GET":
        projects = (
            DashboardProject.objects.filter(user=request.user).prefetch_related("results")
        )
        return JsonResponse({"projects": [_project_json(p) for p in projects]})

    body, error = _parse_json_body(request)
    if error:
        return error
    name = (body.get("name") or "").strip()
    results = body.get("results")
    if not name or not results:
        return JsonResponse(
            {"error": "missing_field", "message": "'name' and a non-empty 'results' list are required."},
            status=400,
        )
    for r in results:
        if not r.get("tool_key") or r.get("result") is None:
            return JsonResponse(
                {"error": "missing_field", "message": "each result needs 'tool_key' and 'result'."},
                status=400,
            )

    project = DashboardProject.objects.create(
        user=request.user, name=name[:150], target=(body.get("target") or "")[:255]
    )
    SavedResult.objects.bulk_create(
        [
            SavedResult(
                user=request.user,
                project=project,
                tool_key=r["tool_key"],
                target=(r.get("target") or "")[:255],
                result_json=r["result"],
                label=(r.get("label") or "")[:100],
            )
            for r in results
        ]
    )
    return JsonResponse(_project_json(project), status=201)


@csrf_exempt
@premium_required
@require_http_methods(["DELETE"])
def project_detail_view(request, project_id):
    project = get_object_or_404(DashboardProject, id=project_id, user=request.user)
    project.delete()
    return JsonResponse({"status": "deleted"})


def _project_csv_response(project):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="coreripper-project-{project.id}.csv"'
    writer = csv.writer(resp)
    writer.writerow(["id", "tool_key", "target", "label", "created_at", "result_json"])
    for r in project.results.all():
        writer.writerow([
            r.id, r.tool_key, r.target, r.label, r.created_at.isoformat(),
            json.dumps(r.result_json, ensure_ascii=False),
        ])
    return resp


def _pdf_response(pdf_bytes, filename):
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _project_result_dicts(project):
    return [
        {
            "tool_key": r.tool_key,
            "target": r.target,
            "created_at": r.created_at,
            "result_json": r.result_json,
        }
        for r in project.results.all()
    ]


@premium_required
@require_http_methods(["GET"])
def project_export_view(request, project_id):
    project = get_object_or_404(DashboardProject, id=project_id, user=request.user)
    fmt = request.GET.get("format", "json")
    if fmt == "csv":
        return _project_csv_response(project)
    if fmt == "pdf":
        # No narrative here - this is the raw-evidence export, not the client
        # report. Generating one would mean an unrequested AI spend on what the
        # user asked for as a plain download; the report endpoint below is the
        # explicit path for that.
        from core.pdf import build_report_pdf

        pdf = build_report_pdf(
            title=project.name,
            target=project.target,
            narrative="",
            results=_project_result_dicts(project),
        )
        return _pdf_response(pdf, f"coreripper-project-{project.id}.pdf")
    resp = JsonResponse(_project_json(project))
    resp["Content-Disposition"] = f'attachment; filename="coreripper-project-{project.id}.json"'
    return resp


@csrf_exempt
@premium_required
@require_http_methods(["POST"])
def project_report_pdf_view(request, project_id):
    """Turn an already-generated client report into a branded PDF.

    The narrative arrives in the request body rather than being regenerated
    here on purpose: the caller has just paid for it (in credits or free-model
    quota) via project_report_view, and re-running the model to produce a
    download would charge twice and could return different prose than the one
    the user read on screen and chose to export.
    """
    body, error = _parse_json_body(request)
    if error:
        return error
    project = get_object_or_404(DashboardProject, id=project_id, user=request.user)
    narrative = (body.get("narrative") or "").strip()
    if not narrative:
        return JsonResponse(
            {"error": "missing_field", "message": "'narrative' is required."}, status=400
        )

    from core.pdf import build_report_pdf

    prepared_for = (request.user.get_full_name() or "").strip() or request.user.email
    pdf = build_report_pdf(
        title=project.name,
        target=project.target,
        narrative=narrative,
        results=_project_result_dicts(project),
        prepared_for=prepared_for,
    )
    return _pdf_response(pdf, f"coreripper-report-{project.id}.pdf")


# --- AI: Generate Fix, Generate Client Report, Assistant chat ---------------
# All three reuse core's shared LLM completion helper (core.views._run_completion)
# and its quota/budget guardrails (core.views._quota_check)  same honest
# "llm_not_configured" / "user_quota_exceeded" behavior as every other AI tool
# in this project, no separate credits ledger.

@csrf_exempt
@premium_required
@require_http_methods(["POST"])
def fix_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error
    tool_key = (body.get("tool_key") or "").strip()
    problem_text = (body.get("problem_text") or "").strip()
    if not tool_key or not problem_text:
        return JsonResponse(
            {"error": "missing_field", "message": "'tool_key' and 'problem_text' are required."},
            status=400,
        )

    target = (body.get("target") or "").strip()
    result = body.get("result")
    user_msg = f"Tool: {tool_key}\nTarget: {target}\nProblem detected: {problem_text}"
    if result is not None:
        user_msg += f"\nRaw tool result:\n{json.dumps(result, ensure_ascii=False)}"

    return _run_completion(request, "dashboard_fix", FIX_SYSTEM, user_msg, model=body.get("model"))


@csrf_exempt
@premium_required
@require_http_methods(["POST"])
def project_report_view(request, project_id):
    project = get_object_or_404(DashboardProject, id=project_id, user=request.user)

    lines = [f"Client report for: {project.target or project.name}"]
    for r in project.results.all():
        lines.append(f"- {r.tool_key} on {r.target}: {json.dumps(r.result_json, ensure_ascii=False)}")
    user_msg = "\n".join(lines)

    return _run_completion(request, "dashboard_report", REPORT_SYSTEM, user_msg)


@csrf_exempt
@premium_required
@require_http_methods(["POST"])
def assistant_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error
    message = (body.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "missing_field", "message": "'message' is required."}, status=400)

    history = body.get("history") or []
    lines = []
    for turn in history[-10:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {turn.get('text', '')}")
    lines.append(f"User: {message}")
    user_msg = "\n".join(lines)

    system = ASSISTANT_SYSTEM_BASE + "\n\n" + _build_site_knowledge()
    return _run_completion(request, "dashboard_assistant", system, user_msg, model=body.get("model"))
