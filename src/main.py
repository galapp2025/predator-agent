"""
PREDATOR AGENT — Political Campaign Voice Agent
Dual-LLM: GPT-4.1-mini (שיחה) + Claude Sonnet (מודיעין)
LiveKit + Deepgram + Cartesia
"""

import os
import logging
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, JobContext, WorkerOptions
from livekit.plugins import deepgram, openai, cartesia, silero

from src.agent.predator import PredatorAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predator.main")

async def entrypoint(ctx: JobContext):
    logger.info(f"🎯 Room: {ctx.room.name}")
    await ctx.connect()

    vad = silero.VAD.load(activation_threshold=0.3)

    session = AgentSession(
        stt=deepgram.STT(
            model="deepgram/nova-3:multi",
            language="he"
        ),
        llm=openai.LLM(
            model="openai/gpt-4.1-mini",
            temperature=0.75,
            max_tokens=200
        ),
        tts=cartesia.TTS(
            model="cartesia/sonic-3",
            voice=os.getenv("CARTESIA_VOICE_MALE")
        ),
        vad=vad,
        preemptive_generation=True
    )

    agent = PredatorAgent(
        anthropic_key=os.getenv("ANTHROPIC_API_KEY")
    )

    await session.start(room=ctx.room, agent=agent)

if __name__ == "__main__":
    agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
