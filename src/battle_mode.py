"""BATTLE MODE — מבחן אש מול טסטר מקצועי
שימוש: PYTHONPATH=. python3 -m src.battle_mode

הטסטר מקליד בעברית. הסוכן מגיב בכל הצינור:
DISC ← State Machine ← Tactic ← Resistance ← TTS Params ← System Prompt
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("battle")

from dotenv import load_dotenv
load_dotenv()

from src.agent.predator import PredatorAgent
from src.enrichment.voter_context import VoterContextBuilder
from src.personas.persona_base import get_persona


# ── Tester Identity ──────────────────────────────────────
TESTER_NAME = "ראש צוות בדיקה"
TESTER_CONTEXT = {
    "first_name": "בוחן",
    "last_name": "מקצועי",
    "city": "תל אביב",
    "street": "רוטשילד",
    "house_number": "1",
    "registered_branch": "תל אביב",
    "support_score": 0.35,
    "campaign_type": "primaries",
    "gender_hint": "male",
}


def banner():
    print()
    print("=" * 60)
    print("   🎯 PREDATOR AGENT — BATTLE MODE")
    print("   מבחן אש: טסטר מקצועי מול הסוכן")
    print("=" * 60)
    print()
    print("הטסטר (אתה) — הקלד בעברית. ENTER = שליחה.")
    print("הסוכן — מגיב דרך כל הצינור: DISC ← State ← Tactic ← TTS")
    print()
    print("פקודות מיוחדות:")
    print("  /state   — הצג מצב נוכחי")
    print("  /history — הצג היסטוריית שיחה")
    print("  /prompt  — הצג system prompt אחרון")
    print("  /tts     — הצג פרמטרי TTS אחרונים")
    print("  /reset   — אפס שיחה והתחל מחדש")
    print("  /quit    — יציאה")
    print("  /help    — פקודות")
    print()


def format_state(agent, session_id):
    session = agent.get_session(session_id)
    if not session:
        return "אין session"
    p = get_persona(session.current_persona)
    return (
        f"\n┌── מצב נוכחי ─────────────────────────────\n"
        f"│ פרסונה:    {p.name} ({session.current_persona})\n"
        f"│ State:     {session.current_state.value}\n"
        f"│ התנגדות:   {session.current_resistance}\n"
        f"│ טקטיקה:    {session.current_tactic or 'אין'}\n"
        f"│ תמיכה:     {session.support_score:.2f}\n"
        f"│ חילופים:   {session.exchange_count}\n"
        f"│ TTS speed: {p.speed:.2f} (base)\n"
        f"│ TTS stab:  {p.stability:.2f}\n"
        f"│ TTS sim:   {p.similarity:.2f}\n"
        f"└──────────────────────────────────────────\n"
    )


def format_history(agent, session_id):
    session = agent.get_session(session_id)
    if not session or not session.conversation_history:
        return "אין היסטוריה"
    lines = ["\n┌── היסטוריית שיחה ────────────────────────"]
    for i, msg in enumerate(session.conversation_history, 1):
        role = "🧪 טסטר" if msg["role"] == "user" else "🤖 סוכן"
        content = msg["content"][:80] + ("..." if len(msg["content"]) > 80 else "")
        lines.append(f"│ {i}. {role}: {content}")
    lines.append("└──────────────────────────────────────────\n")
    return "\n".join(lines)


async def battle():
    banner()

    agent = PredatorAgent()
    builder = VoterContextBuilder()
    ctx = builder.build(
        first_name=TESTER_CONTEXT["first_name"],
        last_name=TESTER_CONTEXT["last_name"],
        city=TESTER_CONTEXT["city"],
        street=TESTER_CONTEXT["street"],
        house_number=TESTER_CONTEXT["house_number"],
        registered_branch=TESTER_CONTEXT["registered_branch"],
        support_score=TESTER_CONTEXT["support_score"],
        campaign_type=TESTER_CONTEXT["campaign_type"],
    )

    session_id = f"battle-{int(datetime.now().timestamp())}"
    session = agent.create_session(session_id, voter_context=ctx)

    print(f"🎭 פרסונה התחלתית: {get_persona(session.current_persona).name}")
    print(f"📊 ציון תמיכה:      {session.support_score:.2f}")
    print(f"🆔 Session:         {session_id}")
    print()
    print("הסוכן מוכן. הטסטר — דבר.")
    print("-" * 60)

    last_result = None

    while True:
        try:
            user_input = input("\n🧪 אתה: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 להתראות.")
            break

        if not user_input:
            continue

        # Commands
        if user_input.startswith("/"):
            cmd = user_input[1:].lower().split()[0]
            if cmd == "quit" or cmd == "exit":
                print("👋 להתראות.")
                break
            elif cmd == "help":
                banner()
                continue
            elif cmd == "state":
                print(format_state(agent, session_id))
                continue
            elif cmd == "history":
                print(format_history(agent, session_id))
                continue
            elif cmd == "prompt":
                if last_result:
                    prompt = last_result.get("system_prompt", "")
                    print(f"\n┌── System Prompt ({len(prompt)} תווים) ───")
                    print(prompt[:3000])
                    if len(prompt) > 3000:
                        print(f"... ({len(prompt) - 3000} תווים נוספים)")
                    print("└──────────────────────────────────────\n")
                else:
                    print("אין prompt עדיין. שלח הודעה ראשונה.")
                continue
            elif cmd == "tts":
                if last_result:
                    tts = last_result.get("tts_params", {})
                    llm = last_result.get("llm_params", {})
                    print(f"\n┌── TTS Params ──────────────────────────")
                    for k, v in tts.items():
                        print(f"│ {k}: {v}")
                    print(f"├── LLM Params ──────────────────────────")
                    for k, v in llm.items():
                        print(f"│ {k}: {v}")
                    print("└──────────────────────────────────────\n")
                else:
                    print("אין TTS params עדיין. שלח הודעה ראשונה.")
                continue
            elif cmd == "reset":
                session_id = f"battle-{int(datetime.now().timestamp())}"
                session = agent.create_session(session_id, voter_context=ctx)
                last_result = None
                print(f"\n🔄 שיחה חדשה. Session: {session_id}")
                print(f"🎭 פרסונה: {get_persona(session.current_persona).name}")
                continue
            else:
                print(f"פקודה לא מוכרת: {cmd}. /help לעזרה.")
                continue

        # Process voter turn
        print("⏳ מעבד...", end="\r")
        result = await agent.process_voter_turn(session_id, user_input)
        last_result = result

        if "error" in result:
            print(f"\n❌ שגיאה: {result['error']}")
            continue

        # Display response summary
        p = get_persona(result["persona"])
        print(f"\r🤖 סוכן ({p.name}-{result['persona']}): ", end="")
        print(f"[state={result['state']}, resistance={result['resistance']}, tactic={result.get('tactic', 'אין')}]")
        print(f"   ⚡ TTS speed={result['tts_params']['speed']:.2f} stability={result['tts_params']['stability']:.2f}")
        print(f"   📝 System prompt: {len(result['system_prompt'])} תווים")


def main():
    asyncio.run(battle())


if __name__ == "__main__":
    main()
