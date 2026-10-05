#!/usr/bin/env python3
"""
Kaito Detector doctor - automatic System Health checks.

Runs from .github/workflows/doctor.yml after every scan and every 3 hours.
It answers "is anything broken or stale?" so nobody has to check by hand:

  1. Diagnose  - freshness, last scan run, agent output, data sanity,
                 learning loop, live sites, missing secrets.
  2. Self-heal - only scripted, predictable fixes:
                   * re-run a failed scan once (first attempt only)
                   * start a scan when data is stale and none is running
                   * fire the Render deploy hook when Render lags behind
                 Every fix is rate-limited through the state kept in
                 health.json so the doctor can never loop.
  3. Report    - writes health.json (shown as the dashboard's System Health
                 panel) and keeps ONE GitHub Issue labelled "doctor" open
                 while something is wrong, closing it when all is green.

Stdlib only, so it needs no pip install. Set DOCTOR_DRY_RUN=1 to run checks
without taking any action (no fixes, no issue changes).
"""

import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPO = os.environ.get("GITHUB_REPOSITORY", "mattappsaibagus-wq/stock-scanner")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
SCAN_WORKFLOW = "scan.yml"
RUN_URL = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{REPO}"
           f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")

DATA_PATH = os.environ.get("DOCTOR_DATA_PATH", os.path.join(ROOT, "dashboard", "data.json"))
PREV_PATH = os.environ.get("DOCTOR_PREV_HEALTH", "")
OUT_PATH = os.environ.get("DOCTOR_OUT", os.path.join(ROOT, "health.json"))
DRY_RUN = os.environ.get("DOCTOR_DRY_RUN", "").strip() in ("1", "true", "yes")
HAS_RENDER_HOOK = bool(os.environ.get("RENDER_DEPLOY_HOOK", "").strip())

SITES = {
    "GitHub Pages": "https://mattappsaibagus-wq.github.io/stock-scanner/data.json",
    "Netlify (kaitoisland)": "https://kaitoisland.netlify.app/data.json",
    "Render (tokyostockradar)": "https://tokyostockradar.onrender.com/data.json",
}

# Signal agents that should contribute every scan (macro sets the regime instead).
SIGNAL_AGENTS = ["early_detector", "momentum_agent", "pattern_agent", "sector_agent",
                 "sentiment_agent", "news_scanner", "dd_agent", "kronos_agent"]

# Scan schedule from scan.yml, UTC, Mon-Fri: (hour, minute).
SCAN_SLOTS = [(2, 45), (6, 45), (14, 0), (21, 30)]
STALE_WARN = timedelta(minutes=75)    # GitHub often starts cron runs late
STALE_FAIL = timedelta(hours=3)
REDISPATCH_COOLDOWN = timedelta(hours=3)
RENDER_COOLDOWN = timedelta(hours=2)
HISTORY_LEN = 30

OK, WARN, FAIL = "ok", "warn", "fail"
RANK = {OK: 0, WARN: 1, FAIL: 2}

NOW = datetime.now(timezone.utc)


# ----------------------------------------------------------------- helpers

def parse_ts(value):
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ago(ts):
    if ts is None:
        return "unknown"
    mins = int((NOW - ts).total_seconds() // 60)
    if mins < 60:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60}h {mins % 60:02d}m ago"
    return f"{mins // 1440} days ago"


def jst(ts):
    return (ts + timedelta(hours=9)).strftime("%m-%d %H:%M JST") if ts else "--"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def http(method, url, body=None, token=True, timeout=25):
    """Returns (status, parsed-json-or-text). Never raises."""
    headers = {"User-Agent": "kaito-doctor", "Accept": "application/vnd.github+json"}
    if token and TOKEN and url.startswith(API):
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # DNS, timeout, TLS...
        return 0, f"{type(e).__name__}: {e}"
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def gh(method, path, body=None):
    return http(method, f"{API}/repos/{REPO}{path}", body)


