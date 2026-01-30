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
    url = f"{JIRA_URL}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = {
        "jql": JQL,
        "fields": [
            "summary", "issuetype", "status", "priority", "assignee", "reporter",
            "customfield_10014", "created", "resolved", "sprint", "versions",
            "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
            "customfield_11067", "customfield_11062", "customfield_11055"
        ]
    }

    response = requests.get(url, headers=headers, params=params, auth=auth)
    response.raise_for_status()
    return response.json()["issues"]

def format_report(issues):
    report = {"issues": []}
    for issue in issues:
        fields = issue["fields"]
        report["issues"].append({
            "key": issue["key"],
            "summary": fields.get("summary"),
            "IssueType": fields["issuetype"]["name"] if fields.get("issuetype") else None,
            "Status": fields["status"]["name"] if fields.get("status") else None,
            "Priority": fields["priority"]["name"] if fields.get("priority") else None,
            "Assignee": fields["assignee"]["emailAddress"] if fields.get("assignee") else None,
            "Reporter": fields["reporter"]["emailAddress"] if fields.get("reporter") else None,
            "EpicLink": fields.get("customfield_10014"),
            "Created": datetime.strptime(fields["created"], "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y") if fields.get("created") else None,
            "Resolved": datetime.strptime(fields["resolved"], "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y") if fields.get("resolved") else None,
            "Sprint": fields.get("sprint", {}).get("name") if fields.get("sprint") else None,
            "AffectsVersions": [v["name"] for v in fields.get("versions", [])],
            "FixVersions": [v["name"] for v in fields.get("fixVersions", [])],
            "Customers": fields.get("customfield_11049"),
            "ScrumTeams": fields.get("customfield_11034", {}).get("value") if fields.get("customfield_11034") else None,
            "Teams": fields.get("customfield_10001", {}).get("name") if fields.get("customfield_10001") else None,
            "RootCause": fields.get("customfield_11067", {}).get("value") if fields.get("customfield_11067") else None,
            "BugMaturity": fields.get("customfield_11062"),
            "ReleasePackage": fields.get("customfield_11055")
        })
    return json.dumps(report, indent=2)

if __name__ == "__main__":
    issues = fetch_jira_issues()
    report = format_report(issues)

    # Save to file so GitHub can upload it
    with open("jira_report.json", "w") as f:
        f.write(report)

    print("Report generated: jira_report.json")

