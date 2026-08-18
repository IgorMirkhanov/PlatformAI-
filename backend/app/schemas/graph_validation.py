from __future__ import annotations

from pydantic import BaseModel


class GraphValidationIssue(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    button_id: str | None = None
    field: str | None = None


class GraphValidationError(Exception):
    """Raised when a React Flow export fails structural validation."""

    def __init__(self, issues: list[GraphValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(issue.message for issue in issues[:3])
        super().__init__(summary or "Flow graph validation failed")


def issues_to_http_detail(issues: list[GraphValidationIssue]) -> dict[str, object]:
    return {
        "message": "Flow graph validation failed. Fix the highlighted nodes or edges in the canvas.",
        "issues": [issue.model_dump() for issue in issues],
    }
