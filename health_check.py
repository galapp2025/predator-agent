#!/usr/bin/env python3
"""
🏥 PREDATOR AGENT — HEALTH CHECK
═════════════════════════════════════════════════════
בדיקת חיבורים מהירה לפני דמו / בדיקת משקיעים.
בודק: Deepgram STT, Cartesia TTS, Groq/OpenAI LLM, Predator Pipeline.

הרצה: cd /home/user/predator-agent && python3 health_check.py
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _is_real(key: str) -> bool:
    if not key or len(key) < 20:
        return False
    if "xxx" in key.lower() or "xxxxxxxx" in key.lower():
        return False
    return True


def ok(msg): return f"{GREEN}✅ {msg}{RESET}"
def fail(msg): return f"{RED}❌ {msg}{RESET}"
def warn(msg): return f"{YELLOW}⚠️  {msg}{RESET}"
def info(msg): return f"{CYAN}ℹ️  {msg}{RESET}"


async def check_deepgram(api_key: str) -> bool:
    """Test Deepgram WebSocket connection."""
    try:
        import websockets
        url = "wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000"
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Token {api_key}"},
            close_timeout=3,
        ) as ws:
            # Send a small silent audio chunk
            silent = b'\x00' * 320  # 10ms of silence at 16kHz s16le
            await ws.send(silent)
            await ws.close()
        return True
    except Exception as e:
        print(f"   {RED}↳ {e}{RESET}")
        return False


async def check_cartesia(api_key: str) -> bool:
    """Test Cartesia TTS API."""
    try:
        import aiohttp
        headers = {
            "X-API-Key": api_key,
            "Cartesia-Version": "2024-06-30",
            "Content-Type": "application/json",
        }
        body = {
            "model_id": "sonic-3",
            "transcript": "שלום",
            "voice": {"mode": "id", "id": "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02"},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
            "language": "he",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.cartesia.ai/tts/bytes",
                headers=headers, json=body,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return len(data) > 100
                else:
                    print(f"   {RED}↳ HTTP {resp.status}{RESET}")
                    return False
    except Exception as e:
        print(f"   {RED}↳ {e}{RESET}")
        return False


async def check_groq(api_key: str) -> bool:
    """Test Groq LLM API."""
    try:
        import aiohttp
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "llama-3.3-70b-versatile",
            "temperature": 0.7,
            "max_tokens": 20,
            "messages": [{"role": "user", "content": "שלום, תגיד שלום בעברית"}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=body,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    return len(text) > 0
                else:
                    print(f"   {RED}↳ HTTP {resp.status}{RESET}")
                    return False
    except Exception as e:
        print(f"   {RED}↳ {e}{RESET}")
        return False


async def check_openai(api_key: str) -> bool:
    """Test OpenAI API."""
    try:
        import aiohttp
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4.1-mini",
            "temperature": 0.7,
            "max_tokens": 20,
            "messages": [{"role": "user", "content": "Say hello in Hebrew"}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers, json=body,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return len(data["choices"][0]["message"]["content"].strip()) > 0
                else:
                    print(f"   {RED}↳ HTTP {resp.status}{RESET}")
                    return False
    except Exception as e:
        print(f"   {RED}↳ {e}{RESET}")
        return False


async def check_pipeline() -> dict:
    """Test Predator pipeline locally."""
    from src.agent.predator import PredatorAgent
    from src.enrichment.voter_context import VoterContextBuilder
    from src.personas.persona_base import get_persona

    agent = PredatorAgent()
    builder = VoterContextBuilder()
    ctx = builder.build(
        first_name="בוחן", last_name="מערכת", city="תל אביב",
        street="רוטשילד", house_number="1",
        registered_branch="תל אביב", support_score=0.55,
        campaign_type="primaries",
    )
    session = agent.create_session("health-check", voter_context=ctx)
    result = await agent.process_voter_turn("health-check", "כן, שלום?")

    persona = get_persona(session.current_persona)
    agent.end_session("health-check")

    return {
        "persona": persona.name,
        "state": result["state"],
        "resistance": result["resistance"],
        "tactic": result.get("tactic", "-"),
        "disc": result["disc"],
        "tts_speed": result["tts_params"]["speed"],
        "prompt_chars": len(result["system_prompt"]),
    }


async def main():
    print()
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  🏥 PREDATOR AGENT — HEALTH CHECK{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print()

    dg_key = os.getenv("DEEPGRAM_API_KEY", "")
    cart_key = os.getenv("CARTESIA_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    claude_key = os.getenv("ANTHROPIC_API_KEY", "")

    results = {}

    # ── 1. Key validation ──
    print(f"{BOLD}🔑 שלב 1: בדיקת מפתחות{RESET}")
    print(f"   Deepgram:  {'✅' if _is_real(dg_key) else '❌'} ({len(dg_key)} תווים)")
    print(f"   Cartesia:  {'✅' if _is_real(cart_key) else '❌'} ({len(cart_key)} תווים)")
    print(f"   Groq:      {'✅' if _is_real(groq_key) else '❌ (לא הוגדר)'} ({len(groq_key)} תווים)")
    print(f"   OpenAI:    {'✅' if _is_real(openai_key) else '❌ (fallback)'} ({len(openai_key)} תווים)")
    print(f"   Claude:    {'✅' if _is_real(claude_key) else '❌ (fallback)'} ({len(claude_key)} תווים)")
    print()

    # ── 2. Deepgram STT ──
    print(f"{BOLD}📋 שלב 2: Deepgram STT (Hebrew){RESET}")
    if _is_real(dg_key):
        dg_ok = await check_deepgram(dg_key)
        print(f"   {ok('Deepgram STT — מחובר')}" if dg_ok else f"   {fail('Deepgram STT — נכשל')}")
        results["deepgram"] = dg_ok
    else:
        print(f"   {fail('אין מפתח Deepgram תקין')}")
        results["deepgram"] = False
    print()

    # ── 3. Cartesia TTS ──
    print(f"{BOLD}🗣 שלב 3: Cartesia TTS (Hebrew, Sonic-3){RESET}")
    if _is_real(cart_key):
        cart_ok = await check_cartesia(cart_key)
        print(f"   {ok('Cartesia TTS — עובד')}" if cart_ok else f"   {fail('Cartesia TTS — נכשל')}")
        results["cartesia"] = cart_ok
    else:
        print(f"   {fail('אין מפתח Cartesia תקין')}")
        results["cartesia"] = False
    print()

    # ── 4. LLM ──
    print(f"{BOLD}🧠 שלב 4: LLM{RESET}")
    llm_ok = False
    if _is_real(groq_key):
        g_ok = await check_groq(groq_key)
        print(f"   {ok('Groq (llama-3.3-70b) — עובד')}" if g_ok else f"   {fail('Groq — נכשל')}")
        llm_ok = g_ok
        results["groq"] = g_ok
    elif _is_real(openai_key):
        o_ok = await check_openai(openai_key)
        print(f"   {ok('OpenAI (GPT-4.1-mini) — עובד')}" if o_ok else f"   {fail('OpenAI — נכשל')}")
        llm_ok = o_ok
        results["openai"] = o_ok
    else:
        print(f"   {warn('אין LLM אמיתי — שימוש ב-fallback (תשובות מוכנות מראש)')}")
        llm_ok = True  # fallback works
    print()

    # ── 5. Predator Pipeline ──
    print(f"{BOLD}🔀 שלב 5: Predator Pipeline{RESET}")
    try:
        pipe = await check_pipeline()
        print(f"   {ok('צינור עובד — Persona=' + pipe['persona'] + ', State=' + pipe['state'] + ', Tactic=' + pipe['tactic'])}")
        print(f"      Resistance={pipe['resistance']}, DISC={pipe['disc']}, Prompt={pipe['prompt_chars']} תווים")
        results["pipeline"] = True
    except Exception as e:
        print(f"   {fail(f'צינור נכשל: {e}')}")
        results["pipeline"] = False
    print()

    # ── Summary ──
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  📊 סיכום{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print()

    all_ok = all(results.values())
    critical_ok = results.get("deepgram", False) and results.get("cartesia", False) and results.get("pipeline", False)

    if critical_ok and llm_ok:
        print(f"   {ok('המערכת מוכנה לדמו!')}")
        print()
        print(f"   להרצה:")
        print(f"   {CYAN}bash start_voice.sh{RESET}")
        print(f"   + פתח test_voice.html בדפדפן")
    elif critical_ok and not llm_ok:
        print(f"   {warn('STT + TTS + Pipeline עובדים. LLM בפייל-back.')}")
        print(f"   {info('תשובות מוכנות מראש — עובד חלק לבדיקה.')}")
    else:
        print(f"   {fail('יש בעיות שדורשות תיקון לפני הדמו.')}")
        for k, v in results.items():
            if not v:
                print(f"      - {k}: נכשל")

    print()
    print(f"{BOLD}{'='*60}{RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
