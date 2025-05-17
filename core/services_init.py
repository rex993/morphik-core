"""Centralised initialisation of core services.

This file was introduced during the refactor of `core/api.py` to keep the
monolithic API file small.  It performs *exactly* the same initialisation
logic that previously lived in `core/api.py` (lines ~90-210) and exposes the
created singletons so that other modules can simply import them:

    from core.services_init import document_service, settings

No behaviour has changed – only the physical location of the code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.cache.llama_cache_factory import LlamaCacheFactory
from core.completion.litellm_completion import LiteLLMCompletionModel
from core.config import get_settings
from core.database.postgres_database import PostgresDatabase
from core.embedding.colpali_api_embedding_model import ColpaliApiEmbeddingModel
from core.embedding.colpali_embedding_model import ColpaliEmbeddingModel
from core.embedding.litellm_embedding import LiteLLMEmbeddingModel
from core.parser.morphik_parser import MorphikParser
from core.reranker.flag_reranker import FlagReranker
from core.services.document_service import DocumentService
from core.storage.local_storage import LocalStorage
from core.storage.s3_storage import S3Storage
from core.vector_store.multi_vector_store import MultiVectorStore
from core.vector_store.pgvector_store import PGVectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------

settings = get_settings()

# ---------------------------------------------------------------------------
# Database & vector store
# ---------------------------------------------------------------------------

if not settings.POSTGRES_URI:
    raise ValueError("PostgreSQL URI is required for PostgreSQL database")

database = PostgresDatabase(uri=settings.POSTGRES_URI)
logger.debug("Created PostgresDatabase singleton")

vector_store = PGVectorStore(uri=settings.POSTGRES_URI)
logger.debug("Created PGVectorStore singleton")

# ---------------------------------------------------------------------------
# Object storage
# ---------------------------------------------------------------------------

match settings.STORAGE_PROVIDER:
    case "local":
        storage = LocalStorage(storage_path=settings.STORAGE_PATH)
    case "aws-s3":
        if not settings.AWS_ACCESS_KEY or not settings.AWS_SECRET_ACCESS_KEY:
            raise ValueError("AWS credentials are required for S3 storage")
        storage = S3Storage(
            aws_access_key=settings.AWS_ACCESS_KEY,
            aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
            default_bucket=settings.S3_BUCKET,
        )
    case _:
        raise ValueError(f"Unsupported storage provider: {settings.STORAGE_PROVIDER}")
logger.debug("Initialised Storage layer: %s", settings.STORAGE_PROVIDER)

# ---------------------------------------------------------------------------
# Parser & models
# ---------------------------------------------------------------------------

parser = MorphikParser(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
    use_unstructured_api=settings.USE_UNSTRUCTURED_API,
    unstructured_api_key=settings.UNSTRUCTURED_API_KEY,
    assemblyai_api_key=settings.ASSEMBLYAI_API_KEY,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
    use_contextual_chunking=settings.USE_CONTEXTUAL_CHUNKING,
)

embedding_model = LiteLLMEmbeddingModel(model_key=settings.EMBEDDING_MODEL)
logger.info("Initialized LiteLLM embedding model with model key: %s", settings.EMBEDDING_MODEL)

completion_model = LiteLLMCompletionModel(model_key=settings.COMPLETION_MODEL)
logger.info("Initialized LiteLLM completion model with model key: %s", settings.COMPLETION_MODEL)

# ---------------------------------------------------------------------------
# Optional reranker
# ---------------------------------------------------------------------------

reranker: Optional[FlagReranker] = None
if settings.USE_RERANKING:
    match settings.RERANKER_PROVIDER:
        case "flag":
            reranker = FlagReranker(
                model_name=settings.RERANKER_MODEL,
                device=settings.RERANKER_DEVICE,
                use_fp16=settings.RERANKER_USE_FP16,
                query_max_length=settings.RERANKER_QUERY_MAX_LENGTH,
                passage_max_length=settings.RERANKER_PASSAGE_MAX_LENGTH,
            )
        case _:
            raise ValueError(f"Unsupported reranker provider: {settings.RERANKER_PROVIDER}")
logger.debug("Reranker enabled: %s", bool(reranker))

# ---------------------------------------------------------------------------
# Cache factory
# ---------------------------------------------------------------------------

cache_factory = LlamaCacheFactory(Path(settings.STORAGE_PATH))

# ---------------------------------------------------------------------------
# ColPali multi-vector support
# ---------------------------------------------------------------------------

match settings.COLPALI_MODE:
    case "off":
        colpali_embedding_model = None
        colpali_vector_store = None
    case "local":
        colpali_embedding_model = ColpaliEmbeddingModel()
        colpali_vector_store = MultiVectorStore(uri=settings.POSTGRES_URI)
    case "api":
        colpali_embedding_model = ColpaliApiEmbeddingModel()
        colpali_vector_store = MultiVectorStore(uri=settings.POSTGRES_URI)
    case _:
        raise ValueError(f"Unsupported COLPALI_MODE: {settings.COLPALI_MODE}")

# ---------------------------------------------------------------------------
# Document service (ties everything together)
# ---------------------------------------------------------------------------

document_service = DocumentService(
    database=database,
    vector_store=vector_store,
    storage=storage,
    parser=parser,
    embedding_model=embedding_model,
    completion_model=completion_model,
    cache_factory=cache_factory,
    reranker=reranker,
    enable_colpali=settings.ENABLE_COLPALI,
    colpali_embedding_model=colpali_embedding_model,
    colpali_vector_store=colpali_vector_store,
)
logger.info("Document service initialised")

__all__ = [
    "settings",
    "database",
    "vector_store",
    "storage",
    "embedding_model",
    "completion_model",
    "document_service",
]
