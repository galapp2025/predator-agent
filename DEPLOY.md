# Predator Agent — Deployment Guide

## Stack
- **Voice**: LiveKit (real-time) + Deepgram Nova-3 (STT) + Cartesia Sonic-3 (TTS)
- **LLM**: GPT-4.1-mini (fast/streaming) + Claude Sonnet 4 (slow/strategic)
- **Logic**: Python 3.12+

## Deploy to Railway

1. **Push to GitHub**:
   ```bash
   cd predator-agent
   git init && git add . && git commit -m "init"
   git remote add origin <your-repo>
   git push -u origin main
   ```

2. **Railway Setup**:
   - New Project → Deploy from GitHub
   - Select repo
   - Add environment variables from `.env.example`
   - Railway will auto-detect Python and run `python -m src.main`

3. **Environment Variables** (set in Railway dashboard):
   - `LIVEKIT_URL`
   - `DEEPGRAM_API_KEY`
   - `CARTESIA_API_KEY`
   - `OPENAI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `CARTESIA_VOICE_MALE` / `CARTESIA_VOICE_FEMALE`

## Local Dev

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in keys
python -m src.main    # dev mode (9-exchange smoke test)
```

## Modes

- `AGENT_MODE=dev` — smoke test
- `AGENT_MODE=queue-start` — load `data/leads.csv` and dial
- `AGENT_MODE=campaign` — full outbound campaign

## Architecture

```
src/
├── agent/predator.py          # Main orchestrator (sessions, state, LLM)
├── llm/
│   ├── prompt_builder.py      # V2 HUMAIN Hebrew prompt (6100+ chars)
│   └── slow_llm.py            # Claude Sonnet 4 strategic analyzer
├── personas/persona_base.py   # 4 DISC personas (אלון/מיה/דוד/רונית)
├── persuasion/
│   ├── tactics.py             # 13 tactics (8 classical + 5 black_psych)
│   └── resistance_meter.py    # 3-tier resistance detection
├── state_machine/states.py    # 11 states with transitions
├── profile/disc_classifier.py # Hebrew DISC keyword detector
├── enrichment/voter_context.py # 5-dim pre-call enrichment
└── telephony/                 # SIP/outbound/inbound/queue stubs
```

## Key Design Decisions

- **Natural Hebrew**: `HEBREW_NATIVE_RULES` + `SPEECH_PATTERN` injected per turn
- **Zero Latency**: streaming, LATENCY_FILLERS, max_tokens=120, preemptive generation
- **Black Psychology**: 5 advanced tactics (micro_yes_ladder, limited_choice, emotional_time_travel, debt_creation, fear_sequencing)
- **DISC Adaptation**: persona + TTS speed change per voter profile
- **Resistance-Aware**: state + tactic + speed adapt in real-time
