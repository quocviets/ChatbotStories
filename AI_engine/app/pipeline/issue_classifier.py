from typing import Optional
from app.application.dto.story_dtos import AnalysisResult


def classify_primary_issue(analysis: AnalysisResult) -> Optional[str]:
    if not analysis or analysis.passed or not analysis.issues:
        return None

    if analysis.primary_issue_type:
        return analysis.primary_issue_type

    counts = {"CONTEXT_ISSUE": 0, "PLANNER_ISSUE": 0, "WRITING_ISSUE": 0, "POLICY_ISSUE": 0}
    for issue in analysis.issues:
        if issue.type == "POLICY_ISSUE":
            return "POLICY_ISSUE"
        if issue.type in counts:
            counts[issue.type] += 3 if issue.severity == "HIGH" else 1

    primary = max(counts, key=counts.get)
    return primary if counts[primary] else "WRITING_ISSUE"
