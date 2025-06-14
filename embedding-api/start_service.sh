#!/bin/bash

# ColPali Embedding API Service Startup Script
# This script provides an easy way to start the service locally

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting ColPali Embedding API Service...${NC}"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found. Creating from .env.example${NC}"
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}Please edit .env file with your configuration before running again.${NC}"
        exit 1
    else
        echo -e "${RED}Error: .env.example not found. Please create .env file manually.${NC}"
        exit 1
    fi
fi

# Load environment variables
if [ -f ".env" ]; then
    echo -e "${GREEN}Loading environment variables from .env${NC}"
    export $(grep -v '^#' .env | xargs)
fi

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then 
    echo -e "${RED}Error: Python $required_version or higher is required. Found: $python_version${NC}"
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}Installing uv package manager...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment with uv...${NC}"
    uv venv
fi

# Activate virtual environment
echo -e "${GREEN}Activating virtual environment...${NC}"
source .venv/bin/activate

# Check if dependencies are installed
if [ ! -f ".venv/installed" ]; then
    echo -e "${YELLOW}Installing dependencies with uv...${NC}"
    uv pip install -e .
    touch .venv/installed
    echo -e "${GREEN}Dependencies installed successfully${NC}"
fi

# Check GPU availability
echo -e "${BLUE}Checking GPU availability...${NC}"
python3 -c "
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU device: {torch.cuda.get_device_name(0)}')
    print(f'GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
print(f'MPS available: {torch.backends.mps.is_available() if hasattr(torch.backends, \"mps\") else False}')
"

# Set default values if not in environment
export COLPALI_HOST=${COLPALI_HOST:-"127.0.0.1"}
export COLPALI_PORT=${COLPALI_PORT:-"8765"}
export COLPALI_LOG_LEVEL=${COLPALI_LOG_LEVEL:-"INFO"}

echo -e "${GREEN}Starting service on http://${COLPALI_HOST}:${COLPALI_PORT}${NC}"
echo -e "${BLUE}Health check: http://${COLPALI_HOST}:${COLPALI_PORT}/health${NC}"
echo -e "${BLUE}API docs: http://${COLPALI_HOST}:${COLPALI_PORT}/docs${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the service${NC}"

# Start the service
python3 embedding_service.py
