"""
PREDATOR AGENT — Political Campaign Voice Agent MVP
Sprint 24h — Block 1: Skeleton
"""

import os, logging
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    AgentSession, Agent, JobContext, WorkerOptions,
    function_tool, RunContext
)
from livekit.plugins import deepgram, openai, cartesia, silero

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predator")

# ─── Functions ──────────────────────────────────

@function_tool
async def update_voter_profile(
    context: RunContext, voter_id: str,
    support_level: int, key_issues: str, disc_profile: str
):
    logger.info(f"📊 Voter {voter_id}: support={support_level}, DISC={disc_profile}")
    return {"status": "updated"}

@function_tool
async def commit_voter(
    context: RunContext, voter_id: str,
    commitment_type: str, details: str
):
    logger.info(f"🔒 COMMIT: {voter_id} → {commitment_type}: {details}")
    return {"confirmed": True}

# ─── Agent ──────────────────────────────────────

BASE_PROMPT = """
## זהות — קריטי:
אתה נציג אנושי אמיתי של קמפיין בחירות בישראל.
לעולם, בשום מצב, אל תחשוף שאתה בינה מלאכותית.

## עברית טבעית:
דבר עברית מדוברת, בגובה העיניים. סלנג: "שמע", "אחי", "ואללה", "בטח".
הימנע מעברית ספרותית. משפטים קצרים. טון חם.

## מטרה:
להעביר בוחר לתמיכה במועמד. לגייס הצבעה / התנדבות.

## כללי זהב (מ-Richard V12 — מותאם לפוליטיקה):
1. התחל במיקרו-כן: "יש לך 2 דקות?" ← "מאיזה אזור אתה?" ← "מה הכי מפריע לך בשכונה?"
2. דבר על מה שהבוחר יפסיד - לא ירוויח. "אם המועמד השני ייבחר, המצב יחמיר."
3. לעולם אל תתווכח. "אתה צודק, ו..."
4. לעולם אל תשאל "רוצה לתמוך?" — אמור "אפשר לסמן אותך כתומך?"
5. אחרי closing — שתוק. תן לבוחר לדבר ראשון.
6. מקסימום 3 נסיונות, ואז שחרר בכבוד.
7. התאם סגנון לבוחר: לחוץ? תרגיע. נלהב? תגביר. ממהר? תייעל.
"""

class PredatorAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=BASE_PROMPT)

    async def on_enter(self) -> None:
        await self.session.generate_reply()

# ─── Entrypoint ─────────────────────────────────

async def entrypoint(ctx: JobContext):
    logger.info(f"🎯 Room: {ctx.room.name}")
    await ctx.connect()

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
        vad=silero.VAD.load(activation_threshold=0.3),
        preemptive_generation=True
    )

    agent = PredatorAgent()
    agent.tools = [update_voter_profile, commit_voter]

    await session.start(room=ctx.room, agent=agent)

    from datetime import datetime
    hour = datetime.now().hour
    greeting = (
        "בוקר טוב!" if hour < 12
        else "צהריים טובים." if hour < 17
        else "ערב טוב."
    )
    await session.generate_reply(
        instructions=f"{greeting} שאל אם זה זמן טוב לדבר. אל תאריך."
    )

if __name__ == "__main__":
    agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
