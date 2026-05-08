from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


# --- Auth Schemas ---

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Agent Schemas ---

class AgentBase(BaseModel):
    name: str
    model_name: str
    provider: str
    memory_enabled: bool = False
    internet_enabled: bool = False
    translator_enabled: bool = False
    document_enabled: bool = False
    mcp_enabled: bool = False
    agent_mode_override: Optional[str] = None  # None=auto | 'STRICT'|'STANDARD'|'ENHANCED'
    status: str = "ready"
    model_metadata: Optional[str] = None


class AgentCreate(AgentBase):
    pass


class Agent(AgentBase):
    id: int

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str
    images: Optional[List[str]] = None  # List of base64 encoded images
    planning_mode: bool = False
    plan_approved: bool = False


class ChatResponse(BaseModel):
    response: str
    confidence: float = 1.0  # 0.0 to 1.0
    sources: List[str] = []  # ["memory", "tool:internet", "tool:search", "rag", "etc"]
    flags: List[str] = []  # ["possible_hallucination", "requires_verification", "uncertain_context", etc]


class ModelPullRequest(BaseModel):
    model_name: str
    provider: str


class ConversationResponse(BaseModel):
    id: int
    agent_id: int
    role: str  # 'user' | 'ai'
    message: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    chunk_count: int
    file_size: int
    status: str
    error_message: Optional[str] = None
    uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentStats(BaseModel):
    agent_id: int
    message_count: int
    document_count: int


class MetricsResponse(BaseModel):
    agent_id: int
    # Tool usage
    tool_search_count: int = 0
    tool_scrape_count: int = 0
    # Confidence
    avg_confidence: float = 1.0
    hallucination_count: int = 0
    uncertain_count: int = 0
    # Response
    total_responses: int = 0
    avg_response_latency_ms: float = 0.0
    # RAG
    rag_retrieval_count: int = 0
    rag_hit_rate: float = 0.0  # relevant/total
    # Memory
    context_loss_events: int = 0
    
    class Config:
        from_attributes = True
