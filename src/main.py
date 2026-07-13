"""Predator Agent — Main Entry Point"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("predator-main")

CONFIG = {
    "livekit_url": os.getenv(
        "LIVEKIT_URL", "wss://predator-gnzrgpca.livekit.cloud"
    ),
    "deepgram_api_key": os.getenv("DEEPGRAM_API_KEY"),
    "cartesia_api_key": os.getenv("CARTESIA_API_KEY"),
    "openai_api_key": os.getenv("OPENAI_API_KEY"),
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
    "groq_api_key": os.getenv("GROQ_API_KEY"),
    "cartesia_voice_male": os.getenv(
        "CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02"
    ),
    "cartesia_voice_female": os.getenv(
        "CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f"
    ),
}


def build_agent():
    from .agent.predator import PredatorAgent

    return PredatorAgent(
        anthropic_api_key=CONFIG["anthropic_api_key"],
        openai_api_key=CONFIG["openai_api_key"],
    )


async def dev_mode():
    from .enrichment.voter_context import VoterContextBuilder

    print("=" * 60)
    print("Predator Agent — DEV MODE")
    print("=" * 60)
    agent = build_agent()
    builder = VoterContextBuilder()
    ctx = builder.build(
        first_name="רחל",
        last_name="לוי",
        city="פתח תקווה",
        street="הרצל",
        house_number="12",
        registered_branch="פתח תקווה",
        support_score=0.62,
        campaign_type="primaries",
    )
    session = agent.create_session("test_session_1", voter_context=ctx)
    print(
        f"\nSession created: persona={session.current_persona}, "
        f"state={session.current_state.value}, support={session.support_score}"
    )

    voter_inputs = [
        "כן, מי זה?",
        "לא, אין לי זמן עכשיו",
        "תקשיב, אני באמת עסוק",
        "אולי. מה אתה רוצה?",
        "אני לא יודע, אני חושב שלא אצביע בכלל",
        "אה, באמת? 30 קולות?",
        "טוב, בוא נדבר. תכלס, מה המועמד שלכם עשה?",
        "אני לא בטוח שזה משנה. אתם כולם אותו דבר.",
        "תקשיב, אתה נשמע הגון. אני אחשוב על זה.",
    ]

    for i, voter_text in enumerate(voter_inputs, 1):
        print(f"\n--- Exchange {i} ---")
        print(f"בוחר: {voter_text}")
        result = await agent.process_voter_turn("test_session_1", voter_text)
        if "error" in result:
            print(f"ERROR: {result['error']}")
            continue
        print(
            f"  State: {result['state']}, Resistance: {result['resistance']}, "
            f"Persona: {result['persona']}"
        )
        print(
            f"  Tactic: {result.get('tactic')}, "
            f"TTS speed: {result['tts_params']['speed']}"
        )
        print(f"  System prompt: {len(result['system_prompt'])} chars")
        agent.add_assistant_response("test_session_1", f"[reply {i}]")

    print("\n" + "=" * 60)
    print("Test complete")
    print(f"Final state: {session.current_state.value}")
    print(f"Exchanges: {session.exchange_count}")
    print("=" * 60)


def main():
    mode = os.getenv("AGENT_MODE", "dev")
    print(f"\n[Predator Agent] mode={mode}")
    print(f"[Config] livekit={CONFIG['livekit_url']}")
    print(f"[Config] deepgram={'OK' if CONFIG['deepgram_api_key'] else 'MISSING'}")
    print(f"[Config] cartesia={'OK' if CONFIG['cartesia_api_key'] else 'MISSING'}")
    print(f"[Config] groq={'OK' if CONFIG['groq_api_key'] else 'MISSING'}")
    print(f"[Config] openai={'OK' if CONFIG['openai_api_key'] else 'MISSING'} (fallback)")
    print(f"[Config] anthropic={'OK' if CONFIG['anthropic_api_key'] else 'MISSING'} (slow)\n")

    if mode == "dev":
        asyncio.run(dev_mode())
    elif mode == "queue-start":
        from .telephony.call_queue import CallQueue
        from .telephony.outbound_dialer import LeadLoader

        q = CallQueue(agent=None)
        leads = LeadLoader(os.getenv("LEADS_CSV", "data/leads.csv")).load_sorted_by_persuadability()
        for lead in leads:
            q.enqueue_outbound(lead)
        print(f"queue-start: enqueued {len(leads)} leads")
        print(q.stats() if hasattr(q, "stats") else f"size={len(q._queue)}")
    elif mode == "campaign":
        from .agent.predator import PredatorAgent
        from .telephony.call_queue import CallQueue
        from .telephony.outbound_dialer import OutboundDialer

        async def _campaign():
            os.environ.setdefault("DIALER_FORCE", "1")
            agent = PredatorAgent()
            queue = CallQueue(agent=agent)
            dialer = OutboundDialer(agent=agent, queue=queue)
            records = await dialer.run_campaign_from_csv()
            print(f"campaign done: {len(records)} records")
            for r in records[:3]:
                print(f"  {r.full_name} → {r.result}")

        asyncio.run(_campaign())
    elif mode == "voice":
        print("voice mode — run: PYTHONPATH=. python3 live_voice_server.py")
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
