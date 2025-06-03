import modal
import os
import base64
import io
import time
from typing import List
from pydantic import BaseModel

# --- Modal App Definition ---
app = modal.App(name="colpali-embedding-service-prod") # Renamed stubb to app

# --- Environment and Image Configuration ---
# Define the Docker image for the Modal function.
# Ensure PyTorch is installed with CUDA support. Modal's newer base images with GPU selection often handle this well.
# Specify exact versions if compatibility issues arise.
gpu_image = modal.Image.debian_slim().pip_install(
    "torch", # Let Modal manage CUDA versioning if possible, or specify e.g., "torch==2.5.1+cu121"
    "transformers",
    "colpali-engine>=0.1.0",
    "Pillow",
    "numpy",
    "filetype", # If used in your image decoding logic
    "fastapi",  # Added FastAPI for @modal.fastapi_endpoint
    "uvicorn"   # Added Uvicorn, standard server for FastAPI
).env({
    "HF_HOME": "/cache/huggingface",
    "TRANSFORMERS_CACHE": "/cache/huggingface/models",
    "HF_HUB_CACHE": "/cache/huggingface/hub",
    "PIP_NO_CACHE_DIR": "true", # Avoid caching pip downloads in the image layer if not needed
})

# --- Pydantic Model for Request Body ---
class EmbeddingRequest(BaseModel):
    input_type: str
    inputs: List[str] # Keep as List[str] as this is what we believe is correct

# --- Modal Class for the Service ---
@app.cls(
    gpu="T4",  # Or "A10G". Consider instance type based on cost/performance needs.
    image=gpu_image,
    scaledown_window=300,  # Spins down after 5 minutes of inactivity. (renamed from container_idle_timeout)
    secrets=[
        modal.Secret.from_name("my-huggingface-secret"), # For HF model download authentication
        modal.Secret.from_name("colpali-service-api-key")  # For securing our endpoint
    ],
    max_containers=10, # Max concurrent requests, tune based on GPU and model performance (renamed from concurrency_limit)
    timeout=600 # Max execution time for a request in seconds
)
class ColpaliModalService:
    def __init__(self):
        print("ColpaliModalService: __init__ starting")
        import torch
        from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
        try:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"ColpaliModalService: Initializing model on device: {self.device}")
            hf_token = os.environ.get("HUGGINGFACE_TOKEN")
            self.service_api_key = os.environ.get("SERVICE_API_KEY")
            if not self.service_api_key:
                print("CRITICAL WARNING: SERVICE_API_KEY is not set! Endpoint will be unsecured.")
            model_name = "tsystems/colqwen2.5-3b-multilingual-v1.0"
            self.model = ColQwen2_5.from_pretrained(
                model_name,
                torch_dtype=torch.bfloat16,
                device_map=self.device,
                attn_implementation="eager",
                token=hf_token,
                cache_dir="/cache/huggingface/models"
            ).eval()
            self.processor = ColQwen2_5_Processor.from_pretrained(
                model_name,
                token=hf_token,
                cache_dir="/cache/huggingface/hub"
            )
            print(f"ColpaliModalService: Model and processor loaded on {self.device}.")
        except Exception as e:
            print(f"ColpaliModalService: Exception during __init__: {e}")
            raise

    def _decode_image(self, base64_string: str):
        from PIL.Image import open as open_image
        # Basic check if it might be a data URI
        if base64_string.startswith("data:"):
            try:
                base64_string = base64_string.split(",", 1)[1]
            except IndexError:
                raise ValueError("Malformed data URI string for image decoding.")
        try:
            image_bytes = base64.b64decode(base64_string)
            return open_image(io.BytesIO(image_bytes))
        except Exception as e:
            raise ValueError(f"Failed to decode base64 image: {e}")

    @modal.fastapi_endpoint(method="POST", label="embeddings")
    async def generate_embeddings_endpoint(self, payload: EmbeddingRequest):
        import torch
        import numpy as np
        from fastapi.responses import JSONResponse
        input_type = payload.input_type
        inputs_data = payload.inputs
        if not inputs_data:
            return {"embeddings": []}
        print(f"Authenticated request. Processing: input_type='{input_type}', num_inputs={len(inputs_data)}")
        all_embeddings_list = []
        batch_size = 8 if input_type == "text" else 4
        try:
            for i in range(0, len(inputs_data), batch_size):
                batch_input_data = inputs_data[i:i + batch_size]
                processed_batch = None
                if input_type == "image":
                    pil_images = [self._decode_image(b64_str) for b64_str in batch_input_data]
                    if not pil_images: continue
                    processed_batch = self.processor.process_images(pil_images).to(self.device)
                elif input_type == "text":
                    if not all(isinstance(text, str) for text in batch_input_data):
                        return JSONResponse(content={"error": "Invalid text inputs, not all are strings"}, status_code=400)
                    processed_batch = self.processor.process_queries(batch_input_data).to(self.device)
                else:
                    return JSONResponse(content={"error": "Invalid input_type"}, status_code=400)
                if processed_batch:
                    with torch.no_grad():
                        embedding_tensor = self.model(**processed_batch)
                    current_batch_embeddings_np = embedding_tensor.to(torch.float32).cpu().numpy().tolist()
                    all_embeddings_list.extend(current_batch_embeddings_np)
        except ValueError as ve:
            print(f"ValueError during processing: {ve}")
            return JSONResponse(content={"error": f"Input processing error: {str(ve)}"}, status_code=400)
        except Exception as e:
            print(f"Unexpected error during embedding generation: {e}")
            return JSONResponse(content={"error": "Internal server error during embedding"}, status_code=500)
        return {"embeddings": all_embeddings_list} 