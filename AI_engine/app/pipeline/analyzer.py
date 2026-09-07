import json
import logging

from app.application.dto.story_dtos import AnalysisResult, Issue, LLMRequest
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)


class StoryAnalyzer:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def analyze(
        self,
        story_id: str,
        draft: str,
        plan: dict,
        context: dict,
        attempt: int = 0,
    ) -> AnalysisResult:
        system_prompt = (
            "You are STORY_ANALYZER. Check continuity and story logic only, not prose style. "
            "A score is telemetry, never a pass threshold. Only HIGH issues of these exact "
            "types can block a draft: EMPTY_OR_BROKEN_OUTPUT, MANDATORY_EVENT_LOSS, "
            "DIRECT_CONTINUITY_CONTRADICTION, CHAPTER_ORDER_VIOLATION, "
            "CORE_WORLD_RULE_VIOLATION, REQUIRED_POV_VIOLATION, "
            "PLOT_ALIGNMENT_VIOLATION. LOW and MEDIUM issues are warnings. "
            "Unknown issues are warnings. Return JSON only."
        )

        recent_chapters = context.get("recent_prose_reference", context.get("recent_chapters", []))
        recent_summary = "\n".join(
            f"- Chapter {chapter['version_number']}: {chapter['content'][:500]}..."
            for chapter in recent_chapters
        )
        memory_items = []
        for group in (
            "must_preserve_facts",
            "continuity_only",
            "character_state",
            "world_constraints",
            "relevant_memories",
        ):
            for item in context.get(group, []):
                memory_items.append(
                    item.get("content", "") if isinstance(item, dict) else str(item)
                )
        memories = "\n".join(f"- {item}" for item in dict.fromkeys(memory_items) if item)

        prompt = (
            f"[DRAFT]\n{draft}\n\n"
            f"[CHAPTER PLAN]\n{json.dumps(plan, ensure_ascii=False)}\n\n"
            f"[RECENT CONTINUITY]\n{recent_summary}\n\n"
            f"[STORY FACTS AND RULES]\n{memories}\n\n"
            "Check mandatory events, direct continuity contradictions, chapter order, "
            "core world rules, required POV and required plot alignment.\n"
            'Return: {"passed": true, "score": 0-100, '
            '"primary_issue_type": null, "issues": [{"type": "...", '
            '"severity": "HIGH|MEDIUM|LOW", "description": "...", '
            '"suggested_action": "..."}]}.\n'
            "Set passed=false only when at least one allowlisted HIGH issue exists."
        )
        request = LLMRequest(
            model=ROUTING_CONFIG["analyzer"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.2,
            max_tokens=1500,
            metadata={"attempt": attempt, "purpose": "story_analysis"},
        )

        try:
            response = await self.gateway.generate(ROUTING_CONFIG["analyzer"], request)
            data = json.loads(response.content)
            if not isinstance(data, dict) or not isinstance(data.get("issues", []), list):
                raise ValueError("Analyzer response must be a JSON object with an issues list")
            if "passed" not in data or not isinstance(data["passed"], bool):
                raise ValueError("Analyzer response must contain a boolean passed field")

            issues = []
            for index, item in enumerate(data.get("issues", []), start=1):
                if not isinstance(item, dict):
                    raise ValueError("Analyzer issue must be a JSON object")
                severity = str(item.get("severity", "MEDIUM")).upper()
                if severity not in {"HIGH", "MEDIUM", "LOW"}:
                    severity = "MEDIUM"
                issue_type = str(item.get("type") or "UNKNOWN_ANALYSIS_ISSUE").upper()
                issues.append(
                    Issue(
                        id=f"issue_{index}",
                        type=issue_type,
                        severity=severity,
                        description=str(item.get("description") or "Unspecified analysis warning."),
                        suggested_action=(
                            str(item["suggested_action"])
                            if item.get("suggested_action") is not None
                            else None
                        ),
                    )
                )

            score = data.get("score", 0)
            score = score if isinstance(score, int) and not isinstance(score, bool) else 0
            return AnalysisResult(
                passed=data["passed"],
                score=max(0, min(100, score)),
                issues=issues,
                primary_issue_type=(
                    str(data["primary_issue_type"])
                    if data.get("primary_issue_type") is not None
                    else None
                ),
            )
        except Exception as exc:
            logger.warning(
                "Analyzer response was unusable; keeping draft for review: %s",
                exc,
            )
            return AnalysisResult(
                passed=False,
                score=0,
                issues=[
                    Issue(
                        type="ANALYZER_UNAVAILABLE",
                        severity="MEDIUM",
                        description=(
                            f"Continuity analyzer unavailable: {type(exc).__name__}: {exc}"
                        ),
                        suggested_action="Review continuity manually before approval.",
                    )
                ],
                primary_issue_type="ANALYZER_UNAVAILABLE",
                needs_manual_review=True,
            )
