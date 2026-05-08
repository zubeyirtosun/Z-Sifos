import logging
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from . import database, models, rag

logger = logging.getLogger(__name__)

# Single instance of scheduler
scheduler = BackgroundScheduler()
scheduler.start()

def process_document_task(doc_id: int):
    """Background task to index a document."""
    db = next(database.get_db())
    try:
        db_doc = db.query(models.DocumentModel).filter(models.DocumentModel.id == doc_id).first()
        if not db_doc:
            return

        db_doc.status = "processing"
        db.commit()

        # Perform indexing
        chunk_count = rag.index_document(
            agent_id=db_doc.agent_id,
            file_path=str(rag.UPLOAD_DIR / str(db_doc.agent_id) / db_doc.filename),
            filename=db_doc.original_name,
            doc_id=db_doc.id,
        )

        db_doc.chunk_count = chunk_count
        db_doc.status = "indexed"
        db_doc.error_message = None
        db.commit()
        logger.info(f"Successfully indexed document {doc_id} with {chunk_count} chunks.")

    except Exception as e:
        logger.error(f"Error indexing document {doc_id}: {e}", exc_info=True)
        # Re-fetch doc to ensure session is valid
        db_doc = db.query(models.DocumentModel).filter(models.DocumentModel.id == doc_id).first()
        if db_doc:
            db_doc.status = "error"
            db_doc.error_message = str(e)
            db.commit()
    finally:
        db.close()

def add_indexing_job(doc_id: int):
    """Add a document indexing job to the scheduler."""
    scheduler.add_job(
        process_document_task,
        args=[doc_id],
        id=f"index_doc_{doc_id}",
        replace_existing=True
    )
