"""Predator Agent — Dual-LLM Orchestrator (full pipeline wiring)"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ..battle_mode import BattleMode
from ..dashboard.live_dashboard import LiveDashboard
from ..enrichment.voter_context import VoterContext, VoterContextBuilder
from ..intelligence.post_call_report import PostCallReporter
from ..llm.prompt_builder import PromptBuilder
from ..llm.slow_llm import PsychologicalAnalysis, SlowLLMAnalyzer
from ..optimizer.ab_engine import ABEngine, reward_from_outcome
from ..personas.persona_base import get_tts_params
from ..persuasion.resistance_meter import ResistanceMeter
from ..persuasion.tactics import get_all_tactics, get_tactic_for_moment
from ..profile.disc_classifier import classify, suggest_persona_from_profile
from ..state_machine.states import ConversationState, can_transition
from ..supervisor.whisper_mode import BUS as WHISPER_BUS

logger = logging.getLogger("predator-agent")

LLM_HEBREW_PARAMS = {
    # Fast path: Groq primary, OpenAI fallback (see src/llm/fast_llm.py)
    "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "fallback_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    "provider": "groq",
    "temperature": 0.9,
    "max_tokens": 90,
    "top_p": 0.92,
}

SILENCE_TIMEOUT_SEC = float(os.getenv("SILENCE_TIMEOUT_SEC", "4"))
SILENCE_PROBE = "בוחן? אתה שם?"
SLOW_LLM_TIMEOUT_SEC = float(os.getenv("SLOW_LLM_TIMEOUT_SEC", "8"))
TURN_BUDGET_SEC = float(os.getenv("TURN_BUDGET_SEC", "12"))


@dataclass
class CallSession:
    session_id: str
    voter_context: Optional[VoterContext] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    current_state: ConversationState = ConversationState.OPENING
    current_persona: str = "S"
    current_resistance: str = "medium"
    current_tactic: Optional[str] = None
    current_tactic_key: Optional[str] = None
    exchange_count: int = 0
    last_slow_analysis: Optional[PsychologicalAnalysis] = None
    support_score: float = 0.5
    resistance_meter: ResistanceMeter = field(default_factory=ResistanceMeter)
    ab_arm: Optional[dict] = None
    phone: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ended: bool = False

    def transition_to(self, new_state: ConversationState) -> bool:
        if can_transition(self.current_state, new_state):
            self.current_state = new_state
            return True
        return False

    def get_last_voter_message(self) -> Optional[str]:
        for msg in reversed(self.conversation_history):
            if msg["role"] == "user":
                return msg["content"]
        return None


def _tactic_prompt_block(tactic) -> Optional[str]:
    if not tactic:
        return None
    lines = [f"שם: {tactic.name}", f"מנגנון: {tactic.mechanism}", f"כלל: {tactic.rule}"]
    if tactic.hebrew_templates:
        lines.append("תבניות:")
        for t in tactic.hebrew_templates[:3]:
            lines.append(f"- {t}")
    return "\n".join(lines)


class PredatorAgent:
    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        self.slow_llm = SlowLLMAnalyzer(api_key=anthropic_api_key)
        self.prompt_builder = PromptBuilder()
        self.voter_builder = VoterContextBuilder()
        self.active_sessions: Dict[str, CallSession] = {}
        self.battle_modes: Dict[str, BattleMode] = {}
        self.dashboard = LiveDashboard()
        self.whisper_bus = WHISPER_BUS
        self.ab_engine = ABEngine(store_path=os.getenv("AB_BANDIT_STATE", "data/ab_bandit_state.json"))
        self.reporter = PostCallReporter(store_dir=os.getenv("REPORTS_DIR", "data/reports"))
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._openai_client = None

    @property
    def openai_client(self):
        if self._openai_client is None:
            try:
                from openai import AsyncOpenAI

                self._openai_client = AsyncOpenAI(api_key=self.openai_api_key)
            except Exception:
                return None
        return self._openai_client

    def create_session(
        self,
        session_id: str,
        voter_context: Optional[VoterContext] = None,
        phone: str = "",
    ) -> CallSession:
        persona = self._initial_persona(voter_context)
        ab_arm = None
        if voter_context:
            ab_arm = self.ab_engine.select(
                neighborhood=voter_context.street or voter_context.city or "unknown",
                age_group=voter_context.age_group or "unknown",
                gender=voter_context.gender or "unknown",
            )
            # AB בוחר פרסונה כשיש מספיק סיגנל / ברירת מחדל דמוגרפית חלשה
            if ab_arm and ab_arm.get("pulls", 0) >= 0:
                persona = ab_arm.get("best_persona") or persona

        session = CallSession(
            session_id=session_id,
            voter_context=voter_context,
            current_persona=persona,
            support_score=voter_context.support_score if voter_context else 0.5,
            ab_arm=ab_arm,
            phone=phone or getattr(voter_context, "phone", "") or "",
        )
        if voter_context and voter_context.support_score > 0.7:
            session.current_state = ConversationState.GOTV
        if ab_arm and ab_arm.get("best_tactic"):
            session.current_tactic_key = ab_arm["best_tactic"]
            tactics = get_all_tactics()
            t = tactics.get(ab_arm["best_tactic"])
            if t:
                session.current_tactic = t.name

        self.active_sessions[session_id] = session
        self.battle_modes[session_id] = BattleMode()
        self.dashboard.publish_turn(
            session_id,
            {
                "voter": self._voter_name(session),
                "phone": session.phone,
                "persona": session.current_persona,
                "state": session.current_state.value,
                "resistance": session.current_resistance,
                "persuadability": session.support_score,
                "exchange": 0,
            },
        )
        return session

    def _voter_name(self, session: CallSession) -> str:
        if not session.voter_context:
            return ""
        return f"{session.voter_context.first_name} {session.voter_context.last_name}".strip()

    def _initial_persona(self, ctx: Optional[VoterContext]) -> str:
        if not ctx:
            return "S"
        if ctx.gender == "female" and ctx.age_group == "65+":
            return "S"
        if ctx.gender == "male" and ctx.age_group in ("25-45", "45-65"):
            return "D"
        if ctx.age_group == "25-45":
            return "I"
        if ctx.ethnic_hint == "russian":
            return "D"
        if ctx.ethnic_hint == "ethiopian":
            return "S"
        return "S"

    async def process_voter_turn(
        self,
        session_id: str,
        voter_text: str,
        *,
        compact_prompt: bool = False,
        skip_slow_llm: bool = False,
    ) -> dict:
        session = self.active_sessions.get(session_id)
        if not session or session.ended:
            return {"error": "session not found"}

        resistance = session.resistance_meter.update(voter_text)
        session.current_resistance = resistance.level

        battle = self.battle_modes.setdefault(session_id, BattleMode())
        battle_hit = battle.evaluate(voter_text, resistance_level=resistance.level)
        if battle_hit:
            self.dashboard.registry.mark_battle(session_id, True)

        disc = classify(voter_text)
        session.conversation_history.append({"role": "user", "content": voter_text})
        session.exchange_count += 1

        # DISC→persona suggestion early (confidence גבוה)
        if disc.confidence >= 0.7 and session.exchange_count <= 2:
            suggested = suggest_persona_from_profile(disc)
            # רק אם אין AB חזק — עדיין מאפשרים הצעה רכה דרך fallback×3

        if not skip_slow_llm and session.exchange_count % 2 == 0:
            await self._run_slow_analysis(session)

        if session.resistance_meter.should_deescalate() and session.current_state not in (
            ConversationState.DEESCALATION,
            ConversationState.CLOSING,
        ):
            session.transition_to(ConversationState.DEESCALATION)

        self._maybe_transition(session, resistance.level, disc.primary)

        tactic = None
        if session.current_tactic_key and session.last_slow_analysis is None:
            tactic = get_all_tactics().get(session.current_tactic_key)
        if not tactic:
            tactic = get_tactic_for_moment(
                state=session.current_state.value,
                resistance=resistance.level,
                support_score=session.support_score,
            )
        # slow LLM best_tactic גובר כשיש
        if session.last_slow_analysis and session.last_slow_analysis.best_tactic:
            slow_t = get_all_tactics().get(session.last_slow_analysis.best_tactic)
            if slow_t:
                tactic = slow_t
        if tactic:
            session.current_tactic = tactic.name
            for k, v in get_all_tactics().items():
                if v.name == tactic.name:
                    session.current_tactic_key = k
                    break

        voter_ctx_str = None
        if session.voter_context:
            voter_ctx_str = self.voter_builder.to_prompt_context(session.voter_context)

        system_prompt = self.prompt_builder.build(
            persona_disc=session.current_persona,
            voter_context=voter_ctx_str,
            state=session.current_state.value,
            resistance_level=resistance.level,
            best_tactic=_tactic_prompt_block(tactic),
            support_score=session.support_score,
            exchange_number=session.exchange_count,
            compact=compact_prompt,
        )
        whisper_overlay = self.whisper_bus.prompt_overlay(session_id)
        if whisper_overlay:
            system_prompt = f"{system_prompt}\n\n{whisper_overlay}"
        if battle_hit and battle.prompt_overlay():
            system_prompt = f"{system_prompt}\n\n{battle.prompt_overlay()}"

        tts_params = get_tts_params(session.current_persona)
        tts_params["speed"] = self._calc_tts_speed(
            tts_params["speed"],
            session.current_state,
            session.last_slow_analysis,
            ab_speed=(session.ab_arm or {}).get("best_speed"),
        )

        # Battle short-circuit — תשובה מוכנה בלי LLM
        forced_reply = None
        if battle_hit and battle_hit.get("reply"):
            forced_reply = battle_hit["reply"]
            if battle_hit.get("return_to_topic"):
                forced_reply = f"{forced_reply} {battle_hit['return_to_topic']}".strip()

        result = {
            "system_prompt": system_prompt,
            "tts_params": tts_params,
            "llm_params": dict(LLM_HEBREW_PARAMS),
            "timeouts": {
                "silence_sec": SILENCE_TIMEOUT_SEC,
                "slow_llm_sec": SLOW_LLM_TIMEOUT_SEC,
                "turn_budget_sec": TURN_BUDGET_SEC,
            },
            "state": session.current_state.value,
            "persona": session.current_persona,
            "resistance": resistance.level,
            "resistance_score": resistance.score,
            "tactic": tactic.name if tactic else None,
            "disc": disc.primary,
            "battle": battle_hit,
            "battle_overlay": battle.prompt_overlay() if battle_hit else "",
            "forced_reply": forced_reply,
            "whisper": bool(whisper_overlay),
            "ab": session.ab_arm,
        }

        self.dashboard.publish_turn(
            session_id,
            {
                "voter": self._voter_name(session),
                "phone": session.phone,
                "persona": session.current_persona,
                "state": session.current_state.value,
                "resistance": resistance.level,
                "tactic": tactic.name if tactic else "",
                "disc": disc.primary,
                "battle": bool(battle_hit),
                "exchange": session.exchange_count,
                "last_voter_text": voter_text,
                "persuadability": session.support_score,
            },
        )
        return result

    def handle_silence(self, session_id: str, silence_seconds: float) -> Optional[dict]:
        session = self.active_sessions.get(session_id)
        if not session or session.ended:
            return {"error": "session not found"}
        if silence_seconds < SILENCE_TIMEOUT_SEC:
            return None

        battle = self.battle_modes.setdefault(session_id, BattleMode())
        battle_hit = battle.evaluate("", silence_seconds=silence_seconds)
        tts_params = get_tts_params(session.current_persona)
        tts_params["speed"] = self._calc_tts_speed(
            tts_params["speed"],
            session.current_state,
            session.last_slow_analysis,
            ab_speed=(session.ab_arm or {}).get("best_speed"),
        )
        reply = (battle_hit or {}).get("reply", SILENCE_PROBE)
        return {
            "reply": reply,
            "forced_reply": reply,
            "silence_probe": True,
            "battle": battle_hit,
            "silence_seconds": silence_seconds,
            "tts_params": tts_params,
            "llm_params": dict(LLM_HEBREW_PARAMS),
            "state": session.current_state.value,
            "persona": session.current_persona,
        }

    async def end_session(
        self,
        session_id: str,
        *,
        outcome: str = "answered",
        duration_seconds: float = 0,
        send_whatsapp: bool = True,
        dry_run_whatsapp: Optional[bool] = None,
    ) -> dict:
        """סגירת שיחה: dashboard end + post-call report + WhatsApp + AB observe."""
        session = self.active_sessions.get(session_id)
        if not session:
            return {"error": "session not found"}
        if session.ended:
            return {"status": "already_ended", "session_id": session_id}

        session.ended = True
        final_state = session.current_state.value
        if final_state not in ("closing", "commitment", "gotv", "seed_planting"):
            # סגירה רכה
            session.transition_to(ConversationState.CLOSING)
            final_state = session.current_state.value

        self.dashboard.publish_end(session_id, final_state)

        report = await self.reporter.build(
            voter=self._voter_name(session) or "לא ידוע",
            history=session.conversation_history,
            final_state=final_state,
            duration_seconds=duration_seconds,
            persona=session.current_persona,
            resistance=session.current_resistance,
            phone=session.phone,
            session_id=session_id,
            use_llm=bool(self.openai_api_key),
        )
        push = self.reporter.push_to_manager(report, channels=["slack", "telegram"])

        wa_result = None
        if send_whatsapp:
            from ..channels.whatsapp_followup import WhatsAppFollowup

            dry = dry_run_whatsapp
            if dry is None:
                dry = os.getenv("WHATSAPP_DRY_RUN", "true").lower() in ("1", "true", "yes")
            wa_result = WhatsAppFollowup().maybe_send_after_call(
                {
                    "phone": session.phone,
                    "voter": report.voter,
                    "full_name": report.voter,
                    "final_state": final_state,
                    "persona": session.current_persona,
                    "resistance": session.current_resistance,
                    "commitment": report.commitment,
                    "poll_location": report.poll_location or os.getenv("POLL_LOCATION"),
                },
                dry_run=dry,
            )

        # AB learn
        if session.voter_context and session.ab_arm:
            committed = any(
                x in (report.commitment or "") for x in ("הבטיח", "נכונות", "אגיע")
            )
            self.ab_engine.observe(
                neighborhood=session.voter_context.street or session.voter_context.city or "unknown",
                age_group=session.voter_context.age_group or "unknown",
                gender=session.voter_context.gender or "unknown",
                persona=session.current_persona,
                tactic=session.current_tactic_key or "micro_yes_ladder",
                speed=float((session.ab_arm or {}).get("best_speed") or 1.0),
                reward=reward_from_outcome(outcome, commitment=committed),
            )

        return {
            "status": "ended",
            "session_id": session_id,
            "final_state": final_state,
            "report": report.to_dict(),
            "push": push,
            "whatsapp": wa_result,
        }

    async def _run_slow_analysis(self, session: CallSession) -> None:
        try:
            voter_ctx_dict = None
            if session.voter_context:
                voter_ctx_dict = {
                    "first_name": session.voter_context.first_name,
                    "last_name": session.voter_context.last_name,
                    "gender": session.voter_context.gender,
                    "age_group": session.voter_context.age_group,
                    "support_score": session.voter_context.support_score,
                }
            analysis = await asyncio.wait_for(
                self.slow_llm.analyze(
                    conversation_history=session.conversation_history,
                    voter_context=voter_ctx_dict,
                ),
                timeout=SLOW_LLM_TIMEOUT_SEC,
            )
            if analysis:
                session.last_slow_analysis = analysis
                if (
                    analysis.persona_recommendation != session.current_persona
                    and analysis.confidence > 0.6
                ):
                    session.current_persona = analysis.persona_recommendation
                    logger.info("[%s] persona → %s", session.session_id, analysis.persona_recommendation)
                if analysis.best_tactic:
                    session.current_tactic_key = analysis.best_tactic
            if not analysis or analysis.confidence < 0.6:
                self._disc_persona_fallback(session)
        except asyncio.TimeoutError:
            logger.warning("[%s] slow_llm timeout — DISC fallback", session.session_id)
            self._disc_persona_fallback(session)
        except Exception as e:
            logger.error("slow analysis failed: %s", e)
            self._disc_persona_fallback(session)

    def _disc_persona_fallback(self, session: CallSession) -> None:
        recent_discs = [
            classify(m["content"]).primary
            for m in session.conversation_history[-6:]
            if m["role"] == "user"
        ]
        if len(recent_discs) >= 3 and len(set(recent_discs[-3:])) == 1:
            if recent_discs[-1] != session.current_persona:
                session.current_persona = recent_discs[-1]
                logger.info(
                    "[%s] persona fallback DISC×3 → %s",
                    session.session_id,
                    recent_discs[-1],
                )

    def _maybe_transition(
        self,
        session: CallSession,
        resistance_level: str,
        disc_primary: str,
    ) -> None:
        current = session.current_state
        if current == ConversationState.GOTV:
            if resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.OBJECTION_HANDLING)
            elif session.exchange_count >= 4 and resistance_level == "low":
                session.transition_to(ConversationState.CLOSING)
            return
        if current == ConversationState.OPENING:
            if resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.DEESCALATION)
            else:
                session.transition_to(ConversationState.EXPLORATION)
            return
        if current == ConversationState.DEESCALATION:
            if resistance_level in ("low", "medium") and session.exchange_count >= 2:
                session.transition_to(ConversationState.EXPLORATION)
            elif session.exchange_count >= 6:
                session.transition_to(ConversationState.CLOSING)
            return
        if current == ConversationState.EXPLORATION:
            if resistance_level == "low" and disc_primary in ("D", "I") and session.exchange_count >= 2:
                session.transition_to(ConversationState.AMPLIFICATION)
            elif session.exchange_count >= 3:
                session.transition_to(ConversationState.PROFILING)
            return
        if current == ConversationState.AMPLIFICATION:
            if session.exchange_count >= 3:
                session.transition_to(ConversationState.PERSUASION)
            return
        if current == ConversationState.PROFILING:
            if session.exchange_count >= 4:
                session.transition_to(ConversationState.PERSUASION)
            return
        if current == ConversationState.PERSUASION:
            if resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.OBJECTION_HANDLING)
            elif session.exchange_count >= 6 and resistance_level == "low":
                session.transition_to(ConversationState.COMMITMENT)
            return
        if current == ConversationState.COMMITMENT:
            if session.exchange_count >= 1:
                session.transition_to(ConversationState.CLOSING)
            return
        if current == ConversationState.OBJECTION_HANDLING:
            if resistance_level == "low":
                session.transition_to(ConversationState.PERSUASION)
            elif session.exchange_count >= 8:
                session.transition_to(ConversationState.SEED_PLANTING)
            return
        if current == ConversationState.SEED_PLANTING:
            if session.exchange_count >= 9:
                session.transition_to(ConversationState.CLOSING)
            return

    def _calc_tts_speed(
        self,
        base_speed: float,
        state: ConversationState,
        slow_analysis: Optional[PsychologicalAnalysis] = None,
        ab_speed: Optional[float] = None,
    ) -> float:
        state_modifier = {
            ConversationState.OPENING: 1.0,
            ConversationState.EXPLORATION: 0.97,
            ConversationState.PROFILING: 0.95,
            ConversationState.PERSUASION: 1.05,
            ConversationState.COMMITMENT: 0.92,
            ConversationState.CLOSING: 0.90,
            ConversationState.OBJECTION_HANDLING: 0.95,
            ConversationState.SEED_PLANTING: 0.95,
            ConversationState.GOTV: 1.0,
            ConversationState.DEESCALATION: 0.88,
            ConversationState.AMPLIFICATION: 1.05,
        }
        speed = base_speed * state_modifier.get(state, 1.0)
        if slow_analysis:
            speed *= slow_analysis.suggested_pace_modifier
        if ab_speed:
            # ממוצע עדין עם AB
            speed = (speed + float(ab_speed)) / 2.0
        return round(max(0.88, min(1.08, speed)), 2)

    def add_assistant_response(self, session_id: str, response: str) -> None:
        session = self.active_sessions.get(session_id)
        if session:
            session.conversation_history.append({"role": "assistant", "content": response})
            self.dashboard.publish_turn(
                session_id,
                {"last_agent_text": response, "exchange": session.exchange_count},
            )

    def get_session(self, session_id: str) -> Optional[CallSession]:
        return self.active_sessions.get(session_id)
