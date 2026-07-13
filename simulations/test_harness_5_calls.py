"""Test harness — 5 שיחות מדומות לאימות pipeline + DISC persona fallback."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.predator import PredatorAgent
from src.enrichment.voter_context import VoterContextBuilder
from src.profile.disc_classifier import classify


SCENARIOS = [
    {
        "name": "רחל — התנגדות→פתיחה",
        "voter": dict(
            first_name="רחל",
            last_name="לוי",
            city="פתח תקווה",
            street="הרצל",
            house_number="12",
            support_score=0.62,
        ),
        "turns": [
            "כן, מי זה?",
            "אין לי זמן עכשיו",
            "אולי. מה אתה רוצה?",
            "טוב, תגיד בקצרה",
            "אוקיי, אחשוב על זה",
        ],
    },
    {
        "name": "אברהם — D רצוף (fallback)",
        "voter": dict(
            first_name="אברהם",
            last_name="כהן",
            city="פתח תקווה",
            street="ז׳בוטינסקי",
            house_number="45",
            support_score=0.78,
        ),
        # מרקרים חזקים של D — 4 תורות רצופות לתפוס slow_llm ב-exchange זוגי
        "turns": [
            "תקצר. בוא לעניין עכשיו.",
            "תכלס תגיד לי מהר מה אתה רוצה. אני מחליט.",
            "מספיק דיבורים. קדימה, תחליט ותגיד לי ישר.",
            "בוא נעשה את זה עכשיו. תגיד לי ישר מה הצעד.",
            "סבבה, אגיע ביום שלישי בערב",
        ],
    },
    {
        "name": "מיכל — I חם",
        "voter": dict(
            first_name="מיכל",
            last_name="שמש",
            city="בת ים",
            street="בן גוריון",
            house_number="8",
            support_score=0.55,
        ),
        "turns": [
            "וואלה מי זה?",
            "מעניין אותי, תספר",
            "אחלה, באמת מעולה מה שאתם עושים",
            "כיף לשמוע, אני אוהבת את זה",
            "יאללה אני אשמח להגיע",
        ],
    },
    {
        "name": "יוסף — C נתונים",
        "voter": dict(
            first_name="יוסף",
            last_name="אברהם",
            city="פתח תקווה",
            street="חיים עוזר",
            house_number="23",
            support_score=0.31,
        ),
        "turns": [
            "מי אתה ומה המספרים?",
            "תראה לי נתונים. כמה אחוזים?",
            "לפי מה אתה אומר? בדקת?",
            "מתי בדיוק הקלפי נפתחת?",
            "אוקיי, אבדוק ואחליט",
        ],
    },
    {
        "name": "שרה — Battle AI",
        "voter": dict(
            first_name="שרה",
            last_name="גולדברג",
            city="רמת השרון",
            street="הנדיב",
            house_number="67",
            support_score=0.68,
        ),
        "turns": [
            "שלום?",
            "אתה נשמע כמו מחשב",
            "בוט. רובוט. בינה מלאכותית.",
            "טוב נו, מה רצית?",
            "סבבה, תזכיר לי מחר",
        ],
    },
]


async def run_one(agent: PredatorAgent, idx: int, scenario: dict) -> dict:
    builder = VoterContextBuilder()
    ctx = builder.build(**scenario["voter"], campaign_type="primaries")
    sid = f"sim-{idx}-{scenario['voter']['first_name']}"
    session = agent.create_session(sid, voter_context=ctx)
    start_persona = session.current_persona
    turns_out = []

    for text in scenario["turns"]:
        out = await agent.process_voter_turn(sid, text)
        turns_out.append(
            {
                "text": text,
                "disc": out.get("disc"),
                "persona": out.get("persona"),
                "state": out.get("state"),
                "resistance": out.get("resistance"),
                "battle": bool(out.get("battle")),
            }
        )
        agent.add_assistant_response(sid, f"[sim] מבין. נמשיך — {out.get('state')}.")

    end = agent.get_session(sid)
    discs = [classify(t).primary for t in scenario["turns"]]
    return {
        "name": scenario["name"],
        "session_id": sid,
        "start_persona": start_persona,
        "end_persona": end.current_persona if end else None,
        "end_state": end.current_state.value if end else None,
        "disc_path": discs,
        "turns": turns_out,
        "exchanges": end.exchange_count if end else 0,
    }


async def main() -> int:
    print("=" * 60)
    print("Predator — 5-call simulation harness")
    print("=" * 60)
    agent = PredatorAgent()
    results = []
    for i, sc in enumerate(SCENARIOS, start=1):
        print(f"\n[{i}/5] {sc['name']}")
        r = await run_one(agent, i, sc)
        results.append(r)
        switched = r["start_persona"] != r["end_persona"]
        print(
            f"  persona {r['start_persona']} → {r['end_persona']}"
            f"{' (switched)' if switched else ''}"
            f" | state={r['end_state']} | discs={r['disc_path']}"
        )
        for t in r["turns"]:
            flag = " ⚔" if t["battle"] else ""
            print(
                f"    · {t['text'][:40]:40s}  "
                f"DISC={t['disc']} P={t['persona']} S={t['state']} R={t['resistance']}{flag}"
            )

    d_case = results[1]
    last3 = d_case["disc_path"][:3]
    if len(set(last3)) == 1:
        print("\n✓ DISC×3 consistency on call #2:", last3[0])
        if d_case["end_persona"] == last3[0]:
            print("✓ persona fallback applied →", d_case["end_persona"])
        else:
            print(
                "· end_persona=",
                d_case["end_persona"],
                "(fallback רץ כש-slow_llm חלש/חסר)",
            )

    print("\n" + "=" * 60)
    print(f"DONE — {len(results)} calls simulated")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
