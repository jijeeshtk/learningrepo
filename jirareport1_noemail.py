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
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y/%m/%d %H:%M")

def build_jql(last_run_iso: str | None) -> str:
    base = 'project = VCS AND type IN (Bug, Defect)'
    if last_run_iso:
        # Parse the stored ISO time and convert to Jira format
        dt = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
        jql_time = to_jql_datetime(dt)
        # IMPORTANT: use >= (not HTML-escaped)
        return f'{base} AND updated >= "{jql_time}"'
    else:
        # First run fallback window (no duplicates state yet)
        return f'{base} AND updated >= -48h'

def fetch_jira_issues(jql: str):
    """
    NOTE: If /search/jql behaves unexpectedly for your site, switch to: f"{JIRA_URL}/rest/api/3/search"
    """
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

# -------- Email resolution helpers --------

def fetch_user_email_by_account_id(account_id: str) -> str:
    """
    Resolve a user's email via the user API using accountId.
    Returns "" if not accessible.
    """
    if not account_id:
        return ""
    url = f"{JIRA_URL}/rest/api/3/user"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)
    params = {"accountId": account_id}

    try:
        resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=20)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        return data.get("emailAddress") or ""
    except Exception:
        return ""

def resolve_user_email(user_obj: dict) -> str:
    """
    Prefer emailAddress from the issue's user object.
    If missing (common due to Jira Cloud privacy), fallback to user lookup by accountId.
    Output is always an email or "" (no display name, no accountId in output).
    """
    if not isinstance(user_obj, dict):
        return ""
    # 1) Try direct email from fields (if your org exposes it)
    email = user_obj.get("emailAddress")
    if email:
        return email
    # 2) Fallback to user lookup by accountId (internal only, not exposed in output)
    account_id = user_obj.get("accountId")
    return fetch_user_email_by_account_id(account_id)

# ------------------------------------------

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

        # Assignee — output email only
        assignee_email = resolve_user_email(fields.get("assignee"))

        # Reporter — output email only
        reporter_email = resolve_user_email(fields.get("reporter"))

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
            "Assignee": assignee_email,     # email only
            "Reporter": reporter_email,     # email only

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
