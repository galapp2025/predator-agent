"""LiveKit Worker — STT/LLM/TTS דרך PredatorAgent instructions דינמיים"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions
from livekit.plugins import cartesia, deepgram, openai, silero

from src.agent.predator import PredatorAgent, LLM_HEBREW_PARAMS
from src.llm.prompt_builder import PromptBuilder
from src.personas.persona_base import get_tts_params

load_dotenv()
logger = logging.getLogger("livekit-worker")


class LiveKitPredatorAgent(Agent):
    """Agent עם פרומפט מלא מ-Predator (מתעדכן לפי session אם קיים)."""

    def __init__(self, instructions: str | None = None):
        super().__init__(instructions=instructions or PromptBuilder().build())


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    # Orchestrator — יוצר session לחיבור DISC/state/tactics לעתיד (metadata room)
    predator = PredatorAgent()
    session_id = f"lk-{ctx.room.name}"
    call_session = predator.create_session(session_id)
    tts = get_tts_params(call_session.current_persona)
    instructions = PromptBuilder().build(
        persona_disc=call_session.current_persona,
        state=call_session.current_state.value,
        resistance_level="medium",
        exchange_number=1,
    )

    voice = tts.get("voice_id") or os.getenv(
        "CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02"
    )
    lk_session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="he"),
        llm=openai.LLM(
            # LiveKit path: OpenAI plugin. Voice server uses Groq→OpenAI via FastLLM.
            model=os.getenv("OPENAI_MODEL", LLM_HEBREW_PARAMS.get("fallback_model", "gpt-4.1-mini")),
            temperature=LLM_HEBREW_PARAMS["temperature"],
        ),
        tts=cartesia.TTS(
            model="sonic-3",
            language="he",
            voice=voice,
        ),
        vad=silero.VAD.load(),
    )
    logger.info(
        "LiveKit room=%s persona=%s state=%s",
        ctx.room.name,
        call_session.current_persona,
        call_session.current_state.value,
    )
    await lk_session.start(
        room=ctx.room,
        agent=LiveKitPredatorAgent(instructions=instructions),
    )


if __name__ == "__main__":
    agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
