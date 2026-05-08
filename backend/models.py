from sqlalchemy import Boolean, Column, Integer, String, Text, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # 'admin' | 'user'
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agents = relationship("AgentModel", back_populates="owner", cascade="all, delete-orphan")


class AgentModel(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True) # Nullable for legacy support
    name = Column(String, index=True)
    model_name = Column(String)       # e.g. 'llama3.2:1b'
    provider = Column(String)         # e.g. 'ollama' or 'llamacpp'
    status = Column(String, default="ready")          # 'ready' | 'downloading' | 'error'
    model_metadata = Column(Text, nullable=True)      # JSON: size, context, family
    memory_enabled = Column(Boolean, default=False)
    internet_enabled = Column(Boolean, default=False)
    translator_enabled = Column(Boolean, default=False)
    document_enabled = Column(Boolean, default=False)  # RAG toggle
    mcp_enabled = Column(Boolean, default=False)       # MCP toggle
    agent_mode_override = Column(String, nullable=True)  # None=auto | 'STRICT'|'STANDARD'|'ENHANCED'

    owner = relationship("UserModel", back_populates="agents")
    conversations = relationship("ConversationHistory", back_populates="agent", cascade="all, delete-orphan")
    documents = relationship("DocumentModel", back_populates="agent", cascade="all, delete-orphan")


class ConversationHistory(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    role = Column(String)    # 'user' | 'ai'
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("AgentModel", back_populates="conversations")


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    filename = Column(String)
    original_name = Column(String)
    chunk_count = Column(Integer, default=0)
    file_size = Column(Integer, default=0)      # bytes
    status = Column(String, default="pending")  # 'pending' | 'processing' | 'indexed' | 'error'
    error_message = Column(Text, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("AgentModel", back_populates="documents")


class MetricsModel(Base):
    """Track RAG and agent performance metrics."""
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    
    # Tool usage
    tool_search_count = Column(Integer, default=0)
    tool_scrape_count = Column(Integer, default=0)
    
    # Confidence & hallucination
    avg_confidence = Column(Float, default=1.0)
    hallucination_count = Column(Integer, default=0)
    uncertain_count = Column(Integer, default=0)
    
    # Response metrics
    total_responses = Column(Integer, default=0)
    avg_response_latency_ms = Column(Float, default=0.0)
    
    # RAG metrics
    rag_retrieval_count = Column(Integer, default=0)
    rag_relevant_count = Column(Integer, default=0)  # User feedback: "was helpful"
    
    # RAG Re-ranking (ML enhancement)
    rag_reranking_count = Column(Integer, default=0)  # How many times re-ranking applied
    rag_reranking_avg_improvement = Column(Float, default=0.0)  # Avg confidence score improvement
    rag_reranking_position_avg = Column(Float, default=0.0)  # Avg positions the best chunk moved
    
    # Memory & context
    context_loss_events = Column(Integer, default=0)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    agent = relationship("AgentModel")
