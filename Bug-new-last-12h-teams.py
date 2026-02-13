import os
import json
import requests
from datetime import datetime

# ====== CONFIG ======
JIRA_URL = "https://atos-global.atlassian.net"
JIRA_USER = os.getenv("JIRA_USER")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

SEARCH_URL = f"{JIRA_URL}/rest/api/3/search/jql"

# New Bugs/Defects created in last 12 hours
JQL = 'project = VCS AND type IN (Bug, Defect) AND created >= -80h ORDER BY created DESC'

# Fields required for formatting the message
FIELDS = [
    "summary",
    "reporter",
    "priority",
    "versions",                # "Affected Versions"
    "description",             # For "Error Message" (fallback)
    "customfield_11049",       # Customers (string or multi-select)
]

# ====== HELPERS ======
def nz(value, default=""):
    return default if value in (None, "") else value

def to_string(value):
    if value in (None, ""):
        return ""
    return str(value)

def fetch_all_issues():
    """
    Query Jira GET /rest/api/3/search/jql (new style) with pagination using nextPageToken if present.
    """
    if not JIRA_USER or not JIRA_TOKEN:
        raise RuntimeError("JIRA_USER/JIRA_TOKEN not set in environment variables")

    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    issues = []
    next_token = None

    while True:
        params = {
            "jql": JQL,
            "maxResults": 50,
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token

        resp = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params)
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("issues", []) or []
        issues.extend(batch)

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return issues

def extract_customers(fields):
    # customfield_11049 might be a string or list
    val = fields.get("customfield_11049", [])
    if isinstance(val, list):
        return ", ".join([nz(v) for v in val if nz(v)])
    return nz(val)

def extract_affected_versions(fields):
    versions = fields.get("versions", []) or []
    names = [nz(v.get("name")) for v in versions if isinstance(v, dict)]
    return " ; ".join([v for v in names if v])

def extract_error_message(fields):
    # Use description (plain text snippet) as "Error Message"
    desc = fields.get("description")
    if isinstance(desc, dict):
        # Sometimes Jira Cloud gives structured content; flatten a minimal text if possible
        # Fallback: JSON-stringify
        try:
            return json.dumps(desc)[:500]
        except Exception:
            return ""
    elif isinstance(desc, str):
        return desc.strip()[:500]
    return ""

def format_issue_message(issue):
    fields = issue.get("fields", {}) or {}
    key = nz(issue.get("key"))
    url = f"{JIRA_URL}/browse/{key}" if key else ""

    reporter = fields.get("reporter") or {}
    reporter_name = nz(reporter.get("displayName")) or nz(reporter.get("emailAddress"))

    summary = nz(fields.get("summary"))
    customers = extract_customers(fields)
    affected_versions = extract_affected_versions(fields)
    error_message = extract_error_message(fields)
    priority = (fields.get("priority") or {}).get("name") if isinstance(fields.get("priority"), dict) else ""
    impact = nz(priority)  # Using Priority as Impact as discussed

    # Your requested format:
    lines = [
        "New JIRA Bug in VCS project (within last 12 hours)",
        f"{reporter_name} created new bug: {url}",
        f"Summary: {summary}",
        f"Customer/s: {customers}",
        f"Affected Versions: {affected_versions}",
        "Error Message: " + (error_message if error_message else ""),
        f"Impact: {impact}",
    ]
    return "\n".join(lines).strip()

def post_to_teams(text):
    if not TEAMS_WEBHOOK_URL:
        print("TEAMS_WEBHOOK_URL not set; printing message locally:\n")
        print(text)
        print("\n---\n")
        return

    payload = { "text": text }
    resp = requests.post(TEAMS_WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"})
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Teams post failed: {e}\nResponse: {resp.text}")

def main():
    issues = fetch_all_issues()
    if not issues:
        print("No new Bugs/Defects in last 12 hours. Nothing to post.")
        return

    for issue in issues:
        msg = format_issue_message(issue)
        post_to_teams(msg)

if __name__ == "__main__":
    main()
