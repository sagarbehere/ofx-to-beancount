"""
FastAPI application for OFX to Beancount converter.

This is the main API application that coordinates all the processing
services and provides endpoints for the CLI client.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
from contextlib import asynccontextmanager

from api.routers import session, transactions, export
from api.services.session_manager import cleanup_sessions_periodically


# Background task for session cleanup
async def periodic_cleanup():
    """Periodically clean up expired sessions."""
    while True:
        try:
            cleanup_sessions_periodically()
            await asyncio.sleep(300)  # Clean up every 5 minutes
        except Exception as e:
            print(f"Session cleanup error: {e}")
            await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    print("Starting OFX to Beancount API server...")
    
    # Start background task for session cleanup
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    yield
    
    # Shutdown
    print("Shutting down OFX to Beancount API server...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Create FastAPI application
app = FastAPI(
    title="OFX to Beancount Converter API",
    description="API for converting OFX files to Beancount format with ML categorization",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for local use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(session.router)
app.include_router(transactions.router)
app.include_router(export.router)


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "message": "OFX to Beancount Converter API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "session_init": "/session/initialize",
            "transaction_categorize": "/transactions/categorize", 
            "transaction_update": "/transactions/update-batch",
            "export": "/export/beancount",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    from api.services.session_manager import get_session_manager
    
    session_manager = get_session_manager()
    stats = session_manager.get_session_stats()
    
    return {
        "status": "healthy",
        "session_stats": stats
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    print(f"Unhandled exception: {exc}")
    import traceback
    traceback.print_exc()
    
    return HTTPException(
        status_code=500,
        detail="Internal server error occurred"
    )


def create_app():
    """Factory function to create the FastAPI app."""
    return app


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """
    Run the API server.
    
    Args:
        host: Host to bind to
        port: Port to listen on
    """
    print(f"Starting OFX to Beancount API server on {host}:{port}")
    
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=False,  # Disable reload for production use
        access_log=True,
        log_level="info"
    )


if __name__ == "__main__":
    # Default development server
    run_server()