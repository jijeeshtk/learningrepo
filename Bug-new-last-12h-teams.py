import os
import json
import requests

# ====== CONFIG ======
JIRA_URL = "https://atos-global.atlassian.net"

# Pull JIRA user email from variables
JIRA_USER = os.getenv("JIRA_VCS_API_EMAIL")

# Pull JIRA API token from secrets
JIRA_TOKEN = os.getenv("JIRA_VCS_API_TOKEN")

# Pull Teams webhook from variables
TEAMS_WEBHOOK_URL = os.getenv("JIRA_VCS_BUG_OPEN_ALERT_TEAM_URL")

# Jira search endpoint (canonical)
SEARCH_URL = f"{JIRA_URL}/rest/api/3/search"

# New Bugs/Defects created in last 12 hours
JQL = 'project = VCS AND type IN (Bug, Defect) AND created >= -12h ORDER BY created DESC'

# Fields required for formatting the message
FIELDS = [
    "summary",
    "reporter",
    "priority",
    "versions",                # Affected Versions
    "customfield_11049",       # Customers (string or multi-select)
]

# ====== HELPERS ======
def nz(value, default=""):
    return default if value in (None, "") else value

def fetch_all_issues():
    """
    Query Jira GET /rest/api/3/search with pagination (startAt/maxResults).
    """
    if not JIRA_USER or not JIRA_TOKEN:
        raise RuntimeError("JIRA_VCS_API_EMAIL/JIRA_VCS_API_TOKEN not set in environment variables")

    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    issues = []
    start_at = 0
    max_results = 50

    while True:
        params = {
            "jql": JQL,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": ",".join(FIELDS),
        }

        resp = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params)
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("issues", []) or []
        issues.extend(batch)

        # End when fewer than requested returned
        if len(batch) < max_results:
            break

        start_at += max_results

    return issues

def extract_customers(fields):
    # customfield_11049 might be a string or list
    val = fields.get("customfield_11049", [])
    if isinstance(val, list):
        return ", ".join([v for v in val if v])
    return nz(val)

def extract_affected_versions(fields):
    # Format: "( <id> )  <name>"
    versions = fields.get("versions", []) or []
    formatted = []
    for v in versions:
        if isinstance(v, dict):
            vid = v.get("id")
            name = v.get("name")
            if vid and name:
                formatted.append(f"( {vid} )  {name}")
            elif name:
                formatted.append(name)
    return " ; ".join([x for x in formatted if x])

def map_priority_to_impact(priority_name: str) -> str:
    """
    Map Jira priority to Impact {High, Medium, Low}
    Expedite/Highest/High/Urgent/Critical -> High
    Medium/Normal -> Medium
    Low/Lowest/Minor/Trivial -> Low
    Fallback -> High (conservative)
    """
    if not priority_name:
        return "High"
    p = priority_name.strip().lower()
    if p in {"expedite", "highest", "high", "urgent", "critical"}:
        return "High"
    if p in {"medium", "normal"}:
        return "Medium"
    if p in {"low", "lowest", "minor", "trivial"}:
        return "Low"
    return "High"

def format_issue_message_lines(issue):
    fields = issue.get("fields", {}) or {}
    key = (issue.get("key") or "").strip()
    url = f"{JIRA_URL}/browse/{key}" if key else ""

    reporter = fields.get("reporter") or {}
    reporter_name = (reporter.get("displayName") or reporter.get("emailAddress") or "").strip()

    summary = (fields.get("summary") or "").strip()
    customers = extract_customers(fields)
    affected_versions = extract_affected_versions(fields)

    # Impact mapped from priority
    priority_name = fields.get("priority", {}).get("name") if isinstance(fields.get("priority"), dict) else ""
    impact = map_priority_to_impact(priority_name)

    # Error Message intentionally blank per requirement
    return [
        "New JIRA Bug in VCS project (within last 12 hours)",
        f"{reporter_name} created new bug: {url}",
        f"Summary: {summary}",
        f"Customer/s: {customers}",
        f"Affected Versions: {affected_versions}",
        "Error Message: ",
        f"Impact: {impact}",
    ]

def post_to_teams_card(issue_text_lines):
    """
    Sends a MessageCard to Teams with bold title and reliable line breaks.
    If webhook is not configured, prints to console instead.
    """
    if not TEAMS_WEBHOOK_URL:
        print("\n".join(issue_text_lines))
        print("\n---\n")
        return

    title = issue_text_lines[0]
    body = "<br/>".join(issue_text_lines[1:])

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "New JIRA Bug in VCS project",
        "themeColor": "E81123",  # red accent
        "sections": [
            {
                "activityTitle": f"**{title}**",
                "text": body
            }
        ]
    }

    resp = requests.post(
        TEAMS_WEBHOOK_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"}
    )
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
        lines = format_issue_message_lines(issue)
        post_to_teams_card(lines)

if __name__ == "__main__":
    main()
