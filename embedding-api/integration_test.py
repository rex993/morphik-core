#!/usr/bin/env python3
"""
Integration test script to verify the embedding API service works with Morphik's ColpaliApiEmbeddingModel.

This script simulates how Morphik would use the API service.
"""

import asyncio
import base64
import io
import os
import sys
from typing import List

# Add the core directory to the Python path to import Morphik modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from core.embedding.colpali_api_embedding_model import ColpaliApiEmbeddingModel
    from core.models.chunk import Chunk
    from PIL import Image, ImageDraw
except ImportError as e:
    print(f"❌ Failed to import Morphik modules: {e}")
    print("Make sure you're running this from the embedding-api directory")
    print("and that the core Morphik modules are available.")
    sys.exit(1)

def create_test_image() -> str:
    """Create a test image and return as base64 data URI."""
    img = Image.new('RGB', (300, 200), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "ColPali Integration Test", fill='black')
    draw.text((10, 40), "This image contains sample text", fill='blue')
    draw.rectangle([(10, 70), (290, 190)], outline='red', width=3)
    draw.text((20, 100), "For testing multi-vector embeddings", fill='green')
    
    # Convert to base64 data URI
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{img_b64}"

async def test_morphik_integration():
    """Test the API service using Morphik's ColpaliApiEmbeddingModel."""
    print("🔗 Testing Morphik Integration with ColPali API Service")
    print("=" * 60)
    
    # Set up environment for testing
    os.environ['MORPHIK_EMBEDDING_API_KEY'] = 'your-secret-api-key'
    os.environ['MORPHIK_EMBEDDING_API_DOMAIN'] = 'http://localhost:8000'
    
    try:
        # Initialize the API embedding model
        print("🏗️  Initializing ColpaliApiEmbeddingModel...")
        embedding_model = ColpaliApiEmbeddingModel()
        print(f"✅ Model initialized with endpoint: {embedding_model.endpoint}")
        
        # Test 1: Single text query embedding
        print("\n📝 Test 1: Single text query embedding")
        test_query = "What is machine learning and how does it work?"
        
        try:
            query_embedding = await embedding_model.embed_for_query(test_query)
            print(f"✅ Query embedding generated successfully")
            print(f"   Embedding shape: {len(query_embedding)} vectors")
            print(f"   Vector dimensions: {len(query_embedding[0])}")
        except Exception as e:
            print(f"❌ Query embedding failed: {e}")
            return False
        
        # Test 2: Text chunks for ingestion
        print("\n📄 Test 2: Text chunks for ingestion")
        text_chunks = [
            Chunk(
                id="chunk_1",
                content="Artificial intelligence is transforming modern technology.",
                metadata={"type": "text", "source": "document1.txt"}
            ),
            Chunk(
                id="chunk_2", 
                content="Neural networks are inspired by biological brain structures.",
                metadata={"type": "text", "source": "document2.txt"}
            )
        ]
        
        try:
            text_embeddings = await embedding_model.embed_for_ingestion(text_chunks)
            print(f"✅ Text ingestion embeddings generated successfully")
            print(f"   Number of chunks processed: {len(text_embeddings)}")
            print(f"   First embedding shape: {len(text_embeddings[0])} vectors")
        except Exception as e:
            print(f"❌ Text ingestion embedding failed: {e}")
            return False
        
        # Test 3: Image chunks for ingestion
        print("\n🖼️  Test 3: Image chunks for ingestion")
        image_data = create_test_image()
        image_chunks = [
            Chunk(
                id="img_chunk_1",
                content=image_data,
                metadata={"is_image": True, "source": "test_image.png"}
            )
        ]
        
        try:
            image_embeddings = await embedding_model.embed_for_ingestion(image_chunks)
            print(f"✅ Image ingestion embeddings generated successfully")
            print(f"   Number of image chunks processed: {len(image_embeddings)}")
            print(f"   Image embedding shape: {len(image_embeddings[0])} vectors")
        except Exception as e:
            print(f"❌ Image ingestion embedding failed: {e}")
            return False
        
        # Test 4: Mixed text and image chunks
        print("\n🔀 Test 4: Mixed text and image chunks")
        mixed_chunks = text_chunks + image_chunks
        
        try:
            mixed_embeddings = await embedding_model.embed_for_ingestion(mixed_chunks)
            print(f"✅ Mixed ingestion embeddings generated successfully")
            print(f"   Total chunks processed: {len(mixed_embeddings)}")
            print(f"   Text chunks: {len(text_chunks)}")
            print(f"   Image chunks: {len(image_chunks)}")
        except Exception as e:
            print(f"❌ Mixed ingestion embedding failed: {e}")
            return False
        
        # Test 5: Empty input handling
        print("\n🚫 Test 5: Empty input handling")
        try:
            empty_embeddings = await embedding_model.embed_for_ingestion([])
            if len(empty_embeddings) == 0:
                print(f"✅ Empty input handled correctly")
            else:
                print(f"❌ Empty input handling unexpected result: {len(empty_embeddings)}")
                return False
        except Exception as e:
            print(f"❌ Empty input handling failed: {e}")
            return False
        
        print("\n🎉 All integration tests passed!")
        print("The ColPali API service is fully compatible with Morphik's embedding client.")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed with exception: {e}")
        return False

async def test_performance():
    """Test performance with larger batches."""
    print("\n⚡ Performance Test")
    print("=" * 30)
    
    try:
        embedding_model = ColpaliApiEmbeddingModel()
        
        # Large text batch
        import time
        large_text_batch = [
            Chunk(
                id=f"perf_chunk_{i}",
                content=f"This is test document number {i} with sample content for performance testing.",
                metadata={"type": "text", "batch": "performance_test"}
            )
            for i in range(20)  # Test with 20 text chunks
        ]
        
        start_time = time.time()
        perf_embeddings = await embedding_model.embed_for_ingestion(large_text_batch)
        elapsed_time = time.time() - start_time
        
        print(f"✅ Performance test completed")
        print(f"   Processed {len(large_text_batch)} text chunks")
        print(f"   Total time: {elapsed_time:.2f}s")
        print(f"   Average per chunk: {elapsed_time/len(large_text_batch):.3f}s")
        print(f"   Throughput: {len(large_text_batch)/elapsed_time:.1f} chunks/second")
        
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all integration tests."""
    print("🚀 ColPali API Service Integration Tests")
    print("Verifying compatibility with Morphik's ColpaliApiEmbeddingModel")
    print("=" * 70)
    
    # Check if service is running
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/health", timeout=5.0)
            if response.status_code != 200:
                print("❌ API service is not responding correctly")
                print("Please make sure the service is running on localhost:8000")
                return
            else:
                health_data = response.json()
                print(f"✅ API service is running (status: {health_data['status']})")
    except Exception as e:
        print(f"❌ Cannot connect to API service: {e}")
        print("Please start the service with: ./start_service.sh")
        return
    
    # Run integration tests
    integration_success = await test_morphik_integration()
    
    if integration_success:
        # Run performance test
        perf_success = await test_performance()
        
        if perf_success:
            print("\n" + "=" * 70)
            print("🎯 ALL TESTS PASSED!")
            print("The ColPali API service is ready for production use with Morphik.")
            print("\nNext steps:")
            print("1. Update your Morphik configuration to use this API service")
            print("2. Set MORPHIK_EMBEDDING_API_KEY in your environment")
            print("3. Set MORPHIK_EMBEDDING_API_DOMAIN=http://localhost:8000")
        else:
            print("\n❌ Performance tests failed")
    else:
        print("\n❌ Integration tests failed")

if __name__ == "__main__":
    asyncio.run(main())