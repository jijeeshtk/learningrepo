import requests
import json
import os
from datetime import datetime

# Jira credentials and base URL
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# JQL
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -48h'

def fetch_jira_issues():
    # Correct endpoint for search
    url = f"{JIRA_URL}/rest/api/3/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    body = {
        "jql": JQL,
        "fields": [
            "summary", "issuetype", "status", "priority", "assignee", "reporter",
            "customfield_10014", "created", "resolutiondate", "customfield_10020", "versions",
            "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
            "customfield_11067", "customfield_11062", "customfield_11055"
        ],
        "maxResults": 50
    }

    resp = requests.post(url, headers=headers, auth=auth, json=body)
    resp.raise_for_status()
    return resp.json().get("issues", [])

def fetch_user_emails_bulk(account_ids):
    """
    Use Jira Cloud bulk user API to resolve emails.
    NOTE: emailAddress is returned only if site setting and permissions allow it.
    """
    if not account_ids:
        return {}

    # The bulk API allows multiple accountId query params
    # Example: /rest/api/3/user/bulk?accountId=id1&accountId=id2
    url = f"{JIRA_URL}/rest/api/3/user/bulk"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = []
    for aid in account_ids:
        params.append(("accountId", aid))

    resp = requests.get(url, headers=headers, auth=auth, params=params)
    resp.raise_for_status()
    data = resp.json() or {}

    # Build a lookup: accountId -> email (if visible), and also keep displayName as fallback
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
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except Exception:
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
                # if email not visible, fallback to name
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
    issues = fetch_jira_issues()
    output = format_report(issues)

    with open("jira_report.json", "w") as f:
        f.write(output)

    print("Report generated: jira_report.json")
