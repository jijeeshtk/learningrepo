#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, os, sys, time, math, socket
from datetime import datetime
from typing import List, Dict, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

# ---------- Inputs (mapped from your Actions env) ----------
JIRA_URL = os.getenv("JIRA_URL", "https://atos-global.atlassian.net").rstrip("/")
JIRA_USER = os.getenv("JIRA_VCS_API_EMAIL")                       # Variables
JIRA_TOKEN = os.getenv("JIRA_VCS_API_TOKEN")                      # Secrets
TEAMS_WEBHOOK_URL = os.getenv("JIRA_VCS_BUG_CLOSE_ALERT_TEAM_URL")# Variables

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "48"))
DEFAULT_JQL = f'project = VCS AND type IN (Bug, Defect) AND updated >= -{LOOKBACK_HOURS}h'
JQL = os.getenv("JQL", DEFAULT_JQL)

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "15"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
DEBUG = os.getenv("DEBUG", "0") == "1"
TEAMS_MODE = os.getenv("TEAMS_MODE", "text").lower()  # "text" or "card"

# ---------- Jira Enhanced Search endpoint (token pagination) ----------
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search/jql"

# Explicit fields (the enhanced API returns IDs by default)
FIELDS = [
    "summary","issuetype","status","priority","assignee","reporter","customfield_10014",
    "created","resolutiondate","customfield_10020","versions","fixVersions","customfield_11049",
    "customfield_11034","customfield_10001","customfield_11067","customfield_11062",
    "customfield_11055","updated"
]

USER_AGENT = f"VCS-BugReportBot/1.0 (+GitHubActions; host={socket.gethostname()})"

# ---------- Helpers ----------
def log(msg: str):
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)

def dbg(msg: str):
    if DEBUG:
        log(f"DEBUG: {msg}")

def nz(v, d=""): return d if v in (None, "") else v
def to_string(v): return "" if v in (None, "") else (str(v) if not isinstance(v, str) else v)

def safe_date(value):
    if not value: return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z","%Y-%m-%dT%H:%M:%S%z"):
        try: return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M %Z")
        except Exception: pass
    return to_string(value)