def check(cid, name, status, detail, **extra):
    out = {"id": cid, "name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


def last_expected_slot(now):
    """Most recent scheduled scan time at or before `now` (weekdays only)."""
    day = now.replace(second=0, microsecond=0)
    for back in range(0, 8):
        d = (day - timedelta(days=back)).date()
        if d.weekday() >= 5:
            continue
        for h, m in sorted(SCAN_SLOTS, reverse=True):
            slot = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
            if slot <= now:
                return slot
    return None


# ------------------------------------------------------------------ checks

def check_freshness(data, scan_running):
    gen = parse_ts(data.get("generated_at")) if data else None
    slot = last_expected_slot(NOW)
    if gen is None:
        return check("freshness", "Data freshness", FAIL, "data.json has no generated_at."), True
    detail = f"Last scan {jst(gen)} ({ago(gen)}). Expected run: {jst(slot)}."
    if slot is None or gen >= slot - timedelta(minutes=5):
        return check("freshness", "Data freshness", OK, detail, generated_at=gen.isoformat()), False
    late = NOW - slot
    if scan_running:
        return check("freshness", "Data freshness", OK if late < STALE_FAIL else WARN,
                     detail + " A scan is running now.", generated_at=gen.isoformat()), False
    if late < STALE_WARN:
        return check("freshness", "Data freshness", OK,
                     detail + " Scheduled run hasn't started yet (GitHub often starts late).",
                     generated_at=gen.isoformat()), False
    status = FAIL if late >= STALE_FAIL else WARN
    return check("freshness", "Data freshness", status,
                 detail + f" The {jst(slot)} scan is {int(late.total_seconds() // 60)} min overdue.",
                 generated_at=gen.isoformat()), True


def failed_run_details(run_id):
    """Failing step names + error annotations for a run, for the Issue."""
    steps, errors = [], []
    st, jobs = gh("GET", f"/actions/runs/{run_id}/jobs")
    if st != 200 or not isinstance(jobs, dict):
        return steps, errors
    for job in jobs.get("jobs", []):
        for step in job.get("steps", []) or []:
            if step.get("conclusion") == "failure":
                steps.append(step.get("name"))
        st, ann = gh("GET", f"/check-runs/{job.get('id')}/annotations")
        if st == 200 and isinstance(ann, list):
            for a in ann:
                if a.get("annotation_level") == "failure":
                    msg = (a.get("message") or "").strip().splitlines()
                    if msg:
                        errors.append(msg[0][:300])
    return steps, errors[:5]


def run_warnings(run_id):
    out = []
    st, jobs = gh("GET", f"/actions/runs/{run_id}/jobs")
    if st != 200 or not isinstance(jobs, dict):
        return out
    for job in jobs.get("jobs", []):
        st, ann = gh("GET", f"/check-runs/{job.get('id')}/annotations")
        if st == 200 and isinstance(ann, list):
            for a in ann:
                if a.get("annotation_level") == "warning":
                    msg = (a.get("message") or "").strip().splitlines()
                    # Ignore GitHub's own Node/action deprecation chatter.
                    if msg and "Node.js" not in msg[0] and "deprecated" not in msg[0].lower():
                        out.append(msg[0][:300])
    return out[:5]


def check_scan_runs():
    """Returns (check, scan_running, failed_run_or_None, warnings)."""
    if not TOKEN:
        return check("scan_run", "Last scan run", WARN, "No GITHUB_TOKEN; cannot read Actions."), False, None, []
    st, body = gh("GET", f"/actions/workflows/{SCAN_WORKFLOW}/runs?per_page=15")
    if st != 200 or not isinstance(body, dict):
        return check("scan_run", "Last scan run", WARN, f"Could not read Actions API (HTTP {st})."), False, None, []
    runs = body.get("workflow_runs", [])
    running = any(r.get("status") in ("queued", "in_progress", "waiting", "pending") for r in runs)
    done = [r for r in runs if r.get("status") == "completed"]
    if not done:
        return check("scan_run", "Last scan run", WARN, "No completed scan runs found."), running, None, []
    last = done[0]
    when = parse_ts(last.get("run_started_at") or last.get("created_at"))
    concl = last.get("conclusion")
    base = f"#{last.get('run_number')} ({last.get('event')}, attempt {last.get('run_attempt', 1)}) {ago(when)}"
    link = last.get("html_url")
    if concl == "success":
        return check("scan_run", "Last scan run", OK, f"{base}: succeeded.", url=link), running, None, run_warnings(last["id"])
    if concl in ("cancelled", "skipped"):
        return check("scan_run", "Last scan run", WARN, f"{base}: {concl}.", url=link), running, None, []
    steps, errors = failed_run_details(last["id"])
    detail = f"{base}: {concl}."
    if steps:
        detail += " Failed step: " + ", ".join(steps) + "."
    if errors:
        detail += " Error: " + " | ".join(errors)
    return (check("scan_run", "Last scan run", FAIL, detail, url=link, errors=errors),
            running, last, [])


def check_agents(data):
    sh = (data or {}).get("scan_health") or {}
    counts = sh.get("agent_results")
    source = "agent results"
    if not counts:
        # Older data.json without scan_health: fall back to who appears in recommendations.
        source = "recommendations"
        counts = {}
        for r in (data or {}).get("recommendations", []):
            for a in r.get("agents", []) or []:
                counts.setdefault(a, {"results": 0})
                counts[a]["results"] += 1
    silent = [a for a in SIGNAL_AGENTS if not (counts.get(a) or {}).get("results")]
    summary = ", ".join(f"{a.replace('_agent', '')} {(counts.get(a) or {}).get('results', 0)}"
                        for a in SIGNAL_AGENTS)
    kronos = sh.get("kronos") or {}
    extra = ""
    if "kronos_agent" in silent and kronos.get("unavailable"):
        extra = f" Kronos unavailable: {kronos['unavailable']}."
    if not silent:
        return check("agents", "Agents reporting", OK, f"All 8 signal agents produced output ({source}: {summary}).")
    status = FAIL if len(silent) >= 3 else WARN
    return check("agents", "Agents reporting", status,
                 f"Silent: {', '.join(silent)}.{extra} ({source}: {summary})", silent=silent)


def check_data(data, prev):
    recs = (data or {}).get("recommendations")
    if not isinstance(recs, list):
        return check("data", "Data sanity", FAIL, "data.json missing or has no recommendations list."), None
    problems, status = [], OK
    n = len(recs)
    hist = [h.get("recs") for h in (prev or {}).get("history", []) if isinstance(h.get("recs"), int)]
    if n == 0:
        problems.append("0 recommendations")
        status = FAIL
    elif len(hist) >= 3:
        med = statistics.median(hist[-10:])
        if med and n < 0.4 * med:
            problems.append(f"only {n} recommendations vs usual ~{int(med)}")
            status = WARN
    no_price = sum(1 for r in recs if r.get("reference_price") in (None, 0))
    if n and no_price / n > 0.1:
        problems.append(f"{no_price}/{n} recommendations have no reference price")
        status = max(status, WARN, key=RANK.get)
    reg = (data.get("regime") or {})
    if not reg.get("regime") or reg.get("regime") == "unknown" or reg.get("vix") is None:
        problems.append(f"macro regime incomplete ({reg.get('regime')}, VIX {reg.get('vix')})")
        status = max(status, WARN, key=RANK.get)
    sh = data.get("scan_health") or {}
    total, priced = sh.get("symbols_total"), sh.get("symbols_priced")
    if total and priced is not None and priced < 0.85 * total:
        problems.append(f"Yahoo priced only {priced}/{total} symbols")
        status = max(status, WARN, key=RANK.get)
    failed = sh.get("failed_symbols") or []
    if total and len(failed) > 0.1 * total:
        problems.append(f"{len(failed)} symbols errored ({', '.join(failed[:6])}{'...' if len(failed) > 6 else ''})")
        status = max(status, WARN, key=RANK.get)
    detail = (f"{n} recommendations" + (f", {priced}/{total} symbols priced" if total else "")
              + ". " + ("; ".join(problems).capitalize() + "." if problems else "Looks normal."))
    return check("data", "Data sanity", status, detail), n


def check_learning(data, prev):
    ls = (data or {}).get("learning_stats") or {}
    resolved = ls.get("resolved_recommendations")
    logged = ls.get("total_recommendations_logged")
    pstate = (prev or {}).get("state", {})
    p_resolved, p_logged = pstate.get("resolved"), pstate.get("logged")
    changed_at = parse_ts(pstate.get("resolved_changed_at")) or NOW
    if resolved is None:
        return check("learning", "Learning loop", WARN, "No learning_stats in data.json."), pstate
    new_state = {"resolved": resolved, "logged": logged, "resolved_changed_at": changed_at.isoformat()}
    if p_resolved is None or resolved != p_resolved:
        new_state["resolved_changed_at"] = NOW.isoformat()
        changed_at = NOW
    acc = ls.get("accuracy_pct")
    base = f"{resolved} resolved of {logged} logged calls, accuracy {acc}%."
    if p_resolved is not None and resolved < p_resolved:
        return check("learning", "Learning loop", FAIL,
                     f"Resolved count dropped {p_resolved} -> {resolved}: prediction history was reset or lost. {base}"), new_state
    if p_logged is not None and logged is not None and logged < p_logged:
        return check("learning", "Learning loop", FAIL,
                     f"Logged count dropped {p_logged} -> {logged}: history file was reset. {base}"), new_state
    if NOW - changed_at > timedelta(days=3):
        return check("learning", "Learning loop", WARN,
                     f"No new predictions resolved since {jst(changed_at)}. {base}"), new_state
    return check("learning", "Learning loop", OK, base), new_state


def check_sites(main_gen):
    results, render_behind = [], False
    worst, lines = OK, []
    for name, url in SITES.items():
        st, body = http("GET", url + f"?doctor={int(NOW.timestamp())}", token=False)
        if st != 200 or not isinstance(body, dict):
            s = FAIL
            msg = f"{name}: unreachable (HTTP {st})" if st else f"{name}: unreachable ({body})"
        else:
            gen = parse_ts(body.get("generated_at"))
            if main_gen and gen and gen < main_gen - timedelta(minutes=1):
                lag = main_gen - gen
                # Deploys take a few minutes after the data commit.
                s = WARN if (NOW - main_gen) > timedelta(minutes=30) else OK
                msg = f"{name}: serving scan from {jst(gen)}, {int(lag.total_seconds() // 60)} min behind repo"
                if s != OK and "Render" in name:
                    render_behind = True
            else:
                s, msg = OK, f"{name}: up to date ({jst(gen)})"
        results.append({"site": name, "url": url.rsplit("/", 1)[0] + "/", "status": s})
        lines.append(msg)
        worst = max(worst, s, key=RANK.get)
    return check("sites", "Live sites", worst, ". ".join(lines) + ".", sites=results), render_behind


def check_config(warnings):
    problems = []
    if not HAS_RENDER_HOOK:
        problems.append("RENDER_DEPLOY_HOOK secret is not set, so tokyostockradar.onrender.com never refreshes")
    for w in warnings:
        if "RENDER_DEPLOY_HOOK" in w and not HAS_RENDER_HOOK:
            continue
        problems.append(f"scan warning: {w}")
    if not problems:
        return check("config", "Secrets & warnings", OK, "No missing secrets or scan warnings.")
    return check("config", "Secrets & warnings", WARN, "; ".join(problems) + ".")


# ------------------------------------------------------------------- fixes

def fix_rerun_failed(run, state):
    if run.get("run_attempt", 1) > 1:
        return {"action": "rerun_failed_scan", "done": False,
                "result": "Already retried once and failed again - needs a human."}
    if str(run.get("id")) == str(state.get("last_rerun_id")):
        return {"action": "rerun_failed_scan", "done": False, "result": "Retry already requested."}
    if DRY_RUN:
        return {"action": "rerun_failed_scan", "done": False, "result": "Dry run: would re-run failed jobs."}
    st, _ = gh("POST", f"/actions/runs/{run['id']}/rerun-failed-jobs")
    state["last_rerun_id"] = run["id"]
    ok = st in (201, 204)
    return {"action": "rerun_failed_scan", "done": ok,
            "result": "Re-ran the failed scan (attempt 2)." if ok else f"Re-run request failed (HTTP {st})."}


def fix_dispatch_scan(state):
    last = parse_ts(state.get("last_dispatch_at"))
    if last and NOW - last < REDISPATCH_COOLDOWN:
        return {"action": "start_scan", "done": False,
                "result": f"A scan was already started by the doctor {ago(last)}; waiting."}
    if DRY_RUN:
        return {"action": "start_scan", "done": False, "result": "Dry run: would start a scan."}
    st, _ = gh("POST", f"/actions/workflows/{SCAN_WORKFLOW}/dispatches", {"ref": "main"})
    ok = st == 204
    if ok:
        state["last_dispatch_at"] = NOW.isoformat()
    return {"action": "start_scan", "done": ok,
            "result": "Started a fresh scan." if ok else f"Could not start a scan (HTTP {st})."}


def fix_render(state):
    if not HAS_RENDER_HOOK:
        return {"action": "redeploy_render", "done": False, "result": "No RENDER_DEPLOY_HOOK secret to call."}
    last = parse_ts(state.get("last_render_at"))
    if last and NOW - last < RENDER_COOLDOWN:
        return {"action": "redeploy_render", "done": False, "result": f"Redeploy already triggered {ago(last)}."}
    if DRY_RUN:
        return {"action": "redeploy_render", "done": False, "result": "Dry run: would trigger Render deploy."}
    st, _ = http("POST", os.environ["RENDER_DEPLOY_HOOK"].strip(), token=False)
    ok = 200 <= st < 300
    if ok:
        state["last_render_at"] = NOW.isoformat()
    return {"action": "redeploy_render", "done": ok,
            "result": "Triggered a Render redeploy." if ok else f"Render hook failed (HTTP {st})."}


# ------------------------------------------------------------------- issue

STATUS_WORD = {OK: "Healthy", WARN: "Warning", FAIL: "Broken"}
ICON = {OK: "🟢", WARN: "🟡", FAIL: "🔴"}


def issue_body(report):
    lines = [f"**Overall: {ICON[report['status']]} {STATUS_WORD[report['status']]}** "
             f"(checked {jst(NOW)}, [doctor run]({RUN_URL}))", "",
             "| | Check | Detail |", "|---|---|---|"]
    for c in report["checks"]:
        detail = c["detail"].replace("|", "\\|").replace("\n", " ")
        if c.get("url"):
            detail += f" [run]({c['url']})"
        lines.append(f"| {ICON[c['status']]} | {c['name']} | {detail} |")
    if report["fixes"]:
        lines += ["", "**Automatic fixes**", ""]
        lines += [f"- {'✅' if f['done'] else '⏸️'} `{f['action']}`: {f['result']}" for f in report["fixes"]]
    lines += ["", "_This issue is kept up to date by the doctor workflow and closes itself "
              "once every check is green again._"]
    return "\n".join(lines)


def sync_issue(report, prev):
    if DRY_RUN or not TOKEN:
        return None
    gh("POST", "/labels", {"name": "doctor", "color": "d93f0b",
                           "description": "Opened automatically by the System Health doctor"})
    st, issues = gh("GET", "/issues?labels=doctor&state=open&per_page=5")
    issue = issues[0] if st == 200 and isinstance(issues, list) and issues else None
    sig = sorted(f"{c['id']}:{c['status']}" for c in report["checks"] if c["status"] != OK)
    prev_sig = sorted((prev or {}).get("state", {}).get("problem_sig", []))
    report["state"]["problem_sig"] = sig

    if report["status"] == OK:
        if issue:
            gh("POST", f"/issues/{issue['number']}/comments",
               {"body": f"{ICON[OK]} All checks green again ({jst(NOW)}). Closing."})
            gh("PATCH", f"/issues/{issue['number']}", {"state": "closed", "state_reason": "completed",
                                                       "body": issue_body(report)})
        return None

    title = f"System Health: {STATUS_WORD[report['status']]} - " + ", ".join(
        c["name"] for c in report["checks"] if c["status"] != OK)
    if not issue:
        st, issue = gh("POST", "/issues", {"title": title[:240], "body": issue_body(report),
                                           "labels": ["doctor"]})
        return issue.get("html_url") if isinstance(issue, dict) else None
    gh("PATCH", f"/issues/{issue['number']}", {"title": title[:240], "body": issue_body(report)})
    if sig != prev_sig:
        # A comment is what pings your phone/email, so only add one when the
        # set of problems actually changes, not on every 3-hourly check.
        changes = [f"- {ICON[c['status']]} **{c['name']}**: {c['detail']}"
                   for c in report["checks"] if c["status"] != OK]
        gh("POST", f"/issues/{issue['number']}/comments",
           {"body": f"Problems changed ({jst(NOW)}):\n\n" + "\n".join(changes)})
    return issue.get("html_url")


# -------------------------------------------------------------------- main

def main():
    data = load_json(DATA_PATH) or {}
    prev = load_json(PREV_PATH) if PREV_PATH else None
    state = dict((prev or {}).get("state", {}))

    run_check, scan_running, failed_run, warnings = check_scan_runs()
    fresh_check, is_stale = check_freshness(data, scan_running)
    data_check, rec_count = check_data(data, prev)
    learn_check, learn_state = check_learning(data, prev)
    state.update(learn_state)
    sites_check, render_behind = check_sites(parse_ts(data.get("generated_at")))
    checks = [fresh_check, run_check, check_agents(data), data_check, learn_check,
              sites_check, check_config(warnings)]

    fixes = []
    if failed_run is not None and not scan_running:
        fixes.append(fix_rerun_failed(failed_run, state))
    elif is_stale and not scan_running:
        fixes.append(fix_dispatch_scan(state))
    if render_behind:
        fixes.append(fix_render(state))

    status = max((c["status"] for c in checks), key=RANK.get)
    history = list((prev or {}).get("history", []))
    gen = data.get("generated_at")
    if gen and (not history or history[-1].get("generated_at") != gen):
        history.append({"generated_at": gen, "recs": rec_count})
    report = {
        "checked_at": NOW.isoformat(),
        "status": status,
        "checks": checks,
        "fixes": fixes,
        "doctor_run": RUN_URL,
        "history": history[-HISTORY_LEN:],
        "state": state,
    }
    issue_url = sync_issue(report, prev)
    if issue_url:
        report["issue_url"] = issue_url

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print(f"Overall: {status.upper()}")
    for c in checks:
        print(f"  [{c['status'].upper():4}] {c['name']}: {c['detail']}")
    for f in fixes:
        print(f"  fix {f['action']}: {'done' if f['done'] else 'skipped'} - {f['result']}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(issue_body(report) + "\n")
    # The doctor itself succeeds even when the app is unhealthy; problems are
    # reported through the Issue and dashboard, not a red doctor run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
