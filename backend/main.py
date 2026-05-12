import os
import shutil
import logging
import json
import queue
import threading
import traceback
from pathlib import Path
from threading import Thread
from typing import List
import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from backend import models, schemas, database, user_auth, agent as agent_module
from backend.providers import (
    get_provider_metadata,
    get_provider_models,
    get_provider_library,
    get_model_info,
    check_ollama_status,
)
from backend.logging_config import setup_logging, get_logger
from backend.audio_proc import transcribe_audio
from backend.rate_limit import get_rate_limiter
from backend.exceptions import ValidationError, InternalError, RateLimitError

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Setup structured logging
env = os.getenv("ENVIRONMENT", "development")
setup_logging(env)
logger = get_logger(__name__)

models.Base.metadata.create_all(bind=database.engine)

# Paths will be imported from rag
from backend.rag import UPLOAD_DIR

from backend.http_client import HttpClientManager

# Global HTTP Client for tool performance (connection pooling)
@asynccontextmanager
async def lifespan(app: FastAPI):
    await HttpClientManager.get_client()
    yield
    await HttpClientManager.close_client()

app = FastAPI(title="Z-Sifos AI Platform API", version="5.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Run tasks on startup."""
    try:
        from backend.tools import sync_mcp_tools
        import asyncio
        # Run MCP sync in background
        asyncio.create_task(sync_mcp_tools())
        logger.info("MCP tool synchronization started in background.")
    except Exception as e:
        logger.error(f"Failed to start MCP sync: {e}")


# Rate limiting middleware
rate_limiter = get_rate_limiter()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to all requests"""
    # Skip rate limiting for health checks
    if request.url.path in ["/health", "/docs", "/openapi.json"]:
        return await call_next(request)
    
    is_allowed, retry_after, remaining = rate_limiter.is_allowed(request)
    
    if not is_allowed:
        logger.warning(f"Rate limit exceeded for {rate_limiter.get_client_ip(request)}")
        raise RateLimitError(retry_after=retry_after)
    
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def error_handler_middleware(request: Request, call_next):
    """Catch unhandled exceptions and log them"""
    try:
        return await call_next(request)
    except HTTPException as exc:
        # Let HTTPExceptions bubble up to their dedicated handlers
        raise exc
    except Exception as exc:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        raise InternalError(f"{type(exc).__name__}: {str(exc)}")


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors"""
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field = ".".join(str(x) for x in first_error.get("loc", [])[1:])
    message = first_error.get("msg", "Validation error")
    
    logger.warning(f"Validation error: {message} (field: {field})")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "validation_error", "message": message, "field": field}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    logger.warning(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "message": exc.detail}
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_plugin_names(db_agent: models.AgentModel) -> List[str]:
    names = []
    if db_agent.memory_enabled:
        names.append("memory")
    if db_agent.internet_enabled:
        names.append("internet")
    if db_agent.translator_enabled:
        names.append("translator")
    if db_agent.document_enabled:
        names.append("document")
    return names


