# Deploy

Run the orchestrator with `python -m src.main`. Run the worker with `PYTHONPATH=. python src/livekit_worker.py dev`. Railway uses `web: PYTHONPATH=. python src/livekit_worker.py start`. Copy `.env.example` to `.env` and provide secrets; never commit `.env`.
