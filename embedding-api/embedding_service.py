"""
ColPali Embedding API Service

A lightweight FastAPI service for ColPali embeddings that can run standalone or via Docker.
Compatible with the existing ColpaliApiEmbeddingModel client.
"""

import asyncio
import base64
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL.Image import Image
from PIL.Image import open as open_image
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global variables for model loading
colpali_model = None
colpali_processor = None
device = None

# Configuration
API_KEY = os.getenv("COLPALI_API_KEY", "your-secret-api-key")
MODEL_NAME = os.getenv("COLPALI_MODEL_NAME", "tsystems/colqwen2.5-3b-multilingual-v1.0")
DEVICE = os.getenv("COLPALI_DEVICE", "auto")  # auto, cuda, mps, cpu
BATCH_SIZE_TEXT = int(os.getenv("COLPALI_BATCH_SIZE_TEXT", "8"))
BATCH_SIZE_IMAGE = int(os.getenv("COLPALI_BATCH_SIZE_IMAGE", "4"))
HOST = os.getenv("COLPALI_HOST", "0.0.0.0")
PORT = int(os.getenv("COLPALI_PORT", "8000"))
LOG_LEVEL = os.getenv("COLPALI_LOG_LEVEL", "INFO")

# Pydantic models
class EmbeddingRequest(BaseModel):
    input_type: str = Field(..., description="Type of input: 'text' or 'image'")
    inputs: List[str] = Field(..., description="List of text strings or base64-encoded images")

class EmbeddingResponse(BaseModel):
    embeddings: List[List[List[float]]] = Field(..., description="List of multi-vector embeddings")

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    model_name: str
    uptime_seconds: float

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None

# Global startup time for uptime calculation
startup_time = time.time()

async def load_colpali_model():
    """Load the ColPali model and processor."""
    global colpali_model, colpali_processor, device
    
    try:
        logger.info("Starting ColPali model initialization...")
        start_time = time.time()
        
        # Device detection
        if DEVICE == "auto":
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        else:
            device = DEVICE
        
        logger.info(f"Using device: {device}")
        
        # Import ColPali components
        try:
            from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
        except ImportError as e:
            logger.error(f"Failed to import ColPali engine: {e}")
            raise HTTPException(
                status_code=500,
                detail="ColPali engine not available. Please install colpali-engine."
            )
        
        # Load model
        logger.info(f"Loading model: {MODEL_NAME}")
        colpali_model = ColQwen2_5.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.bfloat16,
            device_map=device,
            attn_implementation="flash_attention_2" if device == "cuda" else "eager",
        ).eval()
        
        # Load processor
        logger.info("Loading processor...")
        colpali_processor = ColQwen2_5_Processor.from_pretrained(MODEL_NAME)
        
        initialization_time = time.time() - start_time
        logger.info(f"ColPali model loaded successfully in {initialization_time:.2f} seconds")
        logger.info(f"Model device: {device}")
        logger.info(f"Text batch size: {BATCH_SIZE_TEXT}")
        logger.info(f"Image batch size: {BATCH_SIZE_IMAGE}")
        
    except Exception as e:
        logger.error(f"Failed to load ColPali model: {e}")
        raise

