import requests
import json
import os
from datetime import datetime

# Jira credentials and base URL
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# Correct Jira Search API endpoint
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search"

# JQL
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -2h'

def fetch_jira_issues():
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    body = {
        "jql": JQL,
        "fields": [
            "summary", "issuetype", "status", "priority", "assignee", "reporter",
            "customfield_10014", "created", "resolutiondate", "customfield_10020",
            "versions", "fixVersions", "customfield_11049", "customfield_11034",
            "customfield_10001", "customfield_11067", "customfield_11062",
            "customfield_11055"
        ],
        "maxResults": 50
    }

    response = requests.post(SEARCH_URL, headers=headers, auth=auth, json=body)
    response.raise_for_status()
    data = response.json()

    return data.get("issues", [])

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
    try:
        return datetime.strptime(
            value, "%Y-%m-%dT%H:%M:%S.%f%z"
        ).strftime("%m/%d/%Y")
    except Exception:
        return to_string(value)

def format_report(issues):
    report = {"issues": []}

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Sprint field
        sprint_data = fields.get("customfield_10020")
        if isinstance(sprint_data, list):
            sprint_value = ", ".join(
                nz(s.get("name")) for s in sprint_data if isinstance(s, dict)
            )
        elif isinstance(sprint_data, dict):
            sprint_value = nz(sprint_data.get("name"))
        else:
            sprint_value = ""

        # Assignee
        a = fields.get("assignee")
        assignee_value = (
            nz(a.get("emailAddress")) or nz(a.get("displayName"))
            if isinstance(a, dict)
            else ""
        )

        # Reporter
        r = fields.get("reporter")
        reporter_value = (
            nz(r.get("emailAddress")) or nz(r.get("displayName"))
            if isinstance(r, dict)
            else ""
        )

        # Versions arrays
        affects_versions = [
            nz(v.get("name")) for v in fields.get("versions", []) if isinstance(v, dict)
        ]
        fix_versions = [
            nz(v.get("name")) for v in fields.get("fixVersions", []) if isinstance(v, dict)
        ]

        # Customers
        customers_field = fields.get("customfield_11049", [])
        if isinstance(customers_field, list):
            customers_value = ", ".join(nz(c) for c in customers_field)
        else:
            customers_value = nz(customers_field)

        report["issues"].append(
            {
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
                "BugMaturity": to_string(fields.get("customfield_11062")),
                "ReleasePackage": nz(fields.get("customfield_11055")),
            }
        )

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    # Fetch + transform + print JSON (NO logs)
    issues = fetch_jira_issues()
    report = format_report(issues)

    # IMPORTANT: Print *only* the JSON
    print(report, end="")
