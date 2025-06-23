"""
FastAPI Main Application

This is the entry point for the MahaVistaar AI API FastAPI application.
"""
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import chat_router, suggestions_router, transcribe_router, tts_router
from app.core.cache import cache
from helpers.utils import get_logger

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting up MahaVistaar AI API...")
    
    # Test cache connection
    try:
        await cache.set("health_check", "ok", ttl=60)
        test_value = await cache.get("health_check")
        if test_value == "ok":
            logger.info("✅ Cache connection successful")
        else:
            logger.warning("⚠️ Cache connection issue - values not persisting correctly")
    except Exception as e:
        logger.error(f"❌ Cache connection failed: {str(e)}")
    
    logger.info("✅ Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MahaVistaar AI API...")
    logger.info("✅ Application shutdown complete")

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        FastAPI: Configured FastAPI application instance
    """
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered agricultural assistant API for Maharashtra farmers",
        lifespan=lifespan
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=settings.allowed_credentials,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
    )
    
    # Include routers
    app.include_router(chat_router, prefix=settings.api_prefix)
    app.include_router(suggestions_router, prefix=settings.api_prefix)
    app.include_router(transcribe_router, prefix=settings.api_prefix)
    app.include_router(tts_router, prefix=settings.api_prefix)
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint"""
        try:
            # Test cache connectivity
            await cache.set("health_test", "ok", ttl=10)
            cache_status = await cache.get("health_test")
            cache_healthy = cache_status == "ok"
            
            return JSONResponse({
                "status": "healthy" if cache_healthy else "degraded",
                "service": settings.app_name,
                "version": "1.0.0",
                "environment": settings.environment,
                "cache": "connected" if cache_healthy else "disconnected"
            })
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return JSONResponse({
                "status": "unhealthy",
                "service": settings.app_name,
                "version": "1.0.0",
                "environment": settings.environment,
                "error": str(e)
            }, status_code=503)
    
    return app

# Create the app instance
app = create_app()

if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} server...")
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.uvicorn_workers,
        log_level=settings.log_level.lower()
    )
