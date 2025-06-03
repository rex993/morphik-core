#!/usr/bin/env python3
"""
Test script for ColPali Embedding API Service

This script tests the API service with sample text and image inputs.
"""

import asyncio
import base64
import io
import json
import time
from typing import Dict, List

import httpx
from PIL import Image, ImageDraw

# Configuration
API_BASE_URL = "http://localhost:8000"
API_KEY = "your-secret-api-key"

async def test_health_check():
    """Test the health check endpoint."""
    print("🔍 Testing health check...")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/health", timeout=10.0)
            if response.status_code == 200:
                health_data = response.json()
                print(f"✅ Health check passed")
                print(f"   Status: {health_data['status']}")
                print(f"   Model loaded: {health_data['model_loaded']}")
                print(f"   Device: {health_data['device']}")
                print(f"   Uptime: {health_data['uptime_seconds']:.1f}s")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False

def create_test_image() -> str:
    """Create a simple test image and return as base64."""
    # Create a simple test image
    img = Image.new('RGB', (200, 100), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "Test Image for ColPali", fill='black')
    draw.rectangle([(10, 40), (190, 90)], outline='blue', width=2)
    
    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return img_b64

async def test_text_embeddings():
    """Test text embedding generation."""
    print("\n📝 Testing text embeddings...")
    
    test_texts = [
        "What is artificial intelligence?",
        "How do neural networks work?",
        "Machine learning algorithms explained"
    ]
    
    payload = {
        "input_type": "text",
        "inputs": test_texts
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            response = await client.post(
                f"{API_BASE_URL}/embeddings",
                json=payload,
                headers=headers,
                timeout=60.0
            )
            elapsed_time = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                embeddings = result["embeddings"]
                
                print(f"✅ Text embeddings generated successfully")
                print(f"   Processed {len(test_texts)} texts in {elapsed_time:.2f}s")
                print(f"   Average time per text: {elapsed_time/len(test_texts):.3f}s")
                print(f"   Embedding shape: {len(embeddings[0])} vectors x {len(embeddings[0][0])} dimensions")
                return True
            else:
                print(f"❌ Text embedding failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Text embedding error: {e}")
            return False

async def test_image_embeddings():
    """Test image embedding generation."""
    print("\n🖼️  Testing image embeddings...")
    
    # Create test images
    test_images = [create_test_image()]
    
    payload = {
        "input_type": "image",
        "inputs": test_images
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            response = await client.post(
                f"{API_BASE_URL}/embeddings",
                json=payload,
                headers=headers,
                timeout=120.0
            )
            elapsed_time = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                embeddings = result["embeddings"]
                
                print(f"✅ Image embeddings generated successfully")
                print(f"   Processed {len(test_images)} images in {elapsed_time:.2f}s")
                print(f"   Average time per image: {elapsed_time/len(test_images):.3f}s")
                print(f"   Embedding shape: {len(embeddings[0])} vectors x {len(embeddings[0][0])} dimensions")
                return True
            else:
                print(f"❌ Image embedding failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Image embedding error: {e}")
            return False

async def test_authentication():
    """Test authentication with invalid API key."""
    print("\n🔐 Testing authentication...")
    
    payload = {
        "input_type": "text",
        "inputs": ["test"]
    }
    
    headers = {
        "Authorization": "Bearer invalid-key",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/embeddings",
                json=payload,
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 401:
                print(f"✅ Authentication test passed (correctly rejected invalid key)")
                return True
            else:
                print(f"❌ Authentication test failed: expected 401, got {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Authentication test error: {e}")
            return False

async def test_error_handling():
    """Test error handling with invalid requests."""
    print("\n⚠️  Testing error handling...")
    
    # Test invalid input type
    payload = {
        "input_type": "invalid",
        "inputs": ["test"]
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/embeddings",
                json=payload,
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 400:
                print(f"✅ Error handling test passed (correctly rejected invalid input_type)")
                return True
            else:
                print(f"❌ Error handling test failed: expected 400, got {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error handling test error: {e}")
            return False

async def main():
    """Run all tests."""
    print("🚀 Starting ColPali Embedding API Tests")
    print(f"   API URL: {API_BASE_URL}")
    print("=" * 50)
    
    tests = [
        ("Health Check", test_health_check),
        ("Authentication", test_authentication),
        ("Error Handling", test_error_handling),
        ("Text Embeddings", test_text_embeddings),
        ("Image Embeddings", test_image_embeddings),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status} {test_name}")
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! API service is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the service configuration.")

if __name__ == "__main__":
    asyncio.run(main())