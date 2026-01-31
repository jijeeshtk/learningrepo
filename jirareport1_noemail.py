#!/usr/bin/env python3
"""
Generates jira_report.json with assignee/reporter identity fields.
- Searches via GET /rest/api/3/search/jql + nextPageToken pagination.
- Resolves emails (if visible) via /rest/api/3/user/bulk using accountId.
- Always outputs name + accountId; includes email when available.
- Optionally enriches email from local user_mapping.csv (accountId,email).

Prereqs:
  export JIRA_USER="your.atlassian.login@company.com"
  export JIRA_TOKEN="your_api_token_from_id.atlassian.com"
"""

import csv
import json
import os
from datetime import datetime
from typing import Dict, Set, List, Tuple

import requests

# =======================
# Configuration
# =======================

JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")     # Atlassian account email (required)
JIRA_TOKEN = os.getenv("JIRA_TOKEN")   # API token from https://id.atlassian.com (required)

# RAW JQL (do NOT pre-encode; requests will encode once)
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -48h'

# Fields to fetch. Adjust as needed; ensure custom fields exist in your site.
FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020",
    "versions", "fixVersions", "customfield_11049", "customfield_11034",
    "customfield_10001", "customfield_11067", "customfield_11062",
    "customfield_11055"
]

# Page size for each API request
MAX_RESULTS = 50

# Output file
OUTPUT_JSON = "jira_report.json"

# Optional: local mapping file to enrich emails when Jira hides them
LOCAL_MAPPING_CSV = "user_mapping.csv"   # columns: accountId,email

# Behavior toggles
STRICT_EMAIL = False
"""
If True: "Assignee" and "Reporter" in the flat fields will be email ONLY ("" if hidden)
If False: "Assignee" and "Reporter" in the flat fields will prefer email, else name
Regardless, the detailed objects include {email,name,accountId}.
"""

# =======================
# Helpers
# =======================

def _nz(value, default=""):
    return default if (value is None or value == "") else value

def _safe_date(value: str) -> str:
    if not value:
        return ""
    formats = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except Exception:
            pass
    return _nz(value)

def _load_local_mapping(path: str) -> Dict[str, str]:
    """
    Returns {accountId: email} from optional CSV mapping file.
    If file doesn't exist, returns {}.
    """
    if not os.path.isfile(path):
        return {}
    mapping = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = (row.get("accountId") or "").strip()
            eml = (row.get("email") or "").strip()
            if aid and eml:
                mapping[aid] = eml
    return mapping

# =======================
# Jira API calls
# =======================