def _update_metrics(agent_id: int, executor, response_text: str, db: Session, latency_ms: float = 0.0):
    """Update agent metrics after response."""
    try:
        metrics = db.query(models.MetricsModel).filter(models.MetricsModel.agent_id == agent_id).first()
        if not metrics:
            metrics = models.MetricsModel(agent_id=agent_id)
            db.add(metrics)
        
        # Extract from context
        tools_used = executor.plugin_manager.context.get("tools_used", [])
        confidence = executor.plugin_manager.context.get("response_confidence", 1.0)
        flags = executor.plugin_manager.context.get("response_flags", [])
        rag_sources = executor.plugin_manager.context.get("rag_sources", [])
        reranking_applied = executor.plugin_manager.context.get("rag_reranking_applied", False)
        reranking_metadata = executor.plugin_manager.context.get("rag_reranking_metadata", {})
        
        # Update counts
        metrics.tool_search_count += tools_used.count("search")
        metrics.tool_scrape_count += tools_used.count("scrape")
        metrics.total_responses += 1
        
        # Update averages
        if metrics.total_responses == 1:
            metrics.avg_confidence = confidence
            metrics.avg_response_latency_ms = latency_ms
        else:
            # Running average
            metrics.avg_confidence = (
                (metrics.avg_confidence * (metrics.total_responses - 1) + confidence) / 
                metrics.total_responses
            )
            metrics.avg_response_latency_ms = (
                (metrics.avg_response_latency_ms * (metrics.total_responses - 1) + latency_ms) / 
                metrics.total_responses
            )
        
        # Track flags
        metrics.hallucination_count += flags.count("possible_hallucination")
        metrics.uncertain_count += flags.count("uncertain_context")
        metrics.rag_retrieval_count += bool(rag_sources)
        
        # Track ML re-ranking improvements
        if reranking_applied and reranking_metadata:
            metrics.rag_reranking_count += 1
            score_improvement = reranking_metadata.get("score_improvement", 0.0)
            position_moved = abs(reranking_metadata.get("best_moved_positions", 0))
            
            # Update running averages for re-ranking metrics
            if metrics.rag_reranking_count == 1:
                metrics.rag_reranking_avg_improvement = score_improvement
                metrics.rag_reranking_position_avg = float(position_moved)
            else:
                # Running average
                prev_count = metrics.rag_reranking_count - 1
                metrics.rag_reranking_avg_improvement = (
                    (metrics.rag_reranking_avg_improvement * prev_count + score_improvement) / 
                    metrics.rag_reranking_count
                )
                metrics.rag_reranking_position_avg = (
                    (metrics.rag_reranking_position_avg * prev_count + position_moved) / 
                    metrics.rag_reranking_count
                )
        
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to update metrics: {e}")


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health_check(db: Session = Depends(database.get_db)):
    """API Health monitoring."""
    try:
        # Check database
        db.execute("SELECT 1")
        return {
            "status": "healthy",
            "version": "5.0.0",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": str(e)}
        )


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------

