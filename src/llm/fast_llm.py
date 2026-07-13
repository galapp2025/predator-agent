"""Fast LLM — שיחה בזמן אמת.

סדר עדיפות:
1. Groq llama-3.3-70b-versatile (עברית טבעית)
2. OpenAI (fallback)

הגנות מול Groq TPM/413:
- חיתוך system prompt ל-10K תווים
- cooldown 30s אחרי 413 / rate_limit
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("fast-llm")

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

GROQ_MAX_PROMPT_CHARS = int(os.getenv("GROQ_MAX_PROMPT_CHARS", "10000"))
GROQ_COOLDOWN_SEC = float(os.getenv("GROQ_COOLDOWN_SEC", "30"))

# module-level cooldown shared across FastLLM instances in-process
_groq_cooldown_until = 0.0


def _truncate_prompt(system_prompt: str, limit: int = GROQ_MAX_PROMPT_CHARS) -> str:
    if len(system_prompt) <= limit:
        return system_prompt
    # שמור את הסוף (RUNTIME/FINAL) — שם ההוראות התפעוליות
    head = system_prompt[: limit // 3]
    tail = system_prompt[-(limit - len(head) - 80) :]
    return (
        head
        + "\n\n[…prompt truncated for Groq TPM…]\n\n"
        + tail
    )


def _is_groq_capacity_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(
        x in msg
        for x in (
            "413",
            "rate_limit",
            "tokens per minute",
            "request too large",
            "tpm",
        )
    )


class FastLLM:
    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        temperature: float = 0.82,
        max_tokens: int = 150,
        top_p: float = 0.92,
        groq_model: Optional[str] = None,
        openai_model: Optional[str] = None,
    ):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.groq_model = groq_model or GROQ_MODEL
        self.openai_model = openai_model or OPENAI_MODEL

    @property
    def provider(self) -> str:
        if self.groq_api_key and time.time() >= _groq_cooldown_until:
            return "groq"
        if self.openai_api_key:
            return "openai"
        if self.groq_api_key:
            return "groq"  # only option, even if cooling down
        return "none"

    async def reply(
        self,
        system_prompt: str,
        user_text: str,
        http: aiohttp.ClientSession,
        timeout_sec: float = 12.0,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        global _groq_cooldown_until

        truncated = _truncate_prompt(system_prompt, GROQ_MAX_PROMPT_CHARS)
        if len(truncated) != len(system_prompt):
            logger.info(
                "prompt truncated %d → %d chars for Groq TPM",
                len(system_prompt),
                len(truncated),
            )

        messages: List[Dict[str, str]] = [{"role": "system", "content": truncated}]
        if history:
            messages.extend(history[-8:])
        messages.append({"role": "user", "content": user_text})

        now = time.time()
        in_cooldown = now < _groq_cooldown_until
        use_groq = bool(self.groq_api_key) and not in_cooldown

        if in_cooldown and self.groq_api_key:
            logger.info(
                "Groq cooldown %.0fs left — OpenAI fallback",
                _groq_cooldown_until - now,
            )

        if use_groq:
            try:
                text = await self._chat(
                    http,
                    GROQ_URL,
                    self.groq_api_key,
                    self.groq_model,
                    messages,
                    timeout_sec,
                )
                if text:
                    logger.info("fast_llm provider=groq chars=%d", len(text))
                    return text
            except Exception as e:
                if _is_groq_capacity_error(e):
                    _groq_cooldown_until = time.time() + GROQ_COOLDOWN_SEC
                    logger.warning(
                        "Groq capacity error — cooldown %ss, fallback OpenAI (%s)",
                        int(GROQ_COOLDOWN_SEC),
                        e,
                    )
                else:
                    logger.warning("Groq failed (%s) — falling back to OpenAI", e)

        if self.openai_api_key:
            # OpenAI מקבל את הפרומפט המלא אם קצר מספיק; אחרת truncated
            oa_messages = list(messages)
            if len(system_prompt) <= 24000:
                oa_messages = [{"role": "system", "content": system_prompt}]
                if history:
                    oa_messages.extend(history[-8:])
                oa_messages.append({"role": "user", "content": user_text})
            try:
                text = await self._chat(
                    http,
                    OPENAI_URL,
                    self.openai_api_key,
                    self.openai_model,
                    oa_messages,
                    timeout_sec,
                )
                if text:
                    logger.info("fast_llm provider=openai chars=%d", len(text))
                    return text
            except Exception as e:
                logger.error("OpenAI fallback failed: %s", e)

        return "רגע, לא תפסתי — תגיד שוב?"

    async def _chat(
        self,
        http: aiohttp.ClientSession,
        url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, str]],
        timeout_sec: float,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "messages": messages,
        }
        async with http.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"{model} HTTP {resp.status}: {body}")
            return (body["choices"][0]["message"]["content"] or "").strip()
