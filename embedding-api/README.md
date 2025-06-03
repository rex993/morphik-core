# ColPali Embedding API Service

A lightweight, self-hostable API service for ColPali multi-vector embeddings. This service provides a drop-in replacement for remote ColPali embedding generation, compatible with the existing Morphik `ColpaliApiEmbeddingModel` client.

## Features

- **Fast ColPali Embeddings**: GPU-accelerated ColPali model inference
- **Dual Input Support**: Process both text and images
- **Batch Processing**: Efficient batching for better throughput
- **Modern Python**: Uses `uv` for fast dependency management
- **Docker Ready**: Easy deployment with GPU support
- **Production Ready**: Authentication, logging, error handling, health checks
- **Compatible**: Drop-in replacement for Modal deployment

## Quick Start

### Option 1: Docker Deployment (Recommended)

1. **Clone and setup**:
   ```bash
   cd embedding-api
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Start with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

3. **Test the service**:
   ```bash
   curl http://localhost:8765/health
   ```

### Option 2: Local Development

1. **Setup environment**:
   ```bash
   cd embedding-api
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Run the startup script**:
   ```bash
   ./start_service.sh
   ```

3. **Or manually with uv**:
   ```bash
   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.cargo/env
   
   # Create virtual environment and install dependencies
   uv venv
   source .venv/bin/activate
   uv pip install -e .
   python embedding_service.py
   ```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COLPALI_API_KEY` | `your-secret-api-key` | API authentication key |
| `COLPALI_HOST` | `0.0.0.0` | Server bind address |
| `COLPALI_PORT` | `8765` | Server port |
| `COLPALI_LOG_LEVEL` | `INFO` | Logging level |
| `COLPALI_MODEL_NAME` | `tsystems/colqwen2.5-3b-multilingual-v1.0` | HuggingFace model name |
| `COLPALI_DEVICE` | `auto` | Device selection (auto/cuda/mps/cpu) |
| `COLPALI_BATCH_SIZE_TEXT` | `8` | Text batch size |
| `COLPALI_BATCH_SIZE_IMAGE` | `4` | Image batch size |
| `HF_TOKEN` | - | HuggingFace token (optional) |

### Hardware Requirements

- **Minimum**: 8GB RAM, CPU only
- **Recommended**: 16GB+ RAM, NVIDIA GPU with 8GB+ VRAM
- **Optimal**: 32GB+ RAM, NVIDIA RTX 4090 or better

## API Endpoints

### Health Check
```bash
GET /health
```

Returns service status and model information.

### Generate Embeddings
```bash
POST /embeddings
Content-Type: application/json
Authorization: Bearer your-api-key

{
  "input_type": "text",  // or "image"
  "inputs": [
    "Your text here",
    "Another text"
  ]
}
```

## Integration with Morphik

Update your Morphik configuration:

1. **Set environment variables**:
   ```bash
   export MORPHIK_EMBEDDING_API_KEY="your-secret-api-key"
   export MORPHIK_EMBEDDING_API_DOMAIN="http://localhost:8765"
   ```

2. **Update morphik.toml**:
   ```toml
   [morphik]
   enable_colpali = true
   colpali_mode = "api"
   morphik_embedding_api_domain = "http://localhost:8765"
   ```

3. **Test integration**:
   ```python
   from core.embedding.colpali_api_embedding_model import ColpaliApiEmbeddingModel
   
   model = ColpaliApiEmbeddingModel()
   embeddings = await model.embed_for_query("test query")
   ```

## Deployment Options

### 1. Local Development
```bash
./start_service.sh
```

### 2. Docker (Local)
```bash
docker-compose up -d
```

### 3. Docker (Remote Server)
```bash
# Build and push image
docker build -t your-registry/colpali-embedding-api .
docker push your-registry/colpali-embedding-api

# Deploy on remote server
docker run -d \
  --gpus all \
  -p 8765:8765 \
  -e COLPALI_API_KEY=your-secret-key \
  -v colpali_cache:/home/colpali/.cache/huggingface \
  your-registry/colpali-embedding-api
```

### 4. LAN Deployment
```bash
# On the server machine
export COLPALI_HOST=0.0.0.0  # Allow LAN access
export COLPALI_API_KEY=your-secret-key
./start_service.sh

# On client machines, use the server's IP
export MORPHIK_EMBEDDING_API_DOMAIN="http://192.168.1.100:8765"
```

## Development

### Using uv for Development

This project uses `uv` for fast Python package management:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install in development mode with dev dependencies
uv pip install -e ".[dev]"

# Install with GPU support (Linux only)
uv pip install -e ".[dev,gpu]"

# Run linting and formatting
black .
isort .
flake8 .
mypy .
```

## Testing

Run the comprehensive test suite:

```bash
# Make sure the service is running
./start_service.sh

# In another terminal
python test_api.py
```

The test script will verify:
- Health check endpoint
- Authentication
- Text embedding generation
- Image embedding generation
- Error handling

## Performance

### Benchmarks (RTX 4090)
- **Text embeddings**: ~0.1s per text (batch of 8)
- **Image embeddings**: ~0.3s per image (batch of 4)
- **Model loading**: ~15-30s (first startup)

### Optimization Tips

1. **Use GPU**: Ensure CUDA is available for best performance
2. **Batch requests**: Send multiple inputs in a single request
3. **Persistent deployment**: Keep service running to avoid model reload
4. **Cache models**: Use persistent volumes for HuggingFace cache

## Monitoring

### Health Check
```bash
curl http://localhost:8765/health
```

### Logs
```bash
# Docker
docker logs colpali-embedding-api

# Local
# Check console output or configure log files
```

### Metrics
The service logs performance metrics including:
- Request processing time
- Batch sizes
- GPU memory usage
- Model loading time

## Troubleshooting

### Common Issues

1. **CUDA out of memory**:
   - Reduce batch sizes in environment variables
   - Use smaller model or CPU mode

2. **Model loading fails**:
   - Check HuggingFace token for private models
   - Verify internet connection for model download
   - Check available disk space

3. **Service won't start**:
   - Verify Python version (3.8+)
   - Check port availability
   - Review environment variables

4. **Authentication errors**:
   - Verify API key matches between service and client
   - Check request headers format

### Debug Mode
```bash
export DEBUG=true
export COLPALI_LOG_LEVEL=DEBUG
```

## Security

- **API Key**: Always use a strong, random API key
- **Network**: Consider firewall rules for production deployment
- **Updates**: Keep dependencies updated for security patches
- **Non-root**: Docker container runs as non-root user

## License

This service is part of the Morphik project. See the main project LICENSE file for details.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review service logs
3. Test with the provided test script
4. Report issues to the Morphik project