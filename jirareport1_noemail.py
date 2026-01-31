import os
import json
from datetime import datetime
import requests

# === Config ===
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")     # Atlassian account email
JIRA_TOKEN = os.getenv("JIRA_TOKEN")   # API token from id.atlassian.com

JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -48h'  # <-- RAW JQL (DO NOT pre-encode)

FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020",
    "versions", "fixVersions", "customfield_11049", "customfield_11034",
    "customfield_10001", "customfield_11067", "customfield_11062",
    "customfield_11055"
]

MAX_RESULTS = 50  # page size per call

def _nz(value, default=""):
    return default if (value is None or value == "") else value

def _safe_date(value):
    if not value:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except Exception:
            pass
    return _nz(value)

def fetch_all_issues():
    """
    Uses GET /rest/api/3/search/jql with nextPageToken pagination.
    Provide RAW JQL in params so 'requests' URL-encodes it exactly once.
    """
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    all_issues = []
    next_token = None

    while True:
        params = {
            "jql": JQL,                       # <-- raw JQL (no urllib.parse.quote)
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

def fetch_user_emails_bulk(account_ids):
    """
    Resolve emails via /rest/api/3/user/bulk.
    NOTE: emailAddress returns only if your org/user visibility allows it.
    """
    if not account_ids:
        return {}

    url = f"{JIRA_URL}/rest/api/3/user/bulk"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = [("accountId", aid) for aid in account_ids]
    resp = requests.get(url, headers=headers, auth=auth, params=params)
    resp.raise_for_status()

    data = resp.json() or {}
    out = {}
    for u in data.get("values", []):
        out[u.get("accountId")] = {
            "email": u.get("emailAddress"),     # may be None if hidden by policy
            "name": u.get("displayName")
        }
    return out

def format_report(issues):
    # Collect accountIds for assignee + reporter
    account_ids = set()
    for issue in issues:
        f = issue.get("fields", {}) or {}
        a, r = f.get("assignee"), f.get("reporter")
        if isinstance(a, dict) and a.get("accountId"):
            account_ids.add(a["accountId"])
        if isinstance(r, dict) and r.get("accountId"):
            account_ids.add(r["accountId"])

    user_lookup = fetch_user_emails_bulk(account_ids)

    report = {"issues": []}
    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Sprint can be dict or list depending on board/app
        sprint_data = fields.get("customfield_10020")
        if isinstance(sprint_data, list):
            sprint_value = ", ".join([_nz(s.get("name")) for s in sprint_data if isinstance(s, dict)])
        elif isinstance(sprint_data, dict):
            sprint_value = _nz(sprint_data.get("name"))
        else:
            sprint_value = ""

        # Assignee
        a = fields.get("assignee")
        assignee_email, assignee_name = "", ""
        if isinstance(a, dict):
            aid = a.get("accountId")
            assignee_name = _nz(a.get("displayName"))
            if aid and aid in user_lookup:
                assignee_email = _nz(user_lookup[aid].get("email"))
        assignee_value = assignee_email if assignee_email else assignee_name

        # Reporter
        r = fields.get("reporter")
        reporter_email, reporter_name = "", ""
        if isinstance(r, dict):
            rid = r.get("accountId")
            reporter_name = _nz(r.get("displayName"))
            if rid and rid in user_lookup:
                reporter_email = _nz(user_lookup[rid].get("email"))
        reporter_value = reporter_email if reporter_email else reporter_name

        affects_versions = [_nz(v.get("name")) for v in (fields.get("versions") or []) if isinstance(v, dict)]
        fix_versions     = [_nz(v.get("name")) for v in (fields.get("fixVersions") or []) if isinstance(v, dict)]

        customers_field = fields.get("customfield_11049", [])
        customers_value = ", ".join([_nz(c) for c in customers_field]) if isinstance(customers_field, list) else _nz(customers_field)

        report["issues"].append({
            "key": _nz(issue.get("key")),
            "summary": _nz(fields.get("summary")),
            "IssueType": _nz((fields.get("issuetype") or {}).get("name")),
            "Status": _nz((fields.get("status") or {}).get("name")),
            "Priority": _nz((fields.get("priority") or {}).get("name")),
            "Assignee": assignee_value,     # email if visible; else name
            "Reporter": reporter_value,     # email if visible; else name
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
            "ReleasePackage": _nz(fields.get("customfield_11055")),
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    if not JIRA_USER or not JIRA_TOKEN:
        raise SystemExit("JIRA_USER or JIRA_TOKEN not set.")
    issues = fetch_all_issues()
    output = format_report(issues)
    with open("jira_report.json", "w") as f:
        f.write(output)
    print("Report generated: jira_report.json")