def build_session() -> requests.Session:
    """Create a Session with sane retries & timeouts."""
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    # Retries: handle 429 / transient 5xx / connect timeouts
    retries = Retry(
        total=5,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET","POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def fetch_all_issues(jql: str) -> List[Dict]:
    if not JIRA_USER or not JIRA_TOKEN:
        print("ERROR: Jira credentials missing (JIRA_VCS_API_EMAIL / JIRA_VCS_API_TOKEN).", file=sys.stderr)
        sys.exit(2)

    s = build_session()
    auth = (JIRA_USER, JIRA_TOKEN)

    issues = []
    next_token: Optional[str] = None
    max_results = 50
    page = 1
    while True:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token

        resp = s.get(SEARCH_URL, auth=auth, params=params, timeout=30)
        dbg(f"Jira GET: {resp.url} (status={resp.status_code})")
        if resp.status_code >= 400:
            print(f"ERROR: Jira search failed {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(3)

        data = resp.json()
        batch = data.get("issues", []) or []
        dbg(f"Page {page}: fetched {len(batch)} issues")
        issues.extend(batch)

        next_token = data.get("nextPageToken")
        if not next_token:
            break
        page += 1

    return issues

def format_issue(issue: Dict) -> Dict:
    f = issue.get("fields", {}) or {}
    # Sprint (customfield_10020) might be list or dict
    sprint_value = ""
    sdata = f.get("customfield_10020")
    if isinstance(sdata, list):
        sprint_value = ", ".join(nz(s.get("name")) for s in sdata if isinstance(s, dict))
    elif isinstance(sdata, dict):
        sprint_value = nz(sdata.get("name"))

    a, r = f.get("assignee"), f.get("reporter")
    assignee_value = (nz(a.get("emailAddress")) or nz(a.get("displayName"))) if isinstance(a, dict) else ""
    reporter_value = (nz(r.get("emailAddress")) or nz(r.get("displayName"))) if isinstance(r, dict) else ""

    affects_versions = [nz(v.get("name")) for v in f.get("versions", []) if isinstance(v, dict)]
    fix_versions = [nz(v.get("name")) for v in f.get("fixVersions", []) if isinstance(v, dict)]

    customers_field = f.get("customfield_11049", [])
    customers_value = ", ".join(nz(c) for c in customers_field) if isinstance(customers_field, list) else nz(customers_field)

    summary = nz(f.get("summary"))
    if len(summary) > 180:
        summary = summary[:177] + "..."

    return {
        "key": nz(issue.get("key")),
        "summary": summary,
        "IssueType": nz((f.get("issuetype") or {}).get("name")),
        "Status": nz((f.get("status") or {}).get("name")),
        "Priority": nz((f.get("priority") or {}).get("name")),
        "Assignee": assignee_value,
        "Reporter": reporter_value,
        "EpicLink": nz(f.get("customfield_10014")),
        "Created": safe_date(f.get("created")),
        "Updated": safe_date(f.get("updated")),
        "Resolved": safe_date(f.get("resolutiondate")),
        "Sprint": sprint_value,
        "AffectsVersions": affects_versions,
        "FixVersions": fix_versions,
        "Customers": customers_value,
        "ScrumTeams": nz((f.get("customfield_11034") or {}).get("value")),
        "Teams": nz((f.get("customfield_10001") or {}).get("name")),
        "RootCause": nz((f.get("customfield_11067") or {}).get("value")),
        "BugMaturity": to_string(f.get("customfield_11062")),
        "ReleasePackage": nz(f.get("customfield_11055")),
        "Browse": f"{JIRA_URL}/browse/{nz(issue.get('key'))}",
    }

def chunk(lst: List, size: int) -> List[List]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]

def _teams_session() -> requests.Session:
    s = build_session()
    s.headers.update({"Content-Type": "application/json"})
    return s

def post_to_teams_text(text: str):
    if DRY_RUN:
        dbg(f"[DRY_RUN] Would post to Teams (text): {text[:4000]}")
        return
    if not TEAMS_WEBHOOK_URL:
        print("ERROR: Teams webhook is not set (JIRA_VCS_BUG_CLOSE_ALERT_TEAM_URL).", file=sys.stderr)
        sys.exit(4)

    s = _teams_session()
    payload = {"text": text}
    resp = s.post(TEAMS_WEBHOOK_URL, data=json.dumps(payload), timeout=30)
    dbg(f"POST Teams text status={resp.status_code}")
    if resp.status_code < 200 or resp.status_code >= 300:
        print(f"ERROR: Teams webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(6)

def post_to_teams_card(title: str, items: List[Dict]):
    """Simple Adaptive Card (safe, compact)."""
    if DRY_RUN:
        dbg(f"[DRY_RUN] Would post to Teams (card) with {len(items)} items")
        return
    if not TEAMS_WEBHOOK_URL:
        print("ERROR: Teams webhook is not set (JIRA_VCS_BUG_CLOSE_ALERT_TEAM_URL).", file=sys.stderr)
        sys.exit(4)

    # Limit list for card size; card is visually denser than code block
    max_items = 15
    subset = items[:max_items]

    facts = []
    for i in subset:
        facts.append({"title": i["key"], "value": f"{i['Status']} • {i['Priority']} • {i['Assignee']}\n{i['summary']}\n{ i['Browse'] }"})

    card = {
      "type": "message",
      "attachments": [
        {
          "contentType": "application/vnd.microsoft.card.adaptive",
          "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
              {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
              {"type": "FactSet", "facts": facts}
            ]
          }
        }
      ]
    }

    s = _teams_session()
    resp = s.post(TEAMS_WEBHOOK_URL, data=json.dumps(card), timeout=30)
    dbg(f"POST Teams card status={resp.status_code}")
    if resp.status_code < 200 or resp.status_code >= 300:
        print(f"ERROR: Teams webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(6)

def write_summary(total: int, batches: int, lookback: int, sample_keys: List[str]):
    """Append a short report to the Actions job 'Summary' tab."""
    # GitHub automatically populates GITHUB_STEP_SUMMARY file path.
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"### Bug Updated Report\n")
        f.write(f"- Lookback: **{lookback}h**\n")
        f.write(f"- Total issues: **{total}**\n")
        f.write(f"- Batches sent: **{batches}**\n")
        if sample_keys:
            f.write(f"- Sample: `{', '.join(sample_keys[:10])}`\n")

def main():
    log(f"Running Jira Bug/Defect update report for last {LOOKBACK_HOURS}h…")
    log(f"JQL: {JQL}")

    t0 = time.time()
    issues_raw = fetch_all_issues(JQL)
    issues = [format_issue(i) for i in issues_raw]
    elapsed = time.time() - t0
    dbg(f"Fetched & formatted {len(issues)} issues in {elapsed:.2f}s")

    # Persist output for auditing
    with open("jira.json", "w", encoding="utf-8") as f:
        json.dump({"issues": issues}, f, indent=2, ensure_ascii=False)

    total = len(issues)
    log(f"Total issues: {total}")

    # Summary in GH UI
    write_summary(total, math.ceil(total / max(1, BATCH_SIZE)), LOOKBACK_HOURS, [i["key"] for i in issues])

    if total == 0:
        msg = f"No Bugs/Defects updated in the last {LOOKBACK_HOURS}h. (Heartbeat)"
        if TEAMS_MODE == "card":
            post_to_teams_card("Bug Updated Report — No Updates", [])
        else:
            post_to_teams_text(msg)
        log("Posted heartbeat to Teams.")
        return

    # Chunk & send
    batches = chunk(issues, BATCH_SIZE)
    total_batches = len(batches)

    for idx, b in enumerate(batches, start=1):
        header = f"Bug Updated Report — Batch {idx}/{total_batches} (items {(idx-1)*BATCH_SIZE + 1}..{(idx-1)*BATCH_SIZE + len(b)})"

        if TEAMS_MODE == "card":
            post_to_teams_card(header, b)
        else:
            body = json.dumps({"issues": b}, indent=2, ensure_ascii=False)
            text = f"{header}\n```json\n{body}\n```"
            # Guard for Teams payload size; switch to compact lines if too big
            if len(text.encode("utf-8")) > 25000:
                lines = [
                    f"- {i['key']} | {i['Status']} | {i['Priority']} | {i['Assignee']} | {i['summary']}"
                    for i in b
                ]
                text = f"{header}\n" + "\n".join(lines)
            post_to_teams_text(text)

        log(f"Posted batch {idx}/{total_batches} to Teams.")
        time.sleep(1)  # polite pacing

    log("All batches posted to Teams successfully.")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: Unhandled exception: {e}", file=sys.stderr)
        sys.exit(9)