async def unload_colpali_model():
    """Cleanup model resources."""
    global colpali_model, colpali_processor
    
    logger.info("Cleaning up ColPali model resources...")
    if colpali_model is not None:
        del colpali_model
        colpali_model = None
    if colpali_processor is not None:
        del colpali_processor
        colpali_processor = None
    
    # Clear GPU cache if using CUDA
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    logger.info("Model cleanup completed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - load model on startup, cleanup on shutdown."""
    # Startup
    logger.info("Starting ColPali Embedding API Service...")
    await load_colpali_model()
    yield
    # Shutdown
    logger.info("Shutting down ColPali Embedding API Service...")
    await unload_colpali_model()

# Initialize FastAPI app
app = FastAPI(
    title="ColPali Embedding API",
    description="Lightweight API service for ColPali multi-vector embeddings",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

async def verify_api_key(credentials: HTTPAuthorizationCredentials = security):
    """Verify API key authentication."""
    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

def decode_image(base64_string: str) -> Image:
    """Decode base64 image string to PIL Image."""
    try:
        # Handle data URI format
        if base64_string.startswith("data:"):
            try:
                base64_string = base64_string.split(",", 1)[1]
            except IndexError:
                raise ValueError("Malformed data URI string for image decoding")
        
        # Decode base64
        image_bytes = base64.b64decode(base64_string)
        return open_image(io.BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f"Failed to decode base64 image: {e}")

async def generate_embeddings_batch(inputs: List[Any], input_type: str) -> List[List[List[float]]]:
    """Generate embeddings for a batch of inputs."""
    if colpali_model is None or colpali_processor is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Service may be starting up."
        )
    
    try:
        batch_size = BATCH_SIZE_IMAGE if input_type == "image" else BATCH_SIZE_TEXT
        all_embeddings = []
        
        for i in range(0, len(inputs), batch_size):
            batch_inputs = inputs[i:i + batch_size]
            
            # Process inputs based on type
            if input_type == "image":
                # Decode base64 images
                pil_images = [decode_image(img_str) for img_str in batch_inputs]
                processed = colpali_processor.process_images(pil_images).to(device)
            elif input_type == "text":
                # Process text queries
                processed = colpali_processor.process_queries(batch_inputs).to(device)
            else:
                raise ValueError(f"Invalid input_type: {input_type}")
            
            # Generate embeddings
            with torch.no_grad():
                embeddings_tensor = colpali_model(**processed)
            
            # Convert to CPU and then to list format
            embeddings_np = embeddings_tensor.to(torch.float32).cpu().numpy()
            batch_embeddings = embeddings_np.tolist()
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings
        
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embeddings: {str(e)}"
        )

# API Endpoints

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    uptime = time.time() - startup_time
    return HealthResponse(
        status="healthy" if colpali_model is not None else "unhealthy",
        model_loaded=colpali_model is not None,
        device=device or "unknown",
        model_name=MODEL_NAME,
        uptime_seconds=uptime
    )

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "ColPali Embedding API",
        "version": "1.0.0",
        "description": "Lightweight API service for ColPali multi-vector embeddings",
        "endpoints": {
            "health": "/health",
            "embeddings": "/embeddings"
        }
    }

@app.post("/embeddings", response_model=EmbeddingResponse)
async def generate_embeddings(
    request: EmbeddingRequest,
    api_key: str = security
):
    """
    Generate ColPali embeddings for text or image inputs.
    
    Compatible with the existing ColpaliApiEmbeddingModel client.
    """
    # Verify API key
    await verify_api_key(HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_key))
    
    start_time = time.time()
    
    # Validate request
    if not request.inputs:
        return EmbeddingResponse(embeddings=[])
    
    if request.input_type not in ["text", "image"]:
        raise HTTPException(
            status_code=400,
            detail="input_type must be 'text' or 'image'"
        )
    
    logger.info(f"Processing {len(request.inputs)} {request.input_type} inputs")
    
    try:
        # Generate embeddings
        embeddings = await generate_embeddings_batch(request.inputs, request.input_type)
        
        processing_time = time.time() - start_time
        logger.info(
            f"Generated {len(embeddings)} embeddings in {processing_time:.2f}s "
            f"({processing_time/len(request.inputs):.3f}s per input)"
        )
        
        return EmbeddingResponse(embeddings=embeddings)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=exc.detail, detail=str(exc)).dict()
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc) if os.getenv("DEBUG") else None
        ).dict()
    )

if __name__ == "__main__":
    # Configure logging level
    logging.getLogger().setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    logger.info(f"Starting ColPali Embedding API on {HOST}:{PORT}")
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Device: {DEVICE}")
    logger.info(f"API Key configured: {'Yes' if API_KEY != 'your-secret-api-key' else 'No (using default)'}")
    
    uvicorn.run(
        "embedding_service:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False
    )