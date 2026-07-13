"""Slow LLM — Claude Sonnet 5 — ניתוח פסיכולוגי"""
import os
import json
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass

logger = logging.getLogger("slow-llm")


@dataclass
class PsychologicalAnalysis:
    disc_primary: str
    disc_secondary: Optional[str]
    resistance_level: str
    best_tactic: str
    emotional_anchors: List[str]
    hidden_objections: List[str]
    persona_recommendation: str
    suggested_pace_modifier: float
    summary: str
    confidence: float = 0.5


class SlowLLMAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-5"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                return None
        return self._client

    async def analyze(self, conversation_history, voter_context=None):
        if not self.client:
            return self._fallback()
        prompt = self._build_prompt(conversation_history, voter_context)
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=800,
                temperature=0.3,
                system="אתה פסיכולוג פוליטי. עונה רק ב-JSON תקין. בלי markdown.",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            return self._parse_response(content)
        except Exception as e:
            logger.error(f"Claude error: {e}")
            return self._fallback()

    def _build_prompt(self, history, voter_ctx):
        ctx_str = ""
        if voter_ctx:
            ctx_str = f"\n\n[הקשר]\n{json.dumps(voter_ctx, ensure_ascii=False)}"
        conv_text = "\n".join(f"{'סוכן' if m['role'] == 'assistant' else 'בוחר'}: {m['content']}" for m in history[-12:])
        return f"""נתח את השיחה והחזר JSON בלבד.{ctx_str}

[שיחה]
{conv_text}

[פורמט — JSON]
{{
  "disc_primary": "D"|"I"|"S"|"C",
  "disc_secondary": "D"|"I"|"S"|"C"|null,
  "resistance_level": "low"|"medium"|"high"|"very_high",
  "best_tactic": "loss_aversion|social_proof|scarcity_urgency|reciprocity|anchoring|foot_in_door|door_in_face|fear_then_relief|micro_yes_ladder|limited_choice|emotional_time_travel|debt_creation|three_cards",
  "emotional_anchors": ["..."],
  "hidden_objections": ["..."],
  "persona_recommendation": "D"|"I"|"S"|"C",
  "suggested_pace_modifier": 0.85-1.15,
  "summary": "סיכום 2 משפטים",
  "confidence": 0.0-1.0
}}"""

    def _parse_response(self, text):
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.strip().startswith("```"))
        try:
            data = json.loads(text)
            return PsychologicalAnalysis(
                disc_primary=data.get("disc_primary", "S"),
                disc_secondary=data.get("disc_secondary"),
                resistance_level=data.get("resistance_level", "medium"),
                best_tactic=data.get("best_tactic", "reciprocity"),
                emotional_anchors=data.get("emotional_anchors", []),
                hidden_objections=data.get("hidden_objections", []),
                persona_recommendation=data.get("persona_recommendation", "S"),
                suggested_pace_modifier=float(data.get("suggested_pace_modifier", 1.0)),
                summary=data.get("summary", ""),
                confidence=float(data.get("confidence", 0.5)),
            )
        except json.JSONDecodeError:
            return self._fallback()

    def _fallback(self):
        return PsychologicalAnalysis(
            disc_primary="S", disc_secondary=None, resistance_level="medium",
            best_tactic="reciprocity", emotional_anchors=[], hidden_objections=[],
            persona_recommendation="S", suggested_pace_modifier=1.0,
            summary="ניתוח מקומי — Claude לא זמין", confidence=0.3,
        )
