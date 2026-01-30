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
            "customfield_10014", "created", "resolved", "sprint", "versions",
            "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
            "customfield_11067", "customfield_11062", "customfield_11055"
        ],
        "maxResults": 50
    }

    response = requests.post(url, headers=headers, auth=auth, json=body)
    response.raise_for_status()
    return response.json().get("issues", [])

def safe_date(value):
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except Exception:
        return value

def format_report(issues):
    report = {"issues": []}
    for issue in issues:
        fields = issue.get("fields", {})
        report["issues"].append({
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "IssueType": fields.get("issuetype", {}).get("name", ""),
            "Status": fields.get("status", {}).get("name", ""),
            "Priority": fields.get("priority", {}).get("name", ""),
            "Assignee": fields.get("assignee", {}).get("emailAddress", "") if fields.get("assignee") else "",
            "Reporter": fields.get("reporter", {}).get("emailAddress", "") if fields.get("reporter") else "",
            "EpicLink": fields.get("customfield_10014", ""),
            "Created": safe_date(fields.get("created")),
            "Resolved": safe_date(fields.get("resolved")),
            "Sprint": fields.get("sprint", {}).get("name", "") if fields.get("sprint") else "",
            "AffectsVersions": [v.get("name", "") for v in fields.get("versions", [])],
            "FixVersions": [v.get("name", "") for v in fields.get("fixVersions", [])],
            "Customers": fields.get("customfield_11049", ""),
            "ScrumTeams": fields.get("customfield_11034", {}).get("value", "") if fields.get("customfield_11034") else "",
            "Teams": fields.get("customfield_10001", {}).get("name", "") if fields.get("customfield_10001") else "",
            "RootCause": fields.get("customfield_11067", {}).get("value", "") if fields.get("customfield_11067") else "",
            "BugMaturity": fields.get("customfield_11062", ""),
            "ReleasePackage": fields.get("customfield_11055", "")
        })
    return json.dumps(report, indent=2)

if __name__ == "__main__":
    issues = fetch_jira_issues()
    report = format_report(issues)

    with open("jira_report.json", "w") as f:
        f.write(report)

    print("Report generated: jira_report.json")
