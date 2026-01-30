def fetch_jira_issues():
    url = "https://atos-global.atlassian.net/rest/api/3/search"  # no double slash
    headers = {"Accept": "application/json"}
    auth = (JIRA_USER, JIRA_TOKEN)

    params = {
        "jql": JQL,
        "fields": ",".join([
            "summary", "issuetype", "status", "priority", "assignee", "reporter",
            "customfield_10014", "created", "resolved", "sprint", "versions",
            "fixVersions", "customfield_11049", "customfield_11034", "customfield_10001",
            "customfield_11067", "customfield_11062", "customfield_11055"
        ])
    }

    response = requests.get(url, headers=headers, params=params, auth=auth)
    print("Request URL:", response.url)        # 👈 Debug
    print("Response Code:", response.status_code)
    print("Response Body:", response.text[:500])  # 👈 Preview first 500 chars
    response.raise_for_status()
    return response.json()["issues"]
