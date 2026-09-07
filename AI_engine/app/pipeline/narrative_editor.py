import json
import logging

import app.config as config
from app.application.dto.story_dtos import (
    LLMRequest,
    NarrativeCritique,
    TargetedRevision,
)
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)


def _paragraph_spans(text: str) -> list[tuple[str, int, int, str]]:
    spans = []
    start = end = None
    offset = 0
    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        visible = line.rstrip("\r\n")
        if visible.strip():
            start = line_start if start is None else start
            end = line_start + len(visible)
        elif start is not None:
            spans.append((f"p{len(spans) + 1:04d}", start, end, text[start:end]))
            start = end = None
    if start is not None:
        spans.append((f"p{len(spans) + 1:04d}", start, end, text[start:end]))
    return spans


def _json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=lambda item: item.model_dump() if hasattr(item, "model_dump") else str(item),
    )


class NarrativeEditor:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    @staticmethod
    def has_revisable_issues(critique: NarrativeCritique) -> bool:
        return critique.needs_revision and any(
            issue.severity in {"high", "medium"} and issue.type != "continuity_risk"
            for issue in critique.issues
        )

    async def critique(
        self, draft: str, context: dict, character_wiki: dict | None
    ) -> NarrativeCritique:
        paragraphs = _paragraph_spans(draft)
        if not paragraphs:
            return NarrativeCritique(needs_revision=False, issues=[])

        system_prompt = (
            "Bạn là NARRATIVE_CRITIC, chỉ phân tích chất lượng văn xuôi, không viết lại.\n"
            "Phát hiện đúng các loại: redundant_explanation, show_dont_tell_violation, "
            "summary_like_prose, unnatural_dialogue, expository_dialogue, repeated_information, "
            "authorial_conclusion, overexplained_emotion, generic_ai_phrase, "
            "overly_complete_reasoning, pacing_drag, character_voice_mismatch, "
            "unnecessary_internal_monologue, purple_prose, continuity_risk.\n"
            "Không áp dụng show-don't-tell máy móc. Chỉ đánh dấu paragraph thực sự cần sửa. "
            "Severity phải là high, medium hoặc low. Nếu không có lỗi đáng sửa, trả "
            "needs_revision=false và issues rỗng. "
            "Trả JSON đúng schema, không thêm field."
        )
        paragraph_text = "\n\n".join(
            f"[{paragraph_id}]\n{text}" for paragraph_id, _start, _end, text in paragraphs
        )
        prompt = (
            f"[PARAGRAPHS]\n{paragraph_text}\n\n"
            f"[MUST PRESERVE FACTS]\n{_json(context.get('must_preserve_facts', []))}\n\n"
            f"[CHARACTER VOICE]\n{_json(character_wiki or {})}\n\n"
            "Trả JSON:\n"
            '{"needs_revision": true, "issues": [{'
            '"type": "authorial_conclusion", "severity": "medium", '
            '"paragraph_ids": ["p0001"], "evidence": "trích đoạn ngắn", '
            '"reason": "lý do", "revision_instruction": "chỉ dẫn sửa đoạn", '
            '"must_preserve": ["dữ kiện phải giữ"]}]}'
        )
        request = LLMRequest(
            model=ROUTING_CONFIG["narrative_critic"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.2,
            max_tokens=3000,
            metadata={"purpose": "narrative_critique"},
        )
        try:
            response = await self.gateway.generate(ROUTING_CONFIG["narrative_critic"], request)
            critique = NarrativeCritique.model_validate_json(response.content)
            known_ids = {paragraph_id for paragraph_id, *_rest in paragraphs}
            if any(
                paragraph_id not in known_ids
                for issue in critique.issues
                for paragraph_id in issue.paragraph_ids
            ):
                raise ValueError("Critic returned an unknown paragraph ID")
            return critique
        except Exception as exc:
            logger.warning("Narrative critic failed; keeping raw draft: %s", exc)
            return NarrativeCritique(
                needs_revision=False,
                issues=[],
                fallback_reason=str(exc),
            )

    async def revise(
        self,
        draft: str,
        critique: NarrativeCritique,
        context: dict,
        plan: dict,
        character_wiki: dict | None,
        model_alias: str,
    ) -> tuple[str, bool]:
        paragraphs = _paragraph_spans(draft)
        paragraph_map = {
            paragraph_id: (index, start, end, text)
            for index, (paragraph_id, start, end, text) in enumerate(paragraphs)
        }
        issues = [
            issue
            for issue in critique.issues
            if issue.severity in {"high", "medium"} and issue.type != "continuity_risk"
        ]
        target_ids = list(
            dict.fromkeys(paragraph_id for issue in issues for paragraph_id in issue.paragraph_ids)
        )[: config.NARRATIVE_MAX_CHANGED_PARAGRAPHS]
        if not critique.needs_revision or not target_ids:
            return draft, False

        try:
            if any(paragraph_id not in paragraph_map for paragraph_id in target_ids):
                raise ValueError("Revision requested an unknown paragraph ID")

            visible_ids = set(target_ids)
            for paragraph_id in target_ids:
                index = paragraph_map[paragraph_id][0]
                if index:
                    visible_ids.add(paragraphs[index - 1][0])
                if index + 1 < len(paragraphs):
                    visible_ids.add(paragraphs[index + 1][0])

            paragraph_text = "\n\n".join(
                f"[{'TARGET' if paragraph_id in target_ids else 'READ ONLY'} {paragraph_id}]\n{text}"
                for paragraph_id, _start, _end, text in paragraphs
                if paragraph_id in visible_ids
            )
            instructions = "\n".join(
                f"- {', '.join(paragraph_id for paragraph_id in issue.paragraph_ids if paragraph_id in target_ids)}: "
                f"{issue.revision_instruction}"
                for issue in issues
                if any(paragraph_id in target_ids for paragraph_id in issue.paragraph_ids)
            )
            must_preserve = list(context.get("must_preserve_facts", []))
            must_preserve.extend(fact for issue in issues for fact in issue.must_preserve)
            system_prompt = (
                "Bạn là TARGETED_REVISER. Chỉ sửa các paragraph có nhãn TARGET.\n"
                "Không viết lại toàn chương, không trả paragraph READ ONLY, không thêm tình tiết, "
                "không đổi thứ tự sự kiện, POV, tên riêng, vật phẩm hoặc logic sức mạnh.\n"
                "Giữ giọng từng nhân vật. revised_text phải là văn bản thuần, không dùng Markdown "
                "hoặc ký hiệu định dạng như *, ** hay #. Trả JSON đúng schema và không thêm field."
            )
            prompt = (
                f"[TARGETS AND READ-ONLY CONTEXT]\n{paragraph_text}\n\n"
                f"[REVISION INSTRUCTIONS]\n{instructions}\n\n"
                f"[MUST PRESERVE]\n{_json(list(dict.fromkeys(must_preserve)))}\n"
                f"[POV]\n{plan.get('pov_character', '')}\n"
                f"[CHARACTER VOICE]\n{_json(character_wiki or {})}\n\n"
                "Trả đúng một replacement cho mỗi TARGET:\n"
                '{"revisions": [{"paragraph_id": "p0001", "revised_text": "văn bản thay thế"}]}'
            )
            request = LLMRequest(
                model=model_alias,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                response_format="json_object",
                temperature=0.3,
                max_tokens=4000,
                metadata={
                    "purpose": "targeted_revision",
                    "target_paragraph_ids": target_ids,
                },
            )
            response = await self.gateway.generate(model_alias, request)
            result = TargetedRevision.model_validate_json(response.content)
            replacements = {item.paragraph_id: item.revised_text for item in result.revisions}
            if len(replacements) != len(result.revisions) or set(replacements) != set(target_ids):
                raise ValueError("Revision must return each target exactly once")
            if any(
                text != text.strip() or len(_paragraph_spans(text)) != 1
                for text in replacements.values()
            ):
                raise ValueError("Each replacement must contain exactly one paragraph")

            critical_facts = [
                fact
                for fact in context.get("must_preserve_facts", [])
                if isinstance(fact, str) and fact
            ]
            critical_facts.extend(fact for issue in issues for fact in issue.must_preserve if fact)
            for paragraph_id, revised in replacements.items():
                original = paragraph_map[paragraph_id][3]
                for fact in dict.fromkeys(critical_facts):
                    if fact in original and fact not in revised:
                        raise ValueError(f"Revision removed must-preserve text from {paragraph_id}")

            original_word_count = sum(
                len(paragraph_map[paragraph_id][3].split()) for paragraph_id in target_ids
            )
            revised_word_count = sum(
                len(replacements[paragraph_id].split()) for paragraph_id in target_ids
            )
            if (
                original_word_count
                and abs(revised_word_count - original_word_count) / original_word_count
                > config.NARRATIVE_MAX_WORD_DELTA_RATIO
            ):
                raise ValueError("Targeted revision changed the word count too much")

            revised_draft = draft
            for paragraph_id in sorted(
                target_ids, key=lambda item: paragraph_map[item][1], reverse=True
            ):
                _index, start, end, _text = paragraph_map[paragraph_id]
                revised_draft = (
                    revised_draft[:start] + replacements[paragraph_id] + revised_draft[end:]
                )
            return revised_draft, revised_draft != draft
        except Exception as exc:
            logger.warning("Targeted revision failed; keeping raw draft: %s", exc)
            return draft, False
