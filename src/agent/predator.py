"""
Predator Agent — Dual-LLM + DISC + Personas + Tactics + State Machine
"""

import asyncio
import logging
import random
from typing import List, Optional, Dict

from livekit.agents import Agent, RunContext, function_tool
from src.llm.slow_llm import PsychologicalAnalyzer
from src.llm.prompt_builder import build_full_prompt
from src.profile.disc_classifier import classify_disc
from src.personas.persona_base import DiscType, get_persona, get_style_instructions
from src.persuasion.tactics import get_tactic_instructions, get_tactic_by_profile
from src.persuasion.resistance_meter import measure_resistance
from src.state_machine.states import Phase, ConversationState

logger = logging.getLogger("predator.agent")


@function_tool
async def update_voter_profile(
    context: RunContext,
    voter_id: str = "",
    support_level: int = 0,
    key_issues: str = "",
    disc_profile: str = ""
):
    logger.info(f"📊 Voter: support={support_level}, DISC={disc_profile}, issues={key_issues}")
    return {"updated": True}


@function_tool
async def commit_voter(
    context: RunContext,
    voter_id: str = "",
    commitment_type: str = "",
    details: str = ""
):
    logger.info(f"🔒 COMMIT: {commitment_type} — {details}")
    return {"confirmed": True, "type": commitment_type}


@function_tool
async def escalate_to_human(
    context: RunContext,
    voter_id: str = "",
    reason: str = "",
    summary: str = ""
):
    logger.warning(f"🟡 HANDOFF: {reason}")
    return {"handoff": True}


class PredatorAgent(Agent):
    def __init__(self, anthropic_key: str) -> None:
        self.analyzer = PsychologicalAnalyzer(api_key=anthropic_key)
        self.state = ConversationState()

        self.transcript_buffer: List[str] = []
        self.analysis: Optional[Dict] = None
        self.analysis_task: Optional[asyncio.Task] = None
        self.exchange_count = 0
        self.current_disc: Optional[DiscType] = None
        self.current_resistance: float = 0.5
        self.prev_resistance: float = 0.5

        super().__init__(
            instructions=build_full_prompt(),
            tools=[update_voter_profile, commit_voter, escalate_to_human],
        )

    async def on_enter(self) -> None:
        self.exchange_count = 0
        self.transcript_buffer = []
        self.state = ConversationState()

        opener = random.choice([
            "בוקר טוב! שמח שהצלחתי לתפוס.",
            "צהריים טובים. מקווה שהיום זורם.",
            "ערב טוב. סליחה על השעה.",
        ])
        await self.session.generate_reply(
            instructions=f"{opener} שאל אם זה זמן טוב לדבר. קצר."
        )

    async def on_user_speech_ended(self, text: str) -> None:
        self.transcript_buffer.append(f"בוחר: {text}")
        self.exchange_count += 1

        # 1. מדידת התנגדות מיידית
        self.prev_resistance = self.current_resistance
        self.current_resistance = measure_resistance(text)
        logger.info(
            f"💬 #{self.exchange_count}: resistance={self.current_resistance:.2f}, "
            f"phase={self.state.current.value}"
        )

        # 2. DISC מהיר — מקומי, בלי API
        disc, scores = classify_disc(text)
        total = sum(scores.values())
        if total >= 2:
            disc_type = DiscType(disc)
            if disc_type != self.current_disc:
                self.current_disc = disc_type
                persona = get_persona(disc_type)
                logger.info(f"🎭 DISC → {disc} ({persona.name}), scores={scores}")

        # 3. מעבר מצב
        if self.current_resistance > 0.8:
            self.state.transition("resistant")
        elif self.current_resistance < 0.2:
            self.state.transition("convinced")
        elif self.current_resistance > self.prev_resistance + 0.3:
            self.state.transition("hostile")
        else:
            self.state.transition("neutral")

        # 4. בדיקות קריטיות
        if self.state.should_handoff():
            logger.warning("🟡 HANDOFF TRIGGERED")
            await self.session.generate_reply(
                instructions="התנצל והצע להעביר לנציג אנושי. קרא ל-escalate_to_human."
            )
            return

        if self.state.should_release():
            logger.info("🔚 Release — 3 attempts, no commit")
            await self.session.generate_reply(
                instructions="שחרר בכבוד. 'סבבה, תודה על הזמן. אם תשנה את דעתך — אנחנו פה.'"
            )
            return

        # 5. ניתוח קלוד — כל 2 חילופים
        if self.exchange_count >= 2 and len(self.transcript_buffer) >= 4:
            if not self.analysis_task or self.analysis_task.done():
                transcript = "\n".join(self.transcript_buffer[-12:])
                self.analysis_task = asyncio.create_task(
                    self._run_analysis(transcript)
                )

        # 6. עדכון System Prompt דינמי
        self._update_dynamic_prompt()

    def _update_dynamic_prompt(self):
        """בונה ומעדכן System Prompt דינמי"""
        blocks = []

        # פרסונה
        if self.current_disc:
            persona = get_persona(self.current_disc)
            blocks.append(get_style_instructions(persona))

        # שלב
        blocks.append(f"## 📍 שלב נוכחי: {self.state.current.value}")
        blocks.append(self.state.phase_instructions())

        # טקטיקה
        disc_str = self.current_disc.value if self.current_disc else "S"
        tactic = get_tactic_by_profile(disc_str, self.current_resistance)
        blocks.append(get_tactic_instructions(tactic))

        # התנגדות
        blocks.append(f"## 📏 התנגדות נוכחית: {self.current_resistance:.2f}/1.0")

        # ניתוח קלוד (אם קיים)
        if self.analysis:
            blocks.append(self.analyzer.build_prompt_update())

        update = "\n\n".join(blocks)
        self.session.update_instructions(
            instructions=build_full_prompt(update)
        )

    async def _run_analysis(self, transcript: str):
        try:
            self.analysis = await self.analyzer.analyze(transcript)
            # Claude overrides DISC if different
            if self.analysis:
                claude_disc = self.analysis.get("disc_profile")
                if claude_disc and claude_disc != (self.current_disc.value if self.current_disc else None):
                    self.current_disc = DiscType(claude_disc)

            self._update_dynamic_prompt()
            logger.info(
                f"🧠 Claude: DISC={self.analysis.get('disc_profile') if self.analysis else 'N/A'}, "
                f"Tactic={self.analysis.get('recommended_tactic') if self.analysis else 'N/A'}"
            )

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
