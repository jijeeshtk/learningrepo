import requests
import json
import os
from datetime import datetime, timezone

# Jira credentials and base URL
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

STATE_FILE = "state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def to_jql_datetime(dt: datetime) -> str:
    """
    Convert aware UTC datetime to Jira JQL datetime format: yyyy/MM/dd HH:mm
    """
    # ensure UTC
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y/%m/%d %H:%M")

def build_jql(last_run_iso: str | None) -> str:
    base = 'project = VCS AND type IN (Bug, Defect)'
    if last_run_iso:
        # Parse the stored ISO time and convert to Jira format
        dt = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
        jql_time = to_jql_datetime(dt)
        return f'{base} AND updated >= "{jql_time}"'
    else:
        # First run fallback window (no duplicates state yet)
        return f'{base} AND updated >= -48h'

def fetch_jira_issues(jql: str):
    # NOTE: If /search/jql ever returns 404 for your site, switch to /rest/api/3/search
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    body = {
        "jql": jql,
        "fields": [
            "summary", "issuetype", "status", "priority", "assignee", "reporter",
            "customfield_10014", "created", "resolutiondate", "customfield_10020", "versions",
            "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
            "customfield_11067", "customfield_11062", "customfield_11055", "updated"
        ],
        "maxResults": 100
    }

    response = requests.post(url, headers=headers, auth=auth, json=body)
    response.raise_for_status()
    return response.json().get("issues", [])

def nz(value, default=""):
    if value is None or value == "":
        return default
    return value

def to_string(value):
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)

def safe_date(value):
    if not value:
        return ""
    try:
        # Jira format like: 2026-01-30T10:12:34.123+0000
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except Exception:
        return to_string(value)

def format_report(issues):
    report = {"issues": []}

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
        assignee_value = (nz(a.get("emailAddress")) or nz(a.get("displayName"))) if isinstance(a, dict) else ""

        # Reporter
        r = fields.get("reporter")
        reporter_value = (nz(r.get("emailAddress")) or nz(r.get("displayName"))) if isinstance(r, dict) else ""

        # AffectsVersions (array)
        affects_versions = [nz(v.get("name")) for v in fields.get("versions", []) if isinstance(v, dict)]

        # FixVersions (array)
        fix_versions = [nz(v.get("name")) for v in fields.get("fixVersions", []) if isinstance(v, dict)]

        # Customers (list → comma-separated string OR passthrough if already string)
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
            "Assignee": assignee_value,
            "Reporter": reporter_value,
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
            # keep BugMaturity as string to be Power Automate–safe
            "BugMaturity": to_string(fields.get("customfield_11062")),
            "ReleasePackage": nz(fields.get("customfield_11055")),
            # (optional) include updated for debugging/traceability
            "Updated": nz(fields.get("updated"))
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    state = load_state()
    jql = build_jql(state.get("last_run"))

    issues = fetch_jira_issues(jql)
    report = format_report(issues)

    # write report
    with open("jira_report.json", "w") as f:
        f.write(report)

    # update last_run to NOW (UTC, ISO format)
    state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_state(state)

    print("Report generated: jira_report.json")
    print(f"Last run saved: {state['last_run']}")