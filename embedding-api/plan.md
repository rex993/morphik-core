# ColPali Embedding API Service Plan

## Overview
Create a lightweight, self-hostable API service for ColPali embeddings that can run either on a LAN computer or via Docker. This service will be compatible with the existing `colpali_api_embedding_model.py` client.

## Current State Analysis

### Existing API Client Contract
The `colpali_api_embedding_model.py` expects:
- **Endpoint**: `{domain}/embeddings`
- **Authentication**: Bearer token in Authorization header
- **Request format**: 
  ```json
  {
    "input_type": "text" | "image",
    "inputs": ["list", "of", "inputs"]
  }
  ```
- **Response format**:
  ```json
  {
    "embeddings": [
      [[...], [...]], // multivector for input 1
      [[...], [...]]  // multivector for input 2
    ]
  }
  ```

### Existing Local Implementation
The `colpali_embedding_model.py` provides:
- Device detection (MPS/CUDA/CPU)
- Model loading from HuggingFace (`tsystems/colqwen2.5-3b-multilingual-v1.0`)
- Batch processing capabilities
- Image and text processing
- Performance logging

## Proposed Solution

### 1. FastAPI Service (`embedding_service.py`)
Create a lightweight FastAPI application that:
- Loads the ColPali model once at startup
- Provides `/embeddings` endpoint matching the API contract
- Supports both text and image inputs
- Includes authentication via API key
- Handles batch processing efficiently
- Provides health check endpoints
- Includes proper error handling and logging

### 2. Docker Configuration
- **Dockerfile**: Multi-stage build for optimized image size
- **docker-compose.yml**: Easy deployment with GPU support
- **Environment configuration**: API keys, model settings, device selection
- **Volume mounting**: For model cache persistence

### 3. Standalone Deployment
- **Requirements**: Simple pip installable dependencies
- **Configuration**: Environment variables or config file
- **Service script**: Easy start/stop management
- **Documentation**: Setup instructions for different platforms

## Implementation Plan

### Phase 1: Core API Service
1. **Create FastAPI application** (`embedding_service.py`)
   - Implement `/embeddings` endpoint
   - Add authentication middleware
   - Include model loading and inference logic
   - Add health check and status endpoints

2. **Configuration management**
   - Environment variables for API key, model path, device
   - Optional config file support
   - Validation and defaults

3. **Error handling and logging**
   - Structured logging
   - Proper HTTP status codes
   - Request/response validation

### Phase 2: Docker Deployment
1. **Create Dockerfile**
   - Base image with Python and CUDA support
   - Efficient model caching
   - Non-root user for security
   - Health checks

2. **Docker Compose configuration**
   - GPU runtime support
   - Environment variable injection
   - Volume mounting for model cache
   - Network configuration

3. **Scripts and documentation**
   - Build and run scripts
   - Environment setup examples
   - GPU configuration guidance

### Phase 3: LAN Deployment
1. **Standalone installation**
   - Requirements.txt with version pinning
   - Installation script
   - Service management (systemd example)

2. **Network configuration**
   - CORS settings for web access
   - Security considerations
   - Performance tuning recommendations

### Phase 4: Testing and Documentation
1. **Testing suite**
   - Unit tests for API endpoints
   - Integration tests with actual model
   - Performance benchmarks

2. **Documentation**
   - Setup guides for Docker and LAN deployment
   - Configuration reference
   - Troubleshooting guide
   - Performance optimization tips

## File Structure
```
embedding-api/
├── plan.md                     # This file
├── embedding_service.py        # Main FastAPI application
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker image definition
├── docker-compose.yml          # Docker deployment config
├── .env.example               # Environment variables template
├── start_service.sh           # Standalone startup script
└── README.md                  # Setup and usage documentation
```

## Key Features

### Performance Optimizations
- Model loaded once at startup (not per request)
- Efficient batch processing
- Configurable batch sizes based on available hardware
- Model caching to avoid repeated downloads

### Security
- API key authentication
- Input validation and sanitization
- Rate limiting (optional)
- Secure defaults

### Monitoring
- Health check endpoints
- Performance metrics logging
- Request/response logging
- Error tracking

### Compatibility
- Drop-in replacement for Modal deployment
- Same API contract as existing client
- Multiple deployment options (Docker, standalone, LAN)
- GPU/CPU auto-detection

## Configuration Options

### Environment Variables
- `COLPALI_API_KEY`: Authentication token
- `COLPALI_MODEL_NAME`: HuggingFace model identifier
- `COLPALI_DEVICE`: Force specific device (cuda/mps/cpu)
- `COLPALI_BATCH_SIZE`: Override default batch size
- `COLPALI_HOST`: Service bind address
- `COLPALI_PORT`: Service port
- `COLPALI_LOG_LEVEL`: Logging verbosity

### Hardware Requirements
- **Minimum**: 8GB RAM, CPU
- **Recommended**: 16GB+ RAM, NVIDIA GPU with 8GB+ VRAM
- **Optimal**: 32GB+ RAM, NVIDIA RTX 4090 or better

## Deployment Scenarios

### 1. Docker on Local Machine
```bash
docker-compose up -d
```
- Isolated environment
- Easy updates
- GPU passthrough support

### 2. Docker on Remote Server
- Network accessible
- Resource isolation
- Easy scaling

### 3. Standalone on LAN Computer
- Direct hardware access
- Minimal overhead
- Custom optimization

## Success Criteria
1. ✅ API compatible with existing `colpali_api_embedding_model.py`
2. ✅ Deployable via Docker with one command
3. ✅ Runnable on LAN with simple setup
4. ✅ Performance comparable to local model
5. ✅ Proper error handling and logging
6. ✅ Comprehensive documentation
7. ✅ Security best practices implemented

## Next Steps
1. Implement the FastAPI service with core functionality
2. Create Docker configuration and test deployment
3. Add comprehensive documentation and examples
4. Performance testing and optimization
5. Security review and hardening
