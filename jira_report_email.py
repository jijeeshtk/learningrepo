#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jira report → email via Google Workspace SMTP relay (STARTTLS with optional auth)

ENVIRONMENT VARIABLES
---------------------
# Jira
JIRA_URL           (e.g., https://yourdomain.atlassian.net)
JIRA_USER          (Atlassian account email)
JIRA_TOKEN         (API token from id.atlassian.com)
JIRA_JQL           (raw JQL; do NOT pre-encode; example below)
JIRA_MAX_RESULTS   (optional; default 50; page size for tokenized pagination)

# Email (content)
SEND_EMAIL         (true/false; default true)
MAIL_FROM          (e.g., noreply@yourdomain.com)
MAIL_TO            (comma-separated list)
MAIL_SUBJECT
MAIL_REPLY_TO      (optional)

# SMTP relay (Google)
SMTP_HOST          (default: smtp-relay.gmail.com)
SMTP_PORT          (default: 587)
SMTP_STARTTLS      (true/false; default true)

# Authentication mode:
# 1) Recommended for GitHub-hosted runners: SMTP auth ON (user + app password)
# 2) For static-IP/self-hosted runners: SMTP auth OFF + Google IP allowlist
SMTP_REQUIRE_AUTH  (true/false; default false)
SMTP_USER          (Workspace user email; required if REQUIRE_AUTH=true)
SMTP_PASS          (App Password; required if REQUIRE_AUTH=true)
"""

import os
import json
import ssl
import time
import smtplib
from email.message import EmailMessage
from datetime import datetime
from typing import Dict, List, Set, Tuple

import requests


# =======================
# Jira & Search Config
# =======================

JIRA_URL = os.getenv("JIRA_URL", "https://atos-global.atlassian.net")
JIRA_USER = os.getenv("JIRA_USER")        # Atlassian account email
JIRA_TOKEN = os.getenv("JIRA_TOKEN")      # API token from id.atlassian.com

# RAW JQL (do NOT pre-encode; requests will encode once)
# NOTE: Ensure '>=' is NOT HTML-escaped.
JQL = os.getenv(
    "JIRA_JQL",
    "project = VCS AND type IN (Bug, Defect) AND updated >= -6h"
)

FIELDS = [
    "summary", "issuetype", "status", "priority", "assignee", "reporter",
    "customfield_10014", "created", "resolutiondate", "customfield_10020",
    "versions", "fixVersions", "customfield_11049", "customfield_11034",
    "customfield_10001", "customfield_11067", "customfield_11062",
    "customfield_11055"
]

PAGE_SIZE = int(os.getenv("JIRA_MAX_RESULTS", "50"))
HTTP_TIMEOUT = (10, 60)  # (connect, read) seconds


# =======================
# Email Config (Google SMTP relay)
# =======================

SEND_EMAIL = os.getenv("SEND_EMAIL", "true").lower() in ("true", "1", "yes")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() in ("true", "1", "yes")

SMTP_REQUIRE_AUTH = os.getenv("SMTP_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

MAIL_FROM = os.getenv("MAIL_FROM", "noreply@atos.net")
MAIL_TO = os.getenv("MAIL_TO", "jijeesh.valappil@atos.net")
MAIL_SUBJECT = os.getenv("MAIL_SUBJECT", "[Jira] Bug/Defect report (last 6h)")
MAIL_REPLY_TO = os.getenv("MAIL_REPLY_TO", "")


# =======================
# Helpers
# =======================

def _nz(value, default: str = "") -> str:
    return default if (value is None or value == "") else value

def _to_string(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)

def _safe_date(value: str) -> str:
    if not value:
        return ""
    fmts = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except Exception:
            pass
    return _to_string(value)

def _extract_sprint_name(sprint_data) -> str:
    if isinstance(sprint_data, list):
        return ", ".join([_nz(s.get("name")) for s in sprint_data if isinstance(s, dict)])
    if isinstance(sprint_data, dict):
        return _nz(sprint_data.get("name"))
    return ""


# =======================
# Jira Calls
# =======================

def _jira_auth_headers() -> Tuple[Tuple[str, str], Dict[str, str]]:
    if not JIRA_USER or not JIRA_TOKEN:
        raise SystemExit("JIRA_USER or JIRA_TOKEN not set in environment.")
    return (JIRA_USER, JIRA_TOKEN), {"Accept": "application/json"}

def fetch_all_issues() -> List[dict]:
    """
    Uses GET /rest/api/3/search/jql with token pagination (nextPageToken).
    Provide raw JQL in params; 'requests' URL-encodes exactly once.
    """
    auth, headers = _jira_auth_headers()
    url = f"{JIRA_URL}/rest/api/3/search/jql"

    issues: List[dict] = []
    next_token = None

    while True:
        params = {
            "jql": JQL,
            "maxResults": str(PAGE_SIZE),
            "fields": ",".join(FIELDS),
        }
        if next_token:
            params["nextPageToken"] = next_token

        resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=HTTP_TIMEOUT)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            print("Search API (GET /search/jql) failed.")
            print("Status:", resp.status_code)
            print("URL:", resp.url)
            print("Response:", resp.text[:2000])
            raise

        data = resp.json() or {}
        page_issues = data.get("issues", [])
        issues.extend(page_issues)

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return issues

def fetch_user_emails_bulk(account_ids: Set[str]) -> Dict[str, Dict[str, str]]:
    """
    Resolve emails via /rest/api/3/user/bulk.
    NOTE: emailAddress appears only if org privacy allows it for the caller.
    Returns: {accountId: {"email": <or "">, "name": <displayName or "">}}
    """
    if not account_ids:
        return {}

    auth, headers = _jira_auth_headers()
    url = f"{JIRA_URL}/rest/api/3/user/bulk"

    params = [("accountId", aid) for aid in sorted(account_ids)]
    resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=HTTP_TIMEOUT)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print("Bulk user API failed.")
        print("Status:", resp.status_code)
        print("URL:", resp.url)
        print("Response:", resp.text[:2000])
        raise

    data = resp.json() or {}
    out: Dict[str, Dict[str, str]] = {}
    for u in data.get("values", []):
        aid = u.get("accountId")
        if not aid:
            continue
        out[aid] = {
            "email": u.get("emailAddress") or "",
            "name": u.get("displayName") or "",
        }
    return out


# =======================
# Report building
# =======================

def build_json_report(issues: List[dict]) -> str:
    # Collect accountIds for assignee & reporter
    account_ids: Set[str] = set()
    for issue in issues:
        f = issue.get("fields", {}) or {}
        a, r = f.get("assignee"), f.get("reporter")
        if isinstance(a, dict) and a.get("accountId"):
            account_ids.add(a["accountId"])
        if isinstance(r, dict) and r.get("accountId"):
            account_ids.add(r["accountId"])

    user_lookup = fetch_user_emails_bulk(account_ids)

    payload = {"issues": []}
    for issue in issues:
        f = issue.get("fields", {}) or {}

        sprint_value = _extract_sprint_name(f.get("customfield_10020"))

        # Assignee
        a = f.get("assignee")
        assignee_email, assignee_name = "", ""
        if isinstance(a, dict):
            aid = a.get("accountId")
            assignee_name = _nz(a.get("displayName"))
            if aid and aid in user_lookup:
                assignee_email = _nz(user_lookup[aid].get("email"))
        assignee_value = assignee_email if assignee_email else assignee_name

        # Reporter
        r = f.get("reporter")
        reporter_email, reporter_name = "", ""
        if isinstance(r, dict):
            rid = r.get("accountId")
            reporter_name = _nz(r.get("displayName"))
            if rid and rid in user_lookup:
                reporter_email = _nz(user_lookup[rid].get("email"))
        reporter_value = reporter_email if reporter_email else reporter_name

        affects_versions = [_nz(v.get("name")) for v in (f.get("versions") or []) if isinstance(v, dict)]
        fix_versions = [_nz(v.get("name")) for v in (f.get("fixVersions") or []) if isinstance(v, dict)]

        customers_field = f.get("customfield_11049", [])
        customers_value = ", ".join([_nz(c) for c in customers_field]) if isinstance(customers_field, list) else _nz(customers_field)

        payload["issues"].append({
            "key": _nz(issue.get("key")),
            "summary": _nz(f.get("summary")),
            "IssueType": _nz((f.get("issuetype") or {}).get("name")),
            "Status": _nz((f.get("status") or {}).get("name")),
            "Priority": _nz((f.get("priority") or {}).get("name")),

            # Prefer email; fallback to display name
            "Assignee": assignee_value,
            "Reporter": reporter_value,

            "EpicLink": _nz(f.get("customfield_10014")),
            "Created": _safe_date(f.get("created")),
            "Resolved": _safe_date(f.get("resolutiondate")),
            "Sprint": sprint_value,
            "AffectsVersions": affects_versions,
            "FixVersions": fix_versions,
            "Customers": customers_value,
            "ScrumTeams": _nz((f.get("customfield_11034") or {}).get("value")),
            "Teams": _nz((f.get("customfield_10001") or {}).get("name")),
            "RootCause": _nz((f.get("customfield_11067") or {}).get("value")),
            "BugMaturity": _to_string(f.get("customfield_11062")),  # schema-safe string
            "ReleasePackage": _nz(f.get("customfield_11055")),
        })

    return json.dumps(payload, indent=2)

def build_plaintext_body(issues_json: str) -> str:
    try:
        data = json.loads(issues_json)
    except Exception:
        data = {"issues": []}

    issues = data.get("issues", [])
    lines: List[str] = []

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"Jira Report (last 6h) - generated {now}")
    lines.append(f"JQL: {JQL}")
    lines.append(f"Total issues: {len(issues)}")
    lines.append("-" * 78)

    if not issues:
        lines.append("No issues matched the query.")
        return "\n".join(lines)

    lines.append(f"{'KEY':<12} {'STATUS':<12} {'PRIO':<8} {'ASSIGNEE/REPORTER':<40}")
    lines.append("-" * 78)

    for it in issues:
        key = it.get("key", "")
        status = it.get("Status", "")
        prio = it.get("Priority", "")
        assignee = it.get("Assignee", "")
        reporter = it.get("Reporter", "")
        summary = (it.get("summary", "") or "").replace("\n", " ").strip()
        if len(summary) > 120:
            summary = summary[:117] + "..."

        lines.append(f"{key:<12} {status:<12} {prio:<8} {assignee} / {reporter}")
        lines.append(f"  Summary: {summary}")

        sprint = it.get("Sprint", "")
        epic = it.get("EpicLink", "")
        rc = it.get("RootCause", "")
        maturity = it.get("BugMaturity", "")
        rel = it.get("ReleasePackage", "")

        extra = []
        if epic:     extra.append(f"Epic: {epic}")
        if sprint:   extra.append(f"Sprint: {sprint}")
        if rc:       extra.append(f"RootCause: {rc}")
        if maturity: extra.append(f"Maturity: {maturity}")
        if rel:      extra.append(f"Release: {rel}")
        if extra:
            lines.append("  " + " | ".join(extra))

        created = it.get("Created", "")
        resolved = it.get("Resolved", "")
        if created or resolved:
            lines.append(f"  Dates: Created={created or '-'} Resolved={resolved or '-'}")

        av = it.get("AffectsVersions", []) or []
        fv = it.get("FixVersions", []) or []
        if av or fv:
            lines.append(
                "  Versions: "
                + (f"Affects={', '.join(av)}" if av else "")
                + ("; " if av and fv else "")
                + (f"Fix={', '.join(fv)}" if fv else "")
            )

        customers = it.get("Customers", "")
        if customers:
            lines.append(f"  Customers: {customers}")

        lines.append("-" * 78)

    return "\n".join(lines)


# =======================
# Email (Google relay: STARTTLS + optional auth)
# =======================

def send_email_plaintext(subject: str, body: str, mail_from: str, mail_to_csv: str):
    if not mail_to_csv.strip():
        print("SEND_EMAIL set, but MAIL_TO not provided. Skipping email.")
        return

    recipients = [addr.strip() for addr in mail_to_csv.split(",") if addr.strip()]
    if not recipients:
        print("SEND_EMAIL set, but MAIL_TO was empty after parsing. Skipping email.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    if MAIL_REPLY_TO:
        msg["Reply-To"] = MAIL_REPLY_TO
    msg.set_content(body)  # plain text

    attempts = 0
    max_attempts = 5
    backoff = 2  # exponential backoff base

    while True:
        attempts += 1
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                if SMTP_STARTTLS:
                    context = ssl.create_default_context()
                    s.starttls(context=context)
                if SMTP_REQUIRE_AUTH:
                    if not SMTP_USER or not SMTP_PASS:
                        raise RuntimeError("SMTP_REQUIRE_AUTH=true but SMTP_USER/SMTP_PASS not set")
                    s.login(SMTP_USER, SMTP_PASS)

                s.send_message(msg)
                print(f"Email sent via {SMTP_HOST}:{SMTP_PORT} (STARTTLS={SMTP_STARTTLS}, AUTH={SMTP_REQUIRE_AUTH}).")
                return

        except smtplib.SMTPResponseException as e:
            code = e.smtp_code or 0
            err = e.smtp_error.decode() if isinstance(e.smtp_error, (bytes, bytearray)) else str(e.smtp_error)
            print(f"SMTP error {code}: {err}")
            # Retry on transient 4xx (e.g., 421/450/451/452)
            if 400 <= code < 500 and attempts < max_attempts:
                sleep_for = backoff ** attempts
                print(f"Transient error; retrying in {sleep_for}s (attempt {attempts}/{max_attempts})...")
                time.sleep(sleep_for)
                continue
            raise
        except Exception as e:
            print(f"Unexpected email send error: {e}")
            if attempts < max_attempts:
                sleep_for = backoff ** attempts
                print(f"Retrying in {sleep_for}s (attempt {attempts}/{max_attempts})...")
                time.sleep(sleep_for)
                continue
            raise


# =======================
# Main
# =======================

def main():
    # 1) Fetch from Jira
    issues = fetch_all_issues()

    # 2) Build & persist JSON
    report_json = build_json_report(issues)
    with open("jira_report.json", "w", encoding="utf-8") as f:
        f.write(report_json)
    print("Report generated: jira_report.json")

    # 3) Build plaintext mail body
    body = build_plaintext_body(report_json)
    print("\n===== Email preview (plain text) =====\n")
    print(body[:2000])

    # 4) Send via Google SMTP relay
    if SEND_EMAIL:
        send_email_plaintext(MAIL_SUBJECT, body, MAIL_FROM, MAIL_TO)
    else:
        print("SEND_EMAIL is false; skipping email send.")

if __name__ == "__main__":
    main()
