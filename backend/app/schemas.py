"""Pydantic request/response schemas for BlackOpps API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "blackopps"
    version: str = "5.0.0"
    auth_configured: bool = False
    modules: list[str] = Field(default_factory=list)


class AgentInfo(BaseModel):
    id: str
    type: str
    status: str


class AgentsResponse(BaseModel):
    agents: list[AgentInfo] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)


class VoterCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    city: str = ""
    neighborhood: str = ""
    phone: str = ""
    email: str = ""
    support_score: float = 0.5
    turnout_history: float = 0.0


class VoterUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    city: str | None = None
    neighborhood: str | None = None
    phone: str | None = None
    email: str | None = None
    support_score: float | None = None
    turnout_history: float | None = None
    gotv_category: str | None = None
    gotv_priority: int | None = None
    gotv_channel: str | None = None
    gotv_frequency: str | None = None
    gotv_message: str | None = None
    enriched_at: str | None = None


class VoterOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    city: str = ""
    neighborhood: str = ""
    phone: str = ""
    email: str = ""
    support_score: float = 0.5
    turnout_history: float = 0.0
    gotv_category: str = ""
    gotv_priority: int = 0
    gotv_channel: str = ""
    gotv_frequency: str = ""
    gotv_message: str = ""
    enriched_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class VoterListResponse(BaseModel):
    voters: list[VoterOut]
    total: int
    limit: int
    offset: int


class ImportResult(BaseModel):
    imported: int
    duplicates: int
    total: int
    classified: int = 0
    categories: dict[str, int] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    voter_ids: list[str] = Field(default_factory=list)
    location: str = ""
    jurisdiction: str = "il"


class PredictRequest(BaseModel):
    name: str
    support_score: float = 0.5
    turnout_history: float = 0.55


class GotvVoterItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    support_score: float = 0.5
    turnout_history: float = 0.55


class GotvRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    names: list[str] | None = None
    voters: list[GotvVoterItem] | None = None


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name_a: str | None = None
    name_b: str | None = None
    candidate_a: str | None = None
    candidate_b: str | None = None
    location: str = ""
    jurisdiction: str = "il"

    def resolve_names(self) -> tuple[str, str]:
        a = (self.name_a or self.candidate_a or "").strip()
        b = (self.name_b or self.candidate_b or "").strip()
        return a, b


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voter_id: str | None = None
    voter_name: str | None = None
    channel: str = "WhatsApp"
    priority: int = 50
    message: str = ""
    message_template: str | None = None


class DispatchResponse(BaseModel):
    status: str
    message_id: str
    task_id: str
    channel: str
    voter_id: str | None = None
    voter_name: str | None = None
    queued_at: str


class DispatchStats(BaseModel):
    queued: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    agents_active: int = 0
    queue: str = "blackopps:dispatch:queue"
    length: int = 0


class ErrorBody(BaseModel):
    error: str
    detail: Any = None
    retry_after: int | None = None
