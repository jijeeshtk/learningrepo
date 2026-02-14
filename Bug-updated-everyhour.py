#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jira → Teams: Bugs/Defects updated in the last N hours
- Uses Jira Cloud Search API (GET /rest/api/3/search) with startAt/maxResults pagination.
- Builds a compact JSON summary and posts to a Teams Incoming Webhook in batches.
- Sends a "no results" heartbeat if nothing matches (so you still see the job is alive).
- Exits non-zero if Jira or Teams calls fail.

Required secrets/env:
  JIRA_VCS_API_EMAIL        -> Jira user (email)
  JIRA_VCS_API_TOKEN        -> Jira API token
  TEAMS_WEBHOOK_URL         -> Teams Incoming Webhook URL (use repository/organization secret)

Optional env:
  JIRA_URL                  -> Defaults to 'https://atos-global.atlassian.net'
  LOOKBACK_HOURS            -> Defaults to '48'
  JQL                       -> Overrides default JQL
  BATCH_SIZE                -> Defaults to '15'
  DRY_RUN                   -> If '1', will not post to Teams (prints to stdout instead)
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import List, Dict

import requests

# ---------- Configuration from env ----------
JIRA_URL = os.getenv("JIRA_URL", "https://atos-global.atlassian.net").rstrip("/")
JIRA_USER = os.getenv("JIRA_VCS_API_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_VCS_API_TOKEN")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "48"))
DEFAULT_JQL = f'project = VCS AND type IN (Bug, Defect) AND updated >= -{LOOKBACK_HOURS}h'
JQL = os.getenv("JQL", DEFAULT_JQL)

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "15"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

# Jira endpoint (documented)
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search"

# Fields to retrieve (add/remove based on your schema)
FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020",
    "versions", "fixVersions", "customfield_11049", "customfield_11034",
    "customfield_10001", "customfield_11067", "customfield_11062",
    "customfield_11055", "updated"
]


def nz(value, default=""):
    return default if value in (None, "") else value


