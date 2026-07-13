"""Predator Agent — Dual-LLM Orchestrator (Hebrew-optimized)"""
import os
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from ..personas.persona_base import get_persona, get_tts_params
from ..profile.disc_classifier import classify
from ..persuasion.tactics import get_tactic_for_moment
from ..persuasion.resistance_meter import measure_resistance
from ..state_machine.states import ConversationState, can_transition
from ..llm.slow_llm import SlowLLMAnalyzer, PsychologicalAnalysis
from ..llm.prompt_builder import PromptBuilder
from ..enrichment.voter_context import VoterContext, VoterContextBuilder

logger = logging.getLogger("predator-agent")


LLM_HEBREW_PARAMS = {
    "model": "gpt-4.1-mini",
    "temperature": 0.82,
    "max_tokens": 150,
    "top_p": 0.92,
    "frequency_penalty": 0.15,
    "presence_penalty": 0.10,
}


@dataclass
class CallSession:
    session_id: str
    voter_context: Optional[VoterContext] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    current_state: ConversationState = ConversationState.OPENING
    current_persona: str = "S"
    current_resistance: str = "medium"
    current_tactic: Optional[str] = None
    exchange_count: int = 0
    last_slow_analysis: Optional[PsychologicalAnalysis] = None
    support_score: float = 0.5

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