@app.post("/register", response_model=schemas.User)
def register(user_data: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = db.query(models.UserModel).filter(models.UserModel.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = user_auth.get_password_hash(user_data.password)
    new_user = models.UserModel(
        username=user_data.username,
        hashed_password=hashed_password,
        role="user" if db.query(models.UserModel).count() > 0 else "admin" # First user is admin
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.UserModel).filter(models.UserModel.username == form_data.username).first()
    if not user or not user_auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=user_auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = user_auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me", response_model=schemas.User)
async def read_users_me(current_user: models.UserModel = Depends(user_auth.get_current_active_user)):
    return current_user


# ---------------------------------------------------------------------------
# Provider & Model endpoints
# ---------------------------------------------------------------------------

@app.get("/providers/")
def read_providers():
    return get_provider_metadata()


@app.get("/ollama/status")
def read_ollama_status():
    return check_ollama_status()


@app.get("/providers/{provider_name}/models")
def read_provider_models(provider_name: str, local: bool = True):
    try:
        models_list = get_provider_models(provider_name) if local else get_provider_library(provider_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"models": models_list}


@app.get("/models/info")
def read_model_info(model_name: str, provider: str):
    return get_model_info(model_name, provider)


@app.post("/models/pull")
def pull_model(request: schemas.ModelPullRequest):
    from backend.providers import pull_model_stream
    return StreamingResponse(
        pull_model_stream(request.model_name, request.provider),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@app.post("/agents/", response_model=schemas.Agent)
def create_agent(
    agent_data: schemas.AgentCreate, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = models.AgentModel(owner_id=current_user.id, **agent_data.model_dump())
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
    return db_agent


@app.get("/agents/", response_model=List[schemas.Agent])
def read_agents(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    # Users only see their own agents unless admin
    query = db.query(models.AgentModel)
    if current_user.role != "admin":
        query = query.filter(models.AgentModel.owner_id == current_user.id)
    return query.offset(skip).limit(limit).all()


@app.put("/agents/{agent_id}", response_model=schemas.Agent)
def update_agent(
    agent_id: int, 
    agent_data: schemas.AgentBase, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this agent")

    for key, value in agent_data.model_dump().items():
        setattr(db_agent, key, value)
    db.commit()
    db.refresh(db_agent)
    return db_agent


@app.delete("/agents/{agent_id}")
def delete_agent(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this agent")

    db.delete(db_agent)
    db.commit()
    # Also remove embedding files
    embed_dir = Path(__file__).parent.parent / "data" / "embeddings" / str(agent_id)
    if embed_dir.exists():
        shutil.rmtree(embed_dir)
    return {"ok": True}


@app.get("/agents/{agent_id}/stats", response_model=schemas.AgentStats)
def get_agent_stats(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to see stats for this agent")

    msg_count = db.query(models.ConversationHistory).filter(
        models.ConversationHistory.agent_id == agent_id
    ).count()
    doc_count = db.query(models.DocumentModel).filter(
        models.DocumentModel.agent_id == agent_id
    ).count()
    return schemas.AgentStats(agent_id=agent_id, message_count=msg_count, document_count=doc_count)


@app.get("/agents/{agent_id}/metrics", response_model=schemas.MetricsResponse)
def get_agent_metrics(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Get performance metrics for an agent."""
    # Verify agent exists
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to see metrics for this agent")
    
    # Get or create metrics
    metrics = db.query(models.MetricsModel).filter(models.MetricsModel.agent_id == agent_id).first()
    if not metrics:
        metrics = models.MetricsModel(agent_id=agent_id)
        db.add(metrics)
        db.commit()
    
    # Calculate hit rate
    hit_rate = (
        metrics.rag_relevant_count / metrics.rag_retrieval_count
        if metrics.rag_retrieval_count > 0 else 0.0
    )
    
    return schemas.MetricsResponse(
        agent_id=agent_id,
        tool_search_count=metrics.tool_search_count,
        tool_scrape_count=metrics.tool_scrape_count,
        avg_confidence=metrics.avg_confidence,
        hallucination_count=metrics.hallucination_count,
        uncertain_count=metrics.uncertain_count,
        total_responses=metrics.total_responses,
        avg_response_latency_ms=metrics.avg_response_latency_ms,
        rag_retrieval_count=metrics.rag_retrieval_count,
        rag_hit_rate=hit_rate,
        context_loss_events=metrics.context_loss_events,
    )


@app.get("/agents/{agent_id}/export/json")
def export_conversations_json(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Export conversation history as JSON."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to export this agent")

    conversations = (
        db.query(models.ConversationHistory)
        .filter(models.ConversationHistory.agent_id == agent_id)
        .order_by(models.ConversationHistory.id)
        .all()
    )
    
    data = [
        {"role": c.role, "message": c.message, "timestamp": c.created_at.isoformat() if c.created_at else None}
        for c in conversations
    ]
    
    filename = f"chat_export_{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    import json
    from fastapi.responses import Response
    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/agents/{agent_id}/export/markdown")
def export_conversations_markdown(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Export conversation history as Markdown."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to export this agent")

    conversations = (
        db.query(models.ConversationHistory)
        .filter(models.ConversationHistory.agent_id == agent_id)
        .order_by(models.ConversationHistory.id)
        .all()
    )
    
    md_content = f"# Chat History - Agent: {db_agent.name}\n\n"
    for c in conversations:
        role_label = "**User**" if c.role == "user" else "**AI**"
        md_content += f"### {role_label}\n{c.message}\n\n---\n\n"
        
    filename = f"chat_export_{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    
    from fastapi.responses import Response
    return Response(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------

@app.get("/agents/{agent_id}/conversations", response_model=List[schemas.ConversationResponse])
def list_conversations(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Get conversation history for an agent."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to see conversations for this agent")

    conversations = (
        db.query(models.ConversationHistory)
        .filter(models.ConversationHistory.agent_id == agent_id)
        .order_by(models.ConversationHistory.id)
        .all()
    )
    return conversations


@app.delete("/agents/{agent_id}/conversations")
def clear_conversations(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Delete all conversation history for an agent."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to clear conversations for this agent")

    deleted = (
        db.query(models.ConversationHistory)
        .filter(models.ConversationHistory.agent_id == agent_id)
        .delete()
    )
    db.commit()
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Document (RAG) endpoints
# ---------------------------------------------------------------------------

@app.get("/agents/{agent_id}/documents", response_model=List[schemas.DocumentResponse])
def list_documents(
    agent_id: int, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to see documents for this agent")

    return db.query(models.DocumentModel).filter(models.DocumentModel.agent_id == agent_id).all()


@app.post("/agents/{agent_id}/documents", response_model=schemas.DocumentResponse)
async def upload_document(
    agent_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user) # Require auth
):
    """Upload and index a document for an agent."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to upload documents for this agent")

    # Validate extension
    allowed_exts = {".txt", ".md", ".pdf", ".docx", ".rst", ".csv"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya türü: {ext}. İzlenenler: {', '.join(allowed_exts)}"
        )

    # Save file
    agent_upload_dir = UPLOAD_DIR / str(agent_id)
    agent_upload_dir.mkdir(parents=True, exist_ok=True)

    # Create DB record first to get an ID
    db_doc = models.DocumentModel(
        agent_id=agent_id,
        filename=file.filename,
        original_name=file.filename,
        chunk_count=0,
        file_size=0,
        status="pending", # Initial status
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    safe_filename = f"{db_doc.id}_{file.filename}"
    file_path = UPLOAD_DIR / str(agent_id) / safe_filename
    (UPLOAD_DIR / str(agent_id)).mkdir(parents=True, exist_ok=True)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    file_size = len(content)

    # Update DB record with file info
    db_doc.filename = safe_filename
    db_doc.original_name = file.filename
    db_doc.file_size = file_size
    db.commit()
    db.refresh(db_doc)

    # Trigger background indexing
    from backend.scheduler import scheduler, add_indexing_job
    add_indexing_job(db_doc.id)

    return db_doc


@app.delete("/agents/{agent_id}/documents/{doc_id}")
def delete_document(agent_id: int, doc_id: int, db: Session = Depends(database.get_db)):
    db_doc = db.query(models.DocumentModel).filter(
        models.DocumentModel.id == doc_id,
        models.DocumentModel.agent_id == agent_id,
    ).first()
    if not db_doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove file
    file_path = UPLOAD_DIR / str(agent_id) / db_doc.filename
    if file_path.exists():
        file_path.unlink()

    # Remove embeddings
    try:
        from backend.rag import delete_document_chunks
        delete_document_chunks(agent_id, doc_id)
    except Exception as e:
        logger.error(f"RAG delete error: {e}")

    db.delete(db_doc)
    db.commit()
    return {"ok": True}


@app.post("/audio/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """Transcribe uploaded audio file to text."""
    content = await file.read()
    text = transcribe_audio(content)
    if not text:
        raise HTTPException(status_code=400, detail="Could not transcribe audio")
    return {"text": text}


# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------

@app.post("/agents/{agent_id}/chat", response_model=schemas.ChatResponse)
async def chat_with_agent(
    agent_id: int, 
    request: schemas.ChatRequest, 
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to chat with this agent")

    session_history = []
    if db_agent.memory_enabled:
        session_history = (
            db.query(models.ConversationHistory)
            .filter(models.ConversationHistory.agent_id == agent_id)
            .order_by(models.ConversationHistory.id)
            .all()
        )

    plugin_names = _get_plugin_names(db_agent)

    try:
        logger.info(f"[CHAT] Building agent: model={db_agent.model_name}, provider={db_agent.provider}, mode={db_agent.agent_mode_override or 'auto'}")
        executor = agent_module.build_agent(
            model_name=db_agent.model_name,
            provider=db_agent.provider,
            plugin_names=plugin_names,
            session_history=session_history,
            agent_id=agent_id,
            model_metadata=db_agent.model_metadata,
            mode_override=db_agent.agent_mode_override,
            mcp_enabled=db_agent.mcp_enabled
        )
        logger.info(f"[CHAT] Agent built successfully")
    except Exception as e:
        logger.error(f"[CHAT] Agent build failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    try:
        logger.info(f"[CHAT] Running predict for: {request.message[:50]}...")
        response_text = await executor.predict(
            input_text=request.message,
            images=request.images,
            planning_mode=request.planning_mode,
            plan_approved=request.plan_approved
        )
        logger.info(f"[CHAT] Predict completed, response length: {len(response_text)}")
    except Exception as e:
        logger.error(f"[CHAT] Predict failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # Extract metadata from plugin manager context
    confidence = executor.plugin_manager.context.get("response_confidence", 1.0)
    sources = executor.plugin_manager.context.get("response_sources", ["memory"])
    flags = executor.plugin_manager.context.get("response_flags", [])

    if db_agent.memory_enabled:
        db.add(models.ConversationHistory(agent_id=agent_id, role="user", message=request.message))
        db.add(models.ConversationHistory(agent_id=agent_id, role="ai", message=response_text))
        db.commit()

    # Update metrics
    _update_metrics(agent_id, executor, response_text, db)

    return schemas.ChatResponse(response=response_text, confidence=confidence, sources=sources, flags=flags)


@app.post("/agents/{agent_id}/chat/stream")
async def chat_with_agent_stream(
    agent_id: int,
    request: schemas.ChatRequest,
    db: Session = Depends(database.get_db),
    current_user: models.UserModel = Depends(user_auth.get_current_active_user)
):
    """SSE token-by-token streaming chat (interruptable)."""
    db_agent = db.query(models.AgentModel).filter(models.AgentModel.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if current_user.role != "admin" and db_agent.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to chat with this agent")

    session_history = []
    if db_agent.memory_enabled:
        db.add(models.ConversationHistory(agent_id=agent_id, role="user", message=request.message))
        db.commit()
        
        session_history = (
            db.query(models.ConversationHistory)
            .filter(models.ConversationHistory.agent_id == agent_id)
            .order_by(models.ConversationHistory.id)
            .all()
        )

    plugin_names = _get_plugin_names(db_agent)

    try:
        executor = agent_module.build_agent(
            model_name=db_agent.model_name,
            provider=db_agent.provider,
            plugin_names=plugin_names,
            session_history=session_history,
            agent_id=agent_id,
            model_metadata=db_agent.model_metadata,
            mode_override=db_agent.agent_mode_override,
            mcp_enabled=db_agent.mcp_enabled
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def stream_generator():
        try:
            full_response: List[str] = []
            
            # Use async iteration for the new async predict_stream
            async for event in executor.predict_stream(
                input_text=request.message,
                images=request.images,
                planning_mode=request.planning_mode,
                plan_approved=request.plan_approved
            ):
                if event.get("type") == "token":
                    full_response.append(event.get("content", ""))
                
                yield f"data: {json.dumps(event)}\n\n"

            # Save to memory only on clean completion
            if db_agent.memory_enabled and full_response:
                full_answer = "".join(full_response)
                db.add(models.ConversationHistory(agent_id=agent_id, role="ai", message=full_answer))
                db.commit()
                
                # Update metrics
                _update_metrics(agent_id, executor, full_answer, db)

            yield f"data: {json.dumps({'type': 'status', 'content': 'complete'})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.get("/")
def root():
    return {"status": "ok", "message": "Antigravity AI Platform v5.0"}
