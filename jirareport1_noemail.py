import requests
import json
import os
from datetime import datetime

# Jira credentials and base URL
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")  # must be the Atlassian account email for basic auth
JIRA_TOKEN = os.getenv("JIRA_TOKEN")  # API token generated from id.atlassian.com

# JQL
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -48h'

FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020", "versions",
    "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
    "customfield_11067", "customfield_11062", "customfield_11055"
]

def _search_get(jql: str, fields: list, max_results: int = 50, start_at: int = 0):
    """
    Preferred: GET /rest/api/3/search with query params.
    """
    url = f"{JIRA_URL}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = {
        "jql": jql,
        "maxResults": max_results,
        "startAt": start_at,
        # fields can be comma-separated
        "fields": ",".join(fields),
    }

    resp = requests.get(url, headers=headers, auth=auth, params=params)
    return resp

def _search_post(jql: str, fields: list, max_results: int = 50, start_at: int = 0):
    """
    Fallback: POST /rest/api/3/search with JSON body.
    """
    url = f"{JIRA_URL}/rest/api/3/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    body = {
        "jql": jql,
        "fields": fields,
        "maxResults": max_results,
        "startAt": start_at,
    }

    resp = requests.post(url, headers=headers, auth=auth, json=body)
    return resp

def fetch_jira_issues(max_results=50):
    """
    Fetches issues using GET first; if certain status codes (410/405) occur,
    falls back to POST automatically.
    Also supports pagination if needed.
    """
    all_issues = []
    start_at = 0

    while True:
        # Try GET first
        resp = _search_get(JQL, FIELDS, max_results=max_results, start_at=start_at)
        if resp.status_code in (410, 405, 404):  # some sites disallow GET/route
            # Try POST fallback
            resp = _search_post(JQL, FIELDS, max_results=max_results, start_at=start_at)

        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            # Print server response for diagnostics and re-raise
            print("Search API call failed.")
            print("Status:", resp.status_code)
            print("URL:", resp.url)
            try:
                print("Response:", resp.text[:2000])
            except Exception:
                pass
            raise

        data = resp.json() or {}
        issues = data.get("issues", [])
        all_issues.extend(issues)

        total = data.get("total", len(all_issues))
        start_at += len(issues)
        if start_at >= total or not issues:
            break

    return all_issues

def fetch_user_emails_bulk(account_ids):
    """
    Use Jira Cloud bulk user API to resolve emails.
    NOTE: emailAddress is returned only if site setting and permissions allow it.
    """
    if not account_ids:
        return {}

    url = f"{JIRA_URL}/rest/api/3/user/bulk"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = [("accountId", aid) for aid in account_ids]

    resp = requests.get(url, headers=headers, auth=auth, params=params)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print("Bulk user API failed.")
        print("Status:", resp.status_code)
        print("URL:", resp.url)
        try:
            print("Response:", resp.text[:2000])
        except Exception:
            pass
        raise

    data = resp.json() or {}
    lookup = {}
    for u in data.get("values", []):
        account_id = u.get("accountId")
        email = u.get("emailAddress")  # may be missing if not visible
        display_name = u.get("displayName")
        lookup[account_id] = {"email": email, "name": display_name}
    return lookup

def nz(value, default=""):
    if value is None or value == "":
        return default
    return value

def safe_date(value):
    if not value:
        return ""
    # Jira Cloud usually returns ISO 8601 with timezone, e.g. 2026-01-22T11:25:43.123+0000
    fmts = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except Exception:
            continue
    return nz(value)

def format_report(issues):
    report = {"issues": []}

    # Gather all assignee and reporter accountIds to resolve emails in one shot
    account_ids = set()
    for issue in issues:
        f = issue.get("fields", {}) or {}
        a = f.get("assignee")
        r = f.get("reporter")
        if isinstance(a, dict) and a.get("accountId"):
            account_ids.add(a["accountId"])
        if isinstance(r, dict) and r.get("accountId"):
            account_ids.add(r["accountId"])

    # Resolve emails via bulk API
    user_lookup = fetch_user_emails_bulk(account_ids)

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Sprint handling
        sprint_data = fields.get("customfield_10020")
        if isinstance(sprint_data, list):
            sprint_value = ", ".join([nz(s.get("name")) for s in sprint_data if isinstance(s, dict)])
        elif isinstance(sprint_data, dict):
            sprint_value = nz(sprint_data.get("name"))
        else:
            sprint_value = ""

        # Assignee
        a = fields.get("assignee")
        assignee_email = ""
        assignee_name = ""
        if isinstance(a, dict):
            aid = a.get("accountId")
            assignee_name = nz(a.get("displayName"))
            if aid and aid in user_lookup:
                assignee_email = nz(user_lookup[aid].get("email"))
        assignee_value = assignee_email if assignee_email else assignee_name

        # Reporter
        r = fields.get("reporter")
        reporter_email = ""
        reporter_name = ""
        if isinstance(r, dict):
            rid = r.get("accountId")
            reporter_name = nz(r.get("displayName"))
            if rid and rid in user_lookup:
                reporter_email = nz(user_lookup[rid].get("email"))
        reporter_value = reporter_email if reporter_email else reporter_name

        # AffectsVersions (array)
        affects_versions = [
            nz(v.get("name")) for v in (fields.get("versions") or []) if isinstance(v, dict)
        ]

        # FixVersions (array)
        fix_versions = [
            nz(v.get("name")) for v in (fields.get("fixVersions") or []) if isinstance(v, dict)
        ]

        # Customers (list → comma-separated string)
        customers_field = fields.get("customfield_11049", [])
        if isinstance(customers_field, list):
            customers_value = ", ".join([nz(c) for c in customers_field])
        else:
            customers_value = nz(customers_field)

        report["issues"].append({
            "key": nz(issue.get("key")),
            "summary": nz(fields.get("summary")),
            "IssueType": nz((fields.get("issuetype") or {}).get("name")),
            "Status": nz((fields.get("status") or {}).get("name")),
            "Priority": nz((fields.get("priority") or {}).get("name")),
            "Assignee": assignee_value,  # email if available; else name
            "Reporter": reporter_value,  # email if available; else name
            "EpicLink": nz(fields.get("customfield_10014")),
            "Created": safe_date(fields.get("created")),
            "Resolved": safe_date(fields.get("resolutiondate")),
            "Sprint": sprint_value,
            "AffectsVersions": affects_versions,
            "FixVersions": fix_versions,
            "Customers": customers_value,
            "ScrumTeams": nz((fields.get("customfield_11034") or {}).get("value")),
            "Teams": nz((fields.get("customfield_10001") or {}).get("name")),
            "RootCause": nz((fields.get("customfield_11067") or {}).get("value")),
            "BugMaturity": nz(fields.get("customfield_11062")),
            "ReleasePackage": nz(fields.get("customfield_11055"))
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    # Basic env validation
    if not JIRA_USER or not JIRA_TOKEN:
        raise SystemExit("JIRA_USER or JIRA_TOKEN not set in environment.")
    # Jira Cloud requires JIRA_USER to be your Atlassian account email
    issues = fetch_jira_issues()
    output = format_report(issues)

    with open("jira_report.json", "w") as f:
        f.write(output)

    print("Report generated: jira_report.json")
