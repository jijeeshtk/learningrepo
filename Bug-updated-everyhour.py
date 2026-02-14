#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, sys, time, requests
from datetime import datetime
from typing import List, Dict

# ---------- Inputs (mapped from your Actions env) ----------
JIRA_URL = os.getenv("JIRA_URL", "https://atos-global.atlassian.net").rstrip("/")
JIRA_USER = os.getenv("JIRA_VCS_API_EMAIL")                 # from Variables
JIRA_TOKEN = os.getenv("JIRA_VCS_API_TOKEN")                # from Secrets
TEAMS_WEBHOOK_URL = os.getenv("JIRA_VCS_BUG_CLOSE_ALERT_TEAM_URL")  # from Variables

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "48"))
# IMPORTANT: plain >= (no HTML entities)
DEFAULT_JQL = f'project = VCS AND type IN (Bug, Defect) AND updated >= -{LOOKBACK_HOURS}h'
JQL = os.getenv("JQL", DEFAULT_JQL)

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "15"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
DEBUG = os.getenv("DEBUG", "0") == "1"

# ---------- Jira Enhanced Search endpoint (token pagination) ----------
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search/jql"

# Explicit fields (new API returns only IDs unless you request fields)
FIELDS = [
    "summary","issuetype","status","priority","assignee","reporter","customfield_10014",
    "created","resolutiondate","customfield_10020","versions","fixVersions","customfield_11049",
    "customfield_11034","customfield_10001","customfield_11067","customfield_11062",
    "customfield_11055","updated"
]

def nz(v, d=""): return d if v in (None, "") else v
def to_string(v): return "" if v in (None, "") else (str(v) if not isinstance(v, str) else v)

def safe_date(value):
    if not value: return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z","%Y-%m-%dT%H:%M:%S%z"):
        try: return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M %Z")
        except Exception: pass
    return to_string(value)

def fetch_all_issues(jql: str) -> List[Dict]:
    if not JIRA_USER or not JIRA_TOKEN:
        print("ERROR: Jira credentials missing (JIRA_VCS_API_EMAIL / JIRA_VCS_API_TOKEN).", file=sys.stderr)
        sys.exit(2)

    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    issues = []
    next_token = None
    max_results = 50

    while True:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token

        resp = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params, timeout=30)
        if DEBUG:
            print(f"[DEBUG] Jira GET URL: {resp.url}", file=sys.stderr)
        if resp.status_code >= 400:
            print(f"ERROR: Jira search failed {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(3)

        data = resp.json()
        batch = data.get("issues", []) or []
        issues.extend(batch)

        next_token = data.get("nextPageToken")
        if not next_token:
            break

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

def chunk(lst: List, size: int) -> List[List]: return [lst[i:i+size] for i in range(0, len(lst), size)]

def post_to_teams(text: str):
    if DRY_RUN:
        print(f"[DRY_RUN] Would post to Teams:\n{text[:8000]}\n---")
        return
    if not TEAMS_WEBHOOK_URL:
        print("ERROR: Teams webhook is not set (JIRA_VCS_BUG_CLOSE_ALERT_TEAM_URL).", file=sys.stderr)
        sys.exit(4)
    resp = requests.post(
        TEAMS_WEBHOOK_URL,
        headers={"Content-Type":"application/json"},
        data=json.dumps({"text": text}),
        timeout=30
    )
    if resp.status_code < 200 or resp.status_code >= 300:
        print(f"ERROR: Teams webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(6)

def main():
    print(f"Running Jira Bug/Defect update report for last {LOOKBACK_HOURS}h...")
    print(f"JQL: {JQL}")
    issues = fetch_all_issues(JQL)
    formatted = [format_issue(i) for i in issues]

    # Persist output for auditing
    with open("jira.json", "w", encoding="utf-8") as f:
        json.dump({"issues": formatted}, f, indent=2, ensure_ascii=False)

    total = len(formatted)
    print(f"Total issues: {total}")

    if total == 0:
        post_to_teams(f"No Bugs/Defects updated in the last {LOOKBACK_HOURS}h. (Heartbeat)")
        print("Posted heartbeat to Teams.")
        return

    batches = chunk(formatted, BATCH_SIZE)
    total_batches = len(batches)

    for idx, b in enumerate(batches, start=1):
        header = f"Bug Updated Report — Batch {idx}/{total_batches} (items {(idx-1)*BATCH_SIZE + 1}..{(idx-1)*BATCH_SIZE + len(b)})"
        body = json.dumps({"issues": b}, indent=2, ensure_ascii=False)
        text = f"{header}\n```json\n{body}\n```"

        # Fallback if message is too large for Teams
        if len(text.encode("utf-8")) > 25000:
            compact = "\n".join(
                f"- {i['key']} | {i['Status']} | {i['Priority']} | {i['Assignee']} | {i['summary']}"
                for i in b
            )
            text = f"{header}\n{compact}"

        post_to_teams(text)
        print(f"Posted batch {idx}/{total_batches} to Teams.")
        time.sleep(1)

    print("All batches posted to Teams successfully.")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: Unhandled exception: {e}", file=sys.stderr)
        sys.exit(9)
