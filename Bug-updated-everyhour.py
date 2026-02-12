import requests
import json
import os
from datetime import datetime

# Jira credentials (from GitHub Secrets)
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# New Jira Search API (mandatory after 2025)
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search/jql"

# Correct JQL (no HTML entities)
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -2h'

def nz(v, d=""):
    return d if v in (None, "") else v

def to_string(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)

def safe_date(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except:
        return to_string(v)

def fetch_jira_issues():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_USER, JIRA_TOKEN)

    # NEW Jira API body structure
    body = {
        "queries": [
            {
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
        ]
    }

    response = requests.post(SEARCH_URL, headers=headers, auth=auth, json=body)
    response.raise_for_status()

    data = response.json()

    # NEW structure: results sit inside queries[0].results.issues
    return data["queries"][0]["results"]["issues"]

def format_report(issues):
    report = {"issues": []}

    for issue in issues:
        f = issue.get("fields", {})

        # Sprint
        s = f.get("customfield_10020")
        if isinstance(s, list):
            sprint_value = ", ".join(nz(x.get("name")) for x in s)
        elif isinstance(s, dict):
            sprint_value = nz(s.get("name"))
        else:
            sprint_value = ""

        # Assignee
        a = f.get("assignee")
        assignee_value = (
            nz(a.get("emailAddress")) or nz(a.get("displayName"))
            if isinstance(a, dict) else ""
        )

        # Reporter
        r = f.get("reporter")
        reporter_value = (
            nz(r.get("emailAddress")) or nz(r.get("displayName"))
            if isinstance(r, dict) else ""
        )

        # Versions
        affects_versions = [nz(v.get("name")) for v in f.get("versions", [])]
        fix_versions = [nz(v.get("name")) for v in f.get("fixVersions", [])]

        # Customers
        customers = f.get("customfield_11049", [])
        if isinstance(customers, list):
            customers_value = ", ".join(nz(c) for c in customers)
        else:
            customers_value = nz(customers)

        report["issues"].append({
            "key": nz(issue.get("key")),
            "summary": nz(f.get("summary")),
            "IssueType": nz((f.get("issuetype") or {}).get("name")),
            "Status": nz((f.get("status") or {}).get("name")),
            "Priority": nz((f.get("priority") or {}).get("name")),
            "Assignee": assignee_value,
            "Reporter": reporter_value,
            "EpicLink": nz(f.get("customfield_10014")),
            "Created": safe_date(f.get("created")),
            "Resolved": safe_date(f.get("resolutiondate")),
            "Sprint": sprint_value,
            "AffectsVersions": affects_versions,
            "FixVersions": fix_versions,
            "Customers": customers_value,
            "ScrumTeams": nz((f.get("customfield_11034") or {}).get("value")),
            "Teams": nz((f.get("customfield_10001") or {}).get("name")),
            "RootCause": nz((f.get("customfield_11067") or {}).get("value")),
            "BugMaturity": to_string(f.get("customfield_11062")),
            "ReleasePackage": nz(f.get("customfield_11055")),
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    issues = fetch_jira_issues()
    report = format_report(issues)
    print(report, end="")
