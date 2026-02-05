"""
Main FastAPI application for Hustle backend.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import time

from app.database import init_db, close_db
from app.routers import sellers, products, catalog, webhook
from app.services.logging import log_error

# Create FastAPI app
app = FastAPI(
    title="Hustle API",
    description="WhatsApp-first private catalog for informal sellers",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:19006,http://localhost:8081"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time header to responses."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    # Log the error
    log_error(
        error_message=str(exc),
        details={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else None
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please try again later."
        }
    )


# Include routers
app.include_router(sellers.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(webhook.router, prefix="/api/v1")

# Mount uploads directory for serving images
upload_dir = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    print("🚀 Starting Hustle API...")
    init_db()
    print("✅ Database initialized")
    print(f"📁 Upload directory: {upload_dir}")
    print(f"🌐 CORS origins: {allowed_origins}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    print("🛑 Shutting down Hustle API...")
    close_db()
    print("✅ Database connections closed")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Hustle API",
        "version": "1.0.0",
        "description": "WhatsApp-first private catalog for informal sellers",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "hustle-api",
        "version": "1.0.0"
    }


@app.get("/api/v1")
async def api_info():
    """API information endpoint."""
    return {
        "version": "v1",
        "endpoints": {
            "sellers": "/api/v1/sellers",
            "products": "/api/v1/products",
            "catalog": "/api/v1/catalog",
            "webhook": "/api/v1/webhook"
        }
    }
