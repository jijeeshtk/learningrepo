{
  "type": "object",
  "properties": {
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": true,
        "properties": {
          "key": { "type": "string" },
          "summary": { "type": "string" },
          "IssueType": { "type": "string" },
          "Status": { "type": "string" },
          "Priority": { "type": "string" },
          "Assignee": { "type": "string" },
          "Reporter": { "type": "string" },
          "EpicLink": { "type": "string" },
          "Created": { "type": "string" },
          "Resolved": { "type": "string" },
          "Sprint": { "type": "string" },
          "AffectsVersions": {
            "type": "array",
            "items": { "type": "string" }
          },
          "FixVersions": {
            "type": "array",
            "items": { "type": "string" }
          },
          "Customers": {
            "type": "array",
            "items": { "type": "string" }
          },
          "ScrumTeams": { "type": "string" },
          "Teams": { "type": "string" },
          "RootCause": { "type": "string" },
          "BugMaturity": { "type": ["number", "string", "null"] },
          "ReleasePackage": { "type": "string" }
        },
        "required": ["key", "summary"]
      }
    }
  },
  "required": ["issues"]
}
