import requests
import json
import os
from datetime import datetime
from urllib.parse import quote

# Jira credentials (from GitHub Secrets)
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_VCS_API_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_VCS_API_TOKEN")

SEARCH_URL = f"{JIRA_URL}/rest/api/3/search/jql"  # New endpoint

# IMPORTANT: Plain JQL (no HTML entities)
JQL = 'project = VCS AND type IN (Bug, Defect) AND updated >= -48h'

# The fields you want back (same as before)
FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020",
    "versions", "fixVersions", "customfield_11049", "customfield_11034",
    "customfield_10001", "customfield_11067", "customfield_11062",
    "customfield_11055"
]

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
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%m/%d/%Y")
    except Exception:
        return to_string(value)

def fetch_all_issues():
    """
    Uses GET /rest/api/3/search/jql with URL-encoded JQL.
    Handles pagination via nextPageToken (new API behavior).
    """
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    # Encode JQL for use in the URL (as Atlassian recommends)
    # Example of documented usage:
    #   .../rest/api/3/search/jql?maxResults=10000&jql%3Dproject%3DOP%20and%20created%20%3E%3D%20-7d
    # (We’ll just use a normal 'jql=' param; requests will encode it) [2](https://confluence.atlassian.com/jirakb/run-jql-search-query-using-jira-cloud-rest-api-1289424308.html)
    issues = []
    next_token = None

    while True:
        params = {
            "jql": JQL,
            "maxResults": 50,
            # You can request all fields via "*all", but it’s heavier.
            # Supplying a comma-joined list is more efficient.
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token  # new pagination token [2](https://confluence.atlassian.com/jirakb/run-jql-search-query-using-jira-cloud-rest-api-1289424308.html)[3](https://docs.adaptavist.com/sr4jc/latest/release-notes/breaking-changes/atlassian-rest-api-search-endpoints-deprecation)

        resp = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params)
        # If you hit 400 again, uncomment the next two lines temporarily to see the server message:
        # print(resp.status_code, file=sys.stderr)
        # print(resp.text, file=sys.stderr)
        resp.raise_for_status()

        data = resp.json()

        # New response style: you still get "issues" plus a "nextPageToken"
        # (Atlassian KB & migration notes call this out) [2](https://confluence.atlassian.com/jirakb/run-jql-search-query-using-jira-cloud-rest-api-1289424308.html)[3](https://docs.adaptavist.com/sr4jc/latest/release-notes/breaking-changes/atlassian-rest-api-search-endpoints-deprecation)
        batch = data.get("issues", [])
        issues.extend(batch)

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return issues

def format_report(issues):
    report = {"issues": []}

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        # Sprint (customfield_10020)
        sprint_data = fields.get("customfield_10020")
        if isinstance(sprint_data, list):
            sprint_value = ", ".join(
                nz(s.get("name")) for s in sprint_data if isinstance(s, dict)
            )
        elif isinstance(sprint_data, dict):
            sprint_value = nz(sprint_data.get("name"))
        else:
            sprint_value = ""

        # Assignee / Reporter
        a = fields.get("assignee")
        assignee_value = (
            nz(a.get("emailAddress")) or nz(a.get("displayName"))
            if isinstance(a, dict) else ""
        )
        r = fields.get("reporter")
        reporter_value = (
            nz(r.get("emailAddress")) or nz(r.get("displayName"))
            if isinstance(r, dict) else ""
        )

        # Versions arrays
        affects_versions = [nz(v.get("name")) for v in fields.get("versions", []) if isinstance(v, dict)]
        fix_versions = [nz(v.get("name")) for v in fields.get("fixVersions", []) if isinstance(v, dict)]

        # Customers (string or list)
        customers_field = fields.get("customfield_11049", [])
        if isinstance(customers_field, list):
            customers_value = ", ".join(nz(c) for c in customers_field)
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
            "BugMaturity": to_string(fields.get("customfield_11062")),
            "ReleasePackage": nz(fields.get("customfield_11055")),
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    issues = fetch_all_issues()
    report = format_report(issues)
    print(report, end="")
