import requests
import json
import os
from datetime import datetime

# Jira credentials and base URL
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# JQL query
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -12h'

def fetch_jira_issues():
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
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

    response = requests.post(url, headers=headers, auth=auth, json=body)
    response.raise_for_status()
    return response.json().get("issues", [])

# Normalizes None → empty string
def nz(value, default=""):
    if value is None or value == "":
        return default
    return value

# Convert Jira datetime to mm/dd/yyyy or ""
def safe_date(value):
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except Exception:
        return nz(value)

def format_report(issues):
    report = {"issues": []}

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Sprint field handling
        sprint_data = fields.get("customfield_10020")
        if isinstance(sprint_data, list):
            sprint_value = ", ".join(
                [nz(s.get("name", "")) for s in sprint_data if isinstance(s, dict)]
            )
        elif isinstance(sprint_data, dict):
            sprint_value = nz(sprint_data.get("name"))
        else:
            sprint_value = ""

        # Assignee
        assignee = fields.get("assignee")
        if isinstance(assignee, dict):
            assignee_value = (
                nz(assignee.get("emailAddress")) or nz(assignee.get("displayName"))
            )
        else:
            assignee_value = ""

        # Reporter
        reporter = fields.get("reporter")
        if isinstance(reporter, dict):
            reporter_value = (
                nz(reporter.get("emailAddress")) or nz(reporter.get("displayName"))
            )
        else:
            reporter_value = ""

        # Versions lists
        affects_versions = [
            nz(v.get("name", "")) for v in fields.get("versions", []) if isinstance(v, dict)
        ]

        fix_versions = [
            nz(v.get("name", "")) for v in fields.get("fixVersions", []) if isinstance(v, dict)
        ]

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
            "Sprint": nz(sprint_value),
            "AffectsVersions": affects_versions,
            "FixVersions": fix_versions,
            "Customers": nz(fields.get("customfield_11049")),
            "ScrumTeams": nz((fields.get("customfield_11034") or {}).get("value")),
            "Teams": nz((fields.get("customfield_10001") or {}).get("name")),
            "RootCause": nz((fields.get("customfield_11067") or {}).get("value")),
            "BugMaturity": nz(fields.get("customfield_11062")),
            "ReleasePackage": nz(fields.get("customfield_11055"))
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    issues = fetch_jira_issues()
    report = format_report(issues)

    with open("jira_report.json", "w") as f:
        f.write(report)

    print("Report generated: jira_report.json")
