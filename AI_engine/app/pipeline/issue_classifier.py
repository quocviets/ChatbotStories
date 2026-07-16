import logging
from typing import Optional
from app.application.dto.story_dtos import AnalysisResult

logger = logging.getLogger(__name__)

class IssueClassifier:
    @staticmethod
    def classify_primary_issue(analysis: AnalysisResult) -> Optional[str]:
        """
        Determines which pipeline step needs revision based on the list of issues.
        Returns: 'CONTEXT_ISSUE', 'PLANNER_ISSUE', 'WRITING_ISSUE', 'POLICY_ISSUE' or None.
        """
        if not analysis or analysis.passed or not analysis.issues:
            return None

        # If there's a primary issue type already specified, use it
        if analysis.primary_issue_type:
            return analysis.primary_issue_type

        # Count severity and types of issues
        counts = {"CONTEXT_ISSUE": 0, "PLANNER_ISSUE": 0, "WRITING_ISSUE": 0, "POLICY_ISSUE": 0}
        
        # Policy issues have highest priority
        for issue in analysis.issues:
            issue_type = issue.type
            if issue_type == "POLICY_ISSUE":
                return "POLICY_ISSUE"
                
            if issue_type in counts:
                # Give higher weight to HIGH severity issues
                weight = 3 if issue.severity == "HIGH" else 1
                counts[issue_type] += weight

        # Sort and get key with max weight
        sorted_issues = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        if sorted_issues[0][1] > 0:
            return sorted_issues[0][0]

        return "WRITING_ISSUE" # Default fallback