def fetch_all_issues() -> List[dict]:
    """
    Uses GET /rest/api/3/search/jql with nextPageToken pagination.
    Provide RAW JQL in params so 'requests' URL-encodes it exactly once.
    Atlassian KB explains the new endpoint and the need for URL-encoding on GET,
    which the client handles for us. Pagination is via nextPageToken. [KB ref]
    """
    if not JIRA_USER or not JIRA_TOKEN:
        raise SystemExit("JIRA_USER or JIRA_TOKEN not set in environment.")

    url = f"{JIRA_URL}/rest/api/3/search/jql"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    all_issues = []
    next_token = None

    while True:
        params = {
            "jql": JQL,                         # raw JQL; requests encodes once
            "maxResults": str(MAX_RESULTS),
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token

        resp = requests.get(url, headers=headers, auth=auth, params=params)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            print("Search API (GET /search/jql) failed.")
            print("Status:", resp.status_code)
            print("URL:", resp.url)
            print("Response:", resp.text[:2000])
            raise

        data = resp.json() or {}
        issues = data.get("issues", [])
        all_issues.extend(issues)

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return all_issues

def fetch_user_emails_bulk(account_ids: Set[str]) -> Dict[str, Dict[str, str]]:
    """
    Resolve emails via /rest/api/3/user/bulk.
    NOTE: Jira Cloud will omit emailAddress if your org privacy setting hides emails
    (then you'll only get displayName). This is by design. [REST v3 docs]
    Returns: {accountId: {"email": <or None>, "name": <displayName or None>}}
    """
    if not account_ids:
        return {}

    url = f"{JIRA_URL}/rest/api/3/user/bulk"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    # Multiple accountId params supported
    params = [("accountId", aid) for aid in sorted(account_ids)]
    resp = requests.get(url, headers=headers, auth=auth, params=params)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print("Bulk user API failed.")
        print("Status:", resp.status_code)
        print("URL:", resp.url)
        print("Response:", resp.text[:2000])
        raise

    data = resp.json() or {}
    out = {}
    for u in data.get("values", []):
        aid = u.get("accountId")
        if not aid:
            continue
        out[aid] = {
            "email": u.get("emailAddress"),   # May be None if hidden by policy
            "name": u.get("displayName")
        }
    return out

# =======================
# Report formatting
# =======================

def _extract_sprint_value(sprint_data) -> str:
    # customfield_10020 can be a list or dict depending on board/app
    if isinstance(sprint_data, list):
        return ", ".join([_nz(s.get("name")) for s in sprint_data if isinstance(s, dict)])
    if isinstance(sprint_data, dict):
        return _nz(sprint_data.get("name"))
    return ""

def _resolve_identity(field_obj: dict,
                      user_lookup: Dict[str, Dict[str, str]],
                      local_map: Dict[str, str]) -> Tuple[str, str, str]:
    """
    Returns (email, name, accountId) for a Jira user field (assignee/reporter).
    Precedence for email:
      1) emailAddress from user_lookup (if Jira exposes it)
      2) local CSV mapping user_mapping.csv (accountId -> email)
      3) None / ""
    """
    if not isinstance(field_obj, dict):
        return "", "", ""
    account_id = field_obj.get("accountId") or ""
    display_name = _nz(field_obj.get("displayName"))
    email = ""

    if account_id and account_id in user_lookup:
        email = _nz(user_lookup[account_id].get("email"))

    # If Jira hides email, try local CSV mapping
    if (not email) and account_id and local_map:
        mapped = local_map.get(account_id, "")
        if mapped:
            email = mapped

    return email, display_name, account_id

def format_report(issues: List[dict]) -> str:
    # Collect accountIds for assignee + reporter
    account_ids = set()
    for issue in issues:
        f = issue.get("fields", {}) or {}
        a, r = f.get("assignee"), f.get("reporter")
        if isinstance(a, dict) and a.get("accountId"):
            account_ids.add(a["accountId"])
        if isinstance(r, dict) and r.get("accountId"):
            account_ids.add(r["accountId"])

    # Resolve via Jira bulk API
    user_lookup = fetch_user_emails_bulk(account_ids)

    # Optional local mapping to enrich emails when hidden
    local_map = _load_local_mapping(LOCAL_MAPPING_CSV)

    report = {"issues": []}

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Identity resolution
        assignee_email, assignee_name, assignee_id = _resolve_identity(fields.get("assignee"), user_lookup, local_map)
        reporter_email, reporter_name, reporter_id = _resolve_identity(fields.get("reporter"), user_lookup, local_map)

        # Flat "Assignee"/"Reporter" behavior
        if STRICT_EMAIL:
            assignee_flat = assignee_email
            reporter_flat = reporter_email
        else:
            assignee_flat = assignee_email if assignee_email else assignee_name
            reporter_flat = reporter_email if reporter_email else reporter_name

        # Other fields
        sprint_value = _extract_sprint_value(fields.get("customfield_10020"))
        affects_versions = [_nz(v.get("name")) for v in (fields.get("versions") or []) if isinstance(v, dict)]
        fix_versions = [_nz(v.get("name")) for v in (fields.get("fixVersions") or []) if isinstance(v, dict)]

        customers_field = fields.get("customfield_11049", [])
        customers_value = ", ".join([_nz(c) for c in customers_field]) if isinstance(customers_field, list) else _nz(customers_field)

        report["issues"].append({
            "key": _nz(issue.get("key")),
            "summary": _nz(fields.get("summary")),
            "IssueType": _nz((fields.get("issuetype") or {}).get("name")),
            "Status": _nz((fields.get("status") or {}).get("name")),
            "Priority": _nz((fields.get("priority") or {}).get("name")),

            # Flat fields (for compatibility with your original shape)
            "Assignee": assignee_flat,
            "Reporter": reporter_flat,

            # Detailed identity objects (for transparency & downstream use)
            "AssigneeDetails": {
                "email": assignee_email,   # "" if Jira hides and no local mapping
                "name": assignee_name,
                "accountId": assignee_id
            },
            "ReporterDetails": {
                "email": reporter_email,   # "" if Jira hides and no local mapping
                "name": reporter_name,
                "accountId": reporter_id
            },

            "EpicLink": _nz(fields.get("customfield_10014")),
            "Created": _safe_date(fields.get("created")),
            "Resolved": _safe_date(fields.get("resolutiondate")),
            "Sprint": sprint_value,
            "AffectsVersions": affects_versions,
            "FixVersions": fix_versions,
            "Customers": customers_value,
            "ScrumTeams": _nz((fields.get("customfield_11034") or {}).get("value")),
            "Teams": _nz((fields.get("customfield_10001") or {}).get("name")),
            "RootCause": _nz((fields.get("customfield_11067") or {}).get("value")),
            "BugMaturity": _nz(fields.get("customfield_11062")),
            "ReleasePackage": _nz(fields.get("customfield_11055"))
        })

    return json.dumps(report, indent=2)

# =======================
# Main
# =======================

def main():
    issues = fetch_all_issues()
    output = format_report(issues)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Report generated: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
