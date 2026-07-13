import os
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent,AgentSession,JobContext,WorkerOptions
from livekit.plugins import cartesia,deepgram,openai,silero
from src.llm.prompt_builder import PromptBuilder
load_dotenv()
class LiveKitPredatorAgent(Agent):
 def __init__(self):super().__init__(instructions=PromptBuilder().build())
async def entrypoint(ctx:JobContext):
 await ctx.connect();session=AgentSession(stt=deepgram.STT(model="nova-3",language="he"),llm=openai.LLM(model=os.getenv("OPENAI_MODEL","gpt-4.1-mini")),tts=cartesia.TTS(model="sonic-3",language="he",voice=os.getenv("CARTESIA_VOICE_MALE","ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")),vad=silero.VAD.load());await session.start(room=ctx.room,agent=LiveKitPredatorAgent())
if __name__=="__main__":agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
