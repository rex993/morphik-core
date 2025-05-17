import logging
from contextlib import asynccontextmanager

import arq
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Global variable for redis_pool, primarily for shutdown if app.state access fails.
_global_redis_pool = None  # type: ignore


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Application lifespan handler (copied from core/api.py).

    Performs:
    1. Database initialization
    2. Vector store initialization
    3. Redis pool creation
    4. Graceful shutdown of Redis pool
    """
    # ------------------------------------------------------------------
    # Import services directly from services_init instead of through api_module
    # ------------------------------------------------------------------
    from core.services_init import database, settings, vector_store

    # --- BEGIN MOVED STARTUP LOGIC ---
    logger.info("Lifespan: Initializing Database…")
    try:
        success = await database.initialize()
        if success:
            logger.info("Lifespan: Database initialization successful")
        else:
            logger.error("Lifespan: Database initialization failed")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Lifespan: CRITICAL - Failed to initialize Database: %s",
            exc,
            exc_info=True,
        )
        raise

    logger.info("Lifespan: Initializing Vector Store…")
    try:
        if hasattr(vector_store, "initialize"):
            await vector_store.initialize()
        logger.info("Lifespan: Vector Store initialization successful (or not applicable).")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Lifespan: CRITICAL - Failed to initialize Vector Store: %s",
            exc,
            exc_info=True,
        )

    logger.info("Lifespan: Attempting to initialize Redis connection pool…")
    global _global_redis_pool  # pylint: disable=global-statement
    try:
        redis_settings_obj = arq.connections.RedisSettings(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
        )
        logger.info(
            "Lifespan: Redis settings for pool: host=%s, port=%s",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
        )
        current_redis_pool = await arq.create_pool(redis_settings_obj)
        if current_redis_pool:
            app_instance.state.redis_pool = current_redis_pool
            _global_redis_pool = current_redis_pool
            logger.info(
                "Lifespan: Successfully initialized Redis connection pool and stored on app.state.",
            )
        else:
            logger.error(
                "Lifespan: arq.create_pool returned None or a falsey value for Redis pool.",
            )
            raise RuntimeError(
                "Lifespan: Failed to create Redis pool - arq.create_pool returned non-truthy value.",
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Lifespan: CRITICAL - Failed to initialize Redis connection pool: %s",
            exc,
            exc_info=True,
        )
        raise RuntimeError(
            f"Lifespan: CRITICAL - Failed to initialize Redis connection pool: {exc}",
        ) from exc
    # --- END MOVED STARTUP LOGIC ---

    logger.info("Lifespan: Core startup logic executed.")
    yield
    # Shutdown logic
    logger.info("Lifespan: Shutdown initiated.")
    pool_to_close = getattr(app_instance.state, "redis_pool", _global_redis_pool)
    if pool_to_close:
        logger.info("Closing Redis connection pool from lifespan…")
        pool_to_close.close()
        # await pool_to_close.wait_closed()  # Uncomment if needed
        logger.info("Redis connection pool closed from lifespan.")
    logger.info("Lifespan: Shutdown complete.")