def to_string(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def safe_date(value):
    if not value:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            pass
    return to_string(value)


def fetch_all_issues(jql: str) -> List[Dict]:
    """Fetch all issues using classic pagination."""
    if not JIRA_USER or not JIRA_TOKEN:
        print("ERROR: Jira credentials are missing (JIRA_VCS_API_EMAIL / JIRA_VCS_API_TOKEN).", file=sys.stderr)
        sys.exit(2)

    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    issues = []
    start_at = 0
    max_results = 50

    while True:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": ",".join(FIELDS),
        }
        resp = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params, timeout=30)
        if resp.status_code >= 400:
            print(f"ERROR: Jira search failed {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(3)

        data = resp.json()
        batch = data.get("issues", []) or []
        issues.extend(batch)

        total = data.get("total", 0)
        got = data.get("maxResults", len(batch)) or len(batch)

        if start_at + got >= total or not batch:
            break
        start_at += got

    return issues


def format_issue(issue: Dict) -> Dict:
    """Project only the necessary fields, keeping payload small but useful."""
    fields = issue.get("fields", {}) or {}

    # Sprint (customfield_10020) can be list or dict
    sprint_value = ""
    sprint_data = fields.get("customfield_10020")
    if isinstance(sprint_data, list):
        sprint_value = ", ".join(nz(s.get("name")) for s in sprint_data if isinstance(s, dict))
    elif isinstance(sprint_data, dict):
        sprint_value = nz(sprint_data.get("name"))

    a = fields.get("assignee")
    assignee_value = (nz(a.get("emailAddress")) or nz(a.get("displayName"))) if isinstance(a, dict) else ""
    r = fields.get("reporter")
    reporter_value = (nz(r.get("emailAddress")) or nz(r.get("displayName"))) if isinstance(r, dict) else ""

    affects_versions = [nz(v.get("name")) for v in fields.get("versions", []) if isinstance(v, dict)]
    fix_versions = [nz(v.get("name")) for v in fields.get("fixVersions", []) if isinstance(v, dict)]

    customers_field = fields.get("customfield_11049", [])
    if isinstance(customers_field, list):
        customers_value = ", ".join(nz(c) for c in customers_field)
    else:
        customers_value = nz(customers_field)

    # Trim long summaries for Teams readability
    summary = nz(fields.get("summary"))
    if len(summary) > 180:
        summary = summary[:177] + "..."

    return {
        "key": nz(issue.get("key")),
        "summary": summary,
        "IssueType": nz((fields.get("issuetype") or {}).get("name")),
        "Status": nz((fields.get("status") or {}).get("name")),
        "Priority": nz((fields.get("priority") or {}).get("name")),
        "Assignee": assignee_value,
        "Reporter": reporter_value,
        "EpicLink": nz(fields.get("customfield_10014")),
        "Created": safe_date(fields.get("created")),
        "Updated": safe_date(fields.get("updated")),
        "Resolved": safe_date(fields.get("resolutiondate")),
        "Sprint": sprint_value,
        "AffectsVersions": affects_versions,
        "FixVersions": fix_versions,
        "Customers": customers_value,
        "ScrumTeams": nz((fields.get("customfield_11034") or {}).get("value")),
        "Teams": nz((fields.get("customfield_10001") or {}).get("name")),
        "RootCause": nz((fields.get("customfield_11067") or {}).get("value")),
        "BugMaturity": to_string(fields.get("customfield_11062")),
        "ReleasePackage": nz(fields.get("customfield_11055")),
        "Browse": f"{JIRA_URL}/browse/{nz(issue.get('key'))}",
    }


def chunk(lst: List, size: int) -> List[List]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def post_to_teams(text: str) -> None:
    """Post a simple text message to Teams via Incoming Webhook."""
    if DRY_RUN:
        print(f"[DRY_RUN] Would post to Teams:\n{text[:8000]}\n---")
        return

    if not TEAMS_WEBHOOK_URL:
        print("ERROR: TEAMS_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(4)

    payload = {"text": text}
    try:
        resp = requests.post(TEAMS_WEBHOOK_URL, headers={"Content-Type": "application/json"},
                             data=json.dumps(payload), timeout=30)
    except Exception as e:
        print(f"ERROR: Teams post failed: {e}", file=sys.stderr)
        sys.exit(5)

    if resp.status_code < 200 or resp.status_code >= 300:
        print(f"ERROR: Teams webhook returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(6)


def main():
    print(f"Running Jira Bug/Defect update report for last {LOOKBACK_HOURS}h...")
    print(f"JQL: {JQL}")

    issues = fetch_all_issues(JQL)
    formatted = [format_issue(i) for i in issues]

    # Always write jira.json for debugging/auditing (artifact optional)
    with open("jira.json", "w", encoding="utf-8") as f:
        json.dump({"issues": formatted}, f, indent=2, ensure_ascii=False)

    total = len(formatted)
    print(f"Total issues: {total}")

    if total == 0:
        msg = f"No Bugs/Defects updated in the last {LOOKBACK_HOURS}h. (Heartbeat)"
        post_to_teams(msg)
        print("Posted heartbeat to Teams.")
        return

    batches = chunk(formatted, BATCH_SIZE)
    total_batches = len(batches)

    for idx, b in enumerate(batches, start=1):
        # Keep payload compact: send a JSON code block with only the fields we formatted
        header = f"Bug Updated Report — Batch {idx}/{total_batches} (items {(idx-1)*BATCH_SIZE + 1}..{(idx-1)*BATCH_SIZE + len(b)})"
        body = json.dumps({"issues": b}, indent=2, ensure_ascii=False)
        text = f"{header}\n```json\n{body}\n```"

        # Teams has message size limits; if too big, fall back to a compact line list.
        if len(text.encode("utf-8")) > 25000:
            # Compact fallback
            compact_lines = [
                f"- {i['key']} | {i['Status']} | {i['Priority']} | {i['Assignee']} | {i['summary']}"
                for i in b
            ]
            text = f"{header}\n" + "\n".join(compact_lines)

        post_to_teams(text)
        print(f"Posted batch {idx}/{total_batches} to Teams.")
        time.sleep(1)  # a tiny delay is polite

    print("All batches posted to Teams successfully.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: Unhandled exception: {e}", file=sys.stderr)
        sys.exit(9)