class PredatorAgent:
    def __init__(self, anthropic_api_key=None, openai_api_key=None):
        self.slow_llm = SlowLLMAnalyzer(api_key=anthropic_api_key)
        self.prompt_builder = PromptBuilder()
        self.voter_builder = VoterContextBuilder()
        self.active_sessions: Dict[str, CallSession] = {}
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._openai_client = None
        # ── Dashboard integration ──
        self._dashboard_enabled = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
        # ── Whisper integration ──
        self.whisper = None
        try:
            from ..supervisor.whisper_mode import WhisperIntegrator
            self.whisper = WhisperIntegrator(
                enabled=os.getenv("WHISPER_ENABLED", "true").lower() == "true"
            )
        except ImportError:
            pass

    @property
    def openai_client(self):
        if self._openai_client is None:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(api_key=self.openai_api_key)
            except ImportError:
                return None
        return self._openai_client

    def create_session(self, session_id: str, voter_context=None) -> CallSession:
        session = CallSession(
            session_id=session_id,
            voter_context=voter_context,
            current_persona=self._initial_persona(voter_context),
            support_score=voter_context.support_score if voter_context else 0.5,
        )
        if voter_context and voter_context.support_score > 0.7:
            session.current_state = ConversationState.GOTV
        self.active_sessions[session_id] = session
        # ── Dashboard: record call start ──
        self._dashboard_record_start(session_id, voter_context)
        # ── Whisper: notify session start ──
        if self.whisper:
            phone = voter_context.phone if voter_context and hasattr(voter_context, 'phone') else ""
            first = voter_context.first_name if voter_context else ""
            self.whisper.on_session_start(session_id, phone=phone, first_name=first)
        return session

    def _initial_persona(self, ctx) -> str:
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

    async def process_voter_turn(self, session_id: str, voter_text: str) -> Dict:
        session = self.active_sessions.get(session_id)
        if not session:
            return {"error": "session not found"}

        resistance = measure_resistance(voter_text)
        session.current_resistance = resistance.level
        disc = classify(voter_text)
        session.conversation_history.append({"role": "user", "content": voter_text})
        session.exchange_count += 1

        if session.exchange_count % 2 == 0:
            await self._run_slow_analysis(session)

        self._maybe_transition(session, resistance.level, disc.primary)

        tactic = get_tactic_for_moment(
            state=session.current_state.value,
            resistance=resistance.level,
            support_score=session.support_score,
        )
        if tactic:
            session.current_tactic = tactic.name

        voter_ctx_str = None
        if session.voter_context:
            voter_ctx_str = self.voter_builder.to_prompt_context(session.voter_context)

        system_prompt = self.prompt_builder.build(
            persona_disc=session.current_persona,
            voter_context=voter_ctx_str,
            state=session.current_state.value,
            resistance_level=resistance.level,
            best_tactic=tactic.name if tactic else None,
            support_score=session.support_score,
            exchange_number=session.exchange_count,
        )

        tts_params = get_tts_params(session.current_persona)
        tts_params["speed"] = self._calc_tts_speed(
            tts_params["speed"], session.current_state, session.last_slow_analysis
        )

        # ── Dashboard: record update ──
        self._dashboard_record_update(session_id, session)
        # ── Whisper: notify agent response ──
        if self.whisper:
            self.whisper.on_agent_response(session_id, {
                "state": session.current_state.value,
                "resistance": resistance.level,
                "persona": session.current_persona,
                "exchange_count": session.exchange_count,
                "system_prompt": system_prompt[:300],
            })

        return {
            "system_prompt": system_prompt,
            "tts_params": tts_params,
            "llm_params": LLM_HEBREW_PARAMS.copy(),
            "state": session.current_state.value,
            "persona": session.current_persona,
            "resistance": resistance.level,
            "tactic": tactic.name if tactic else None,
            "disc": disc.primary,
        }

    async def _run_slow_analysis(self, session: CallSession):
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
            analysis = await self.slow_llm.analyze(
                conversation_history=session.conversation_history,
                voter_context=voter_ctx_dict,
            )
            if analysis:
                session.last_slow_analysis = analysis
                if analysis.persona_recommendation != session.current_persona and analysis.confidence > 0.6:
                    session.current_persona = analysis.persona_recommendation
                    logger.info(f"[{session.session_id}] persona -> {analysis.persona_recommendation}")
        except Exception as e:
            logger.error(f"slow analysis failed: {e}")

    def _maybe_transition(self, session: CallSession, resistance_level: str, disc_primary: str):
        current = session.current_state
        if current == ConversationState.GOTV:
            if resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.OBJECTION_HANDLING)
            return
        if current == ConversationState.OPENING:
            if resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.DEESCALATION)
            else:
                session.transition_to(ConversationState.EXPLORATION)
            return
        if current == ConversationState.EXPLORATION:
            if session.exchange_count >= 3:
                session.transition_to(ConversationState.PROFILING)
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
            elif session.exchange_count >= 8:
                session.transition_to(ConversationState.OBJECTION_HANDLING)
            elif session.exchange_count >= 10:
                session.transition_to(ConversationState.SEED_PLANTING)
            return
        if current == ConversationState.OBJECTION_HANDLING:
            if resistance_level == "low":
                session.transition_to(ConversationState.PERSUASION)
            elif session.exchange_count >= 8:
                session.transition_to(ConversationState.SEED_PLANTING)
            return
        if current == ConversationState.COMMITMENT:
            if session.exchange_count >= 8 or resistance_level in ("high", "very_high"):
                session.transition_to(ConversationState.CLOSING)
            return

        if current == ConversationState.SEED_PLANTING:
            if session.exchange_count >= 9:
                session.transition_to(ConversationState.CLOSING)
            return

    def _calc_tts_speed(self, base_speed: float, state: ConversationState, slow_analysis=None) -> float:
        state_modifier = {
            ConversationState.OPENING: 1.00,
            ConversationState.EXPLORATION: 0.97,
            ConversationState.PROFILING: 0.95,
            ConversationState.PERSUASION: 1.05,
            ConversationState.COMMITMENT: 0.92,
            ConversationState.CLOSING: 0.90,
            ConversationState.OBJECTION_HANDLING: 0.95,
            ConversationState.SEED_PLANTING: 0.95,
            ConversationState.GOTV: 1.00,
            ConversationState.DEESCALATION: 0.85,
            ConversationState.AMPLIFICATION: 1.00,
        }
        speed = base_speed * state_modifier.get(state, 1.0)
        if slow_analysis and slow_analysis.suggested_pace_modifier:
            speed *= slow_analysis.suggested_pace_modifier
        return round(max(0.80, min(1.20, speed)), 2)

    def add_assistant_response(self, session_id: str, response: str):
        session = self.active_sessions.get(session_id)
        if session:
            session.conversation_history.append({"role": "assistant", "content": response})

    def get_session(self, session_id: str) -> Optional[CallSession]:
        return self.active_sessions.get(session_id)

    def end_session(self, session_id: str):
        """Clean up session — called when call ends."""
        session = self.active_sessions.pop(session_id, None)
        if session:
            self._dashboard_record_end(session_id, session.current_state.value)
            if self.whisper:
                self.whisper.on_session_end(session_id)

    # ── Dashboard helpers ──

    def _dashboard_record_start(self, session_id: str, voter_context):
        if not self._dashboard_enabled:
            return
        try:
            from ..dashboard.live_dashboard import record_call_start
            record_call_start(
                phone=getattr(voter_context, 'phone', session_id),
                name=getattr(voter_context, 'first_name', '') or '',
                support_score=getattr(voter_context, 'support_score', 0.5),
            )
        except Exception:
            pass

    def _dashboard_record_update(self, session_id: str, session: CallSession):
        if not self._dashboard_enabled:
            return
        try:
            from ..dashboard.live_dashboard import record_call_update
            record_call_update(
                phone=getattr(session.voter_context, 'phone', session_id) if session.voter_context else session_id,
                state=session.current_state.value,
                resistance=session.current_resistance,
                exchanges=session.exchange_count,
                persona=session.current_persona,
            )
        except Exception:
            pass

    def _dashboard_record_end(self, session_id: str, final_state: str):
        if not self._dashboard_enabled:
            return
        try:
            from ..dashboard.live_dashboard import record_call_end
            record_call_end(
                phone=session_id,
                result="completed",
                final_state=final_state,
            )
        except Exception:
            pass
