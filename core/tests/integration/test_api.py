import asyncio
import json
import logging
import os
import sys
import uuid  # , override
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator, Dict

import filetype
import jwt
import pydantic
import pytest
from dotenv import load_dotenv
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import get_settings
from core.models.prompts import EntityExtractionPromptOverride, EntityResolutionPromptOverride, GraphPromptOverrides
from core.tests import setup_test_logging

# Set up logging for tests
setup_test_logging()
logger = logging.getLogger(__name__)

load_dotenv(override=True)

# Get settings from the server configuration
settings = get_settings()

# Test configuration
TEST_DATA_DIR = Path(__file__).parent / "test_data"
TEST_USER_ID = "test_user"
TEST_SERVER_URL = os.getenv("TEST_SERVER_URL", "http://localhost:8000")


def confirm_test_database():
    """Confirm that we're using a test database before running tests."""
    expected_test_uri = "postgresql+asyncpg://morphik@localhost:5432/morphik_test"
    actual_uri = settings.POSTGRES_URI

    if not actual_uri:
        logger.critical("POSTGRES_URI not set in .env file! Tests aborted to prevent accidental data loss.")
        logger.critical("Please configure a test database before running integration tests.")
        sys.exit(1)
    elif expected_test_uri != actual_uri:
        logger.critical("POSTGRES_URI is not set to the expected test database!")
        logger.critical(f"Expected: {expected_test_uri}")
        logger.critical(f"Actual: {actual_uri}")
        logger.critical("Tests aborted to prevent modifying production data.")
        logger.critical("Please configure a test database before running integration tests.")
        sys.exit(1)
    else:
        logger.info(f"Using test database: {actual_uri}")


# Run the confirmation check when the module is loaded
confirm_test_database()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_environment(event_loop):
    """Setup test environment and create test files"""
    # Create test data directory if it doesn't exist
    TEST_DATA_DIR.mkdir(exist_ok=True)

    # Create a test text file
    text_file = TEST_DATA_DIR / "test.txt"
    if not text_file.exists():
        text_file.write_text("This is a test document for Morphik testing.")

    # Create a small test PDF if it doesn't exist
    pdf_file = TEST_DATA_DIR / "test.pdf"
    if not pdf_file.exists():
        pytest.skip("PDF file not available, skipping PDF tests")


def create_test_token(
    entity_type: str = "developer",
    entity_id: str = TEST_USER_ID,
    permissions: list = None,
    app_id: str = None,
    expired: bool = False,
) -> str:
    """Create a test JWT token"""
    if not permissions:
        permissions = ["read", "write", "admin"]

    payload = {
        "type": entity_type,
        "entity_id": entity_id,
        "permissions": permissions,
        "exp": datetime.now(UTC) + timedelta(days=-1 if expired else 1),
    }

    if app_id:
        payload["app_id"] = app_id

    # Use JWT_SECRET_KEY from server settings instead of hardcoding
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def create_auth_header(
    entity_type: str = "developer", permissions: list = None, expired: bool = False
) -> Dict[str, str]:
    """Create authorization header with test token"""
    token = create_test_token(entity_type, permissions=permissions, expired=expired)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function", autouse=True)
async def cleanup_redis():
    """Placeholder for Redis cleanup - modified for external server"""
    yield
    # We no longer directly control the Redis connection in tests
    # as we're using an external server


@pytest.fixture
async def client(event_loop: asyncio.AbstractEventLoop, cleanup_redis) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client that connects to a running server"""
    # Verify that the server is running
    try:
        async with AsyncClient(base_url=TEST_SERVER_URL, timeout=30.0) as check_client:
            # First try the /ping endpoint
            try:
                response = await check_client.get(f"{TEST_SERVER_URL}/ping", timeout=5.0)
                if response.status_code != 200:
                    # If /ping fails, try the root endpoint
                    response = await check_client.get(TEST_SERVER_URL, timeout=5.0)
                    if response.status_code >= 400:
                        logger.critical(f"Server at {TEST_SERVER_URL} is not responding properly. Tests will not run.")
                        sys.exit(1)
            except Exception:
                # If /ping fails, try the root endpoint
                response = await check_client.get(TEST_SERVER_URL, timeout=5.0)
                if response.status_code >= 400:
                    logger.critical(f"Server at {TEST_SERVER_URL} is not responding properly. Tests will not run.")
                    sys.exit(1)
    except Exception as e:
        logger.critical(f"Server at {TEST_SERVER_URL} is not running. Tests will not run. Error: {e}")
        sys.exit(1)

    async with AsyncClient(base_url=TEST_SERVER_URL, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="function", autouse=True)
async def cleanup_documents():
    """Clean up documents before each document test"""
    # This will run before the test
    yield
    # This will run after the test

    # We should always use the test database
    # Create a fresh connection to make sure we're not affected by any state
    postgres_uri = settings.POSTGRES_URI
    if not postgres_uri:
        logger.warning("POSTGRES_URI not set, skipping document cleanup")
        return

    engine = create_async_engine(postgres_uri)

    try:
        async with engine.begin() as conn:
            # Clean up by deleting all rows rather than dropping tables
            await conn.execute(text("DELETE FROM documents"))

            # Delete from chunks table
            try:
                await conn.execute(text("DELETE FROM vector_embeddings"))
            except Exception as e:
                logger.info(f"No chunks table to clean or error: {e}")

            try:
                await conn.execute(text("DELETE FROM chat_conversations"))
            except Exception:
                logger.info("No chat_conversations table to clean")

    except Exception as e:
        logger.error(f"Failed to clean up document tables: {e}")
        raise
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_text_document(client: AsyncClient, content: str = "Test content for document ingestion"):
    """Test ingesting a text document"""
    headers = create_auth_header()

    response = await client.post(
        "/ingest/text",
        json={"content": content, "metadata": {"test": True, "type": "text"}, "use_colpali": True},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "external_id" in data
    assert data["content_type"] == "text/plain"
    assert data["metadata"]["test"] is True

    return data["external_id"]


@pytest.mark.asyncio
async def test_ingest_text_document_with_metadata(
    client: AsyncClient,
    content: str = "Test content for document ingestion",
    metadata: dict = {"k": "v"},
):
    """Test ingesting a text document with metadata"""
    headers = create_auth_header()

    response = await client.post(
        "/ingest/text",
        json={"content": content, "metadata": metadata},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "external_id" in data
    assert data["content_type"] == "text/plain"

    for key, value in (metadata or {}).items():
        assert data["metadata"][key] == value

    return data["external_id"]


@pytest.mark.asyncio
async def test_ingest_text_document_folder_user(
    client: AsyncClient,
    content: str = "Test content for document ingestion with folder and user scoping",
    metadata: dict = {},
    folder_name: str = "test_folder",
    end_user_id: str = "test_user@example.com",
):
    """Test ingesting a text document with folder and user scoping"""
    headers = create_auth_header()

    response = await client.post(
        "/ingest/text",
        json={
            "content": content,
            "metadata": metadata or {},
            "folder_name": folder_name,
            "end_user_id": end_user_id,
        },
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "external_id" in data
    assert data["content_type"] == "text/plain"
    assert data["system_metadata"]["folder_name"] == folder_name
    assert data["system_metadata"]["end_user_id"] == end_user_id

    for key, value in (metadata or {}).items():
        assert data["metadata"][key] == value

    return data["external_id"]


@pytest.mark.asyncio
async def test_ingest_pdf(client: AsyncClient):
    """Test ingesting a pdf"""
    headers = create_auth_header()
    pdf_path = TEST_DATA_DIR / "test.pdf"

    if not pdf_path.exists():
        pytest.skip("Test PDF file not available")

    content_type = filetype.guess(pdf_path).mime
    if not content_type:
        content_type = "application/octet-stream"

    with open(pdf_path, "rb") as f:
        response = await client.post(
            "/ingest/file",
            files={"file": (pdf_path.name, f, content_type)},
            data={"metadata": json.dumps({"test": True, "type": "pdf"}), "use_colpali": True},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert "external_id" in data
    assert data["content_type"] == "application/pdf"
    assert "storage_info" in data

    return data["external_id"]


@pytest.mark.asyncio
async def test_ingest_invalid_text_request(client: AsyncClient):
    """Test ingestion with invalid text request missing required content field"""
    headers = create_auth_header()

    response = await client.post(
        "/ingest/text",
        json={"wrong_field": "Test content"},  # Missing required content field
        headers=headers,
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_ingest_invalid_file_request(client: AsyncClient):
    """Test ingestion with invalid file request missing file"""
    headers = create_auth_header()

    response = await client.post(
        "/ingest/file",
        files={},  # Missing file
        data={"metadata": "{}"},
        headers=headers,
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_ingest_invalid_metadata(client: AsyncClient):
    """Test ingestion with invalid metadata JSON"""
    headers = create_auth_header()

    pdf_path = TEST_DATA_DIR / "test.pdf"
    if pdf_path.exists():
        files = {"file": ("test.pdf", open(pdf_path, "rb"), "application/pdf")}
        response = await client.post(
            "/ingest/file",
            files=files,
            data={"metadata": "invalid json"},
            headers=headers,
        )
        assert response.status_code == 400  # Bad request


@pytest.mark.asyncio
async def test_auth_missing_header(client: AsyncClient):
    """Test authentication with missing auth header"""
    if get_settings().dev_mode:
        pytest.skip("Auth tests skipped in dev mode")
    response = await client.post("/ingest/text")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_invalid_token(client: AsyncClient):
    """Test authentication with invalid token"""
    if get_settings().dev_mode:
        pytest.skip("Auth tests skipped in dev mode")
    headers = {"Authorization": "Bearer invalid_token"}
    response = await client.post("/ingest/file", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_expired_token(client: AsyncClient):
    """Test authentication with expired token"""
    if get_settings().dev_mode:
        pytest.skip("Auth tests skipped in dev mode")
    headers = create_auth_header(expired=True)
    response = await client.post("/ingest/text", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_insufficient_permissions(client: AsyncClient):
    """Test authentication with insufficient permissions"""
    if get_settings().dev_mode:
        pytest.skip("Auth tests skipped in dev mode")
    headers = create_auth_header(permissions=["read"])
    response = await client.post(
        "/ingest/text",
        json={"content": "Test content", "metadata": {}},
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient):
    """Test listing documents"""
    # First ingest some documents
    doc_id1 = await test_ingest_text_document(client)
    doc_id2 = await test_ingest_text_document(client)

    headers = create_auth_header()
    # Test without filters
    response = await client.post("/documents", headers=headers)

    assert response.status_code == 200
    docs = response.json()
    assert len(docs) >= 2
    doc_ids = [doc["external_id"] for doc in docs]
    assert doc_id1 in doc_ids
    assert doc_id2 in doc_ids

    # Test with filters
    metadata = {"test_specific": "filter_value"}
    doc_id3 = await test_ingest_text_document_with_metadata(client, metadata=metadata)

    response = await client.post("/documents?skip=0&limit=10", json={"test_specific": "filter_value"}, headers=headers)

    assert response.status_code == 200
    filtered_docs = response.json()
    filtered_doc_ids = [doc["external_id"] for doc in filtered_docs]
    assert doc_id3 in filtered_doc_ids


@pytest.mark.asyncio
async def test_get_document(client: AsyncClient):
    """Test getting a specific document"""
    # First ingest a document
    doc_id = await test_ingest_text_document(client)

    headers = create_auth_header()
    response = await client.get(f"/documents/{doc_id}", headers=headers)

    assert response.status_code == 200
    doc = response.json()
    assert doc["external_id"] == doc_id
    assert "metadata" in doc
    assert "content_type" in doc


@pytest.mark.asyncio
async def test_get_document_by_filename(client: AsyncClient):
    """Test getting a document by filename"""
    # First ingest a document with a specific filename
    filename = "test_get_by_filename.txt"
    headers = create_auth_header()

    initial_content = "This is content for testing get_document_by_filename."
    response = await client.post(
        "/ingest/text",
        json={
            "content": initial_content,
            "filename": filename,
            "metadata": {"test": True, "type": "text"},
        },
        headers=headers,
    )

    assert response.status_code == 200
    doc_id = response.json()["external_id"]

    # Now try to get the document by filename
    response = await client.get(f"/documents/filename/{filename}", headers=headers)

    assert response.status_code == 200
    doc = response.json()
    assert doc["external_id"] == doc_id
    assert doc["filename"] == filename
    assert "metadata" in doc
    assert "content_type" in doc


@pytest.mark.asyncio
async def test_invalid_document_id(client: AsyncClient):
    """Test error handling for invalid document ID"""
    headers = create_auth_header()
    response = await client.get("/documents/invalid_id", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_document_with_text(client: AsyncClient):
    """Test updating a document with text content"""
    # First ingest a document to update
    initial_content = "This is the initial content for update testing."
    doc_id = await test_ingest_text_document(client, content=initial_content)

    headers = create_auth_header()
    update_content = "This is additional content for the document."

    # Test updating with text content
    response = await client.post(
        f"/documents/{doc_id}/update_text",
        json={
            "content": update_content,
            "metadata": {"updated": True, "version": "2.0"},
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["external_id"] == doc_id
    assert updated_doc["metadata"]["updated"] is True
    assert updated_doc["metadata"]["version"] == "2.0"

    # Verify the content was updated by retrieving chunks
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "additional content",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )

    assert search_response.status_code == 200
    chunks = search_response.json()
    assert len(chunks) > 0
    assert any(update_content in chunk["content"] for chunk in chunks)


@pytest.mark.asyncio
async def test_update_document_with_file(client: AsyncClient):
    """Test updating a document with file content"""
    # First ingest a document to update
    initial_content = "This is the initial content for file update testing."
    doc_id = await test_ingest_text_document(client, content=initial_content)

    headers = create_auth_header()

    # Create a test file to upload
    test_file_path = TEST_DATA_DIR / "update_test.txt"
    update_content = "This is file content for updating the document."
    test_file_path.write_text(update_content)

    with open(test_file_path, "rb") as f:
        response = await client.post(
            f"/documents/{doc_id}/update_file",
            files={"file": ("update_test.txt", f, "text/plain")},
            data={
                "metadata": json.dumps({"updated_with_file": True}),
                "rules": json.dumps([]),
                "update_strategy": "add",
            },
            headers=headers,
        )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["external_id"] == doc_id
    assert updated_doc["metadata"]["updated_with_file"] is True

    # Verify the content was updated by retrieving chunks
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "file content for updating",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )

    assert search_response.status_code == 200
    chunks = search_response.json()
    assert len(chunks) > 0
    assert any(update_content in chunk["content"] for chunk in chunks)

    # Clean up the test file
    test_file_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_update_document_metadata(client: AsyncClient):
    """Test updating only a document's metadata"""
    # First ingest a document to update
    initial_content = "This is the content for metadata update testing."
    doc_id = await test_ingest_text_document(client, content=initial_content)

    headers = create_auth_header()

    # Test updating just metadata
    new_metadata = {"meta_updated": True, "tags": ["test", "metadata", "update"], "priority": 1}

    response = await client.post(
        f"/documents/{doc_id}/update_metadata",
        json=new_metadata,
        headers=headers,
    )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["external_id"] == doc_id

    # Verify the response has the updated metadata
    assert updated_doc["metadata"]["meta_updated"] is True
    assert "test" in updated_doc["metadata"]["tags"]
    assert updated_doc["metadata"]["priority"] == 1

    # Fetch the document to verify it exists
    get_response = await client.get(f"/documents/{doc_id}", headers=headers)
    assert get_response.status_code == 200

    # Note: Depending on caching or database behavior, the metadata may not be
    # immediately visible in a subsequent fetch. The important part is that
    # the update operation itself returned the correct metadata.


@pytest.mark.asyncio
async def test_update_document_with_rules(client: AsyncClient):
    """Test updating a document with text content and applying rules"""
    # First ingest a document to update
    initial_content = "This is the initial content for rule testing."
    doc_id = await test_ingest_text_document(client, content=initial_content)

    headers = create_auth_header()
    update_content = (
        "This document contains information about John Doe who lives at 123 Main St and has SSN 123-45-6789."
    )

    # Create a rule to apply during update (natural language rule to remove PII)
    rule = {
        "type": "natural_language",
        "prompt": "Remove all personally identifiable information (PII) such as names, addresses, and SSNs.",
    }

    # Test updating with text content and a rule
    response = await client.post(
        f"/documents/{doc_id}/update_text",
        json={
            "content": update_content,
            "metadata": {"contains_pii": False},
            "rules": [rule],
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["external_id"] == doc_id
    assert updated_doc["metadata"]["contains_pii"] is False

    # Verify the content was updated and PII was removed by retrieving chunks
    # Note: Exact behavior depends on the LLM response, so we check that something changed
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "information about person",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )

    assert search_response.status_code == 200
    chunks = search_response.json()
    assert len(chunks) > 0
    # The processed content should have some of the original content but not the PII
    assert any("information" in chunk["content"] for chunk in chunks)
    # Check that at least one of the PII elements is not in the content
    # This is a loose check since the exact result depends on the LLM
    content_text = " ".join([chunk["content"] for chunk in chunks])
    has_some_pii_removed = (
        ("John Doe" not in content_text) or ("123-45-6789" not in content_text) or ("123 Main St" not in content_text)
    )
    assert has_some_pii_removed, "Rule to remove PII did not seem to have any effect"


@pytest.mark.asyncio
async def test_file_versioning_with_add_strategy(client: AsyncClient):
    """Test that file versioning works correctly with 'add' update strategy"""
    # First ingest a document with a file
    headers = create_auth_header()

    # Create the initial file
    initial_file_path = TEST_DATA_DIR / "version_test_1.txt"
    initial_content = "This is version 1 of the file for testing versioning."
    initial_file_path.write_text(initial_content)

    # Ingest the initial file
    with open(initial_file_path, "rb") as f:
        response = await client.post(
            "/ingest/file",
            files={"file": ("version_test.txt", f, "text/plain")},
            data={
                "metadata": json.dumps({"test": True, "version": 1}),
                "rules": json.dumps([]),
            },
            headers=headers,
        )

    assert response.status_code == 200
    doc_id = response.json()["external_id"]
    # Wait for the document to be fully processed
    await asyncio.sleep(5)

    # Create second version of the file
    second_file_path = TEST_DATA_DIR / "version_test_2.txt"
    second_content = "This is version 2 of the file for testing versioning."
    second_file_path.write_text(second_content)

    # Update with second file using "add" strategy
    with open(second_file_path, "rb") as f:
        response = await client.post(
            f"/documents/{doc_id}/update_file",
            files={"file": ("version_test_v2.txt", f, "text/plain")},
            data={
                "metadata": json.dumps({"test": True, "version": 2}),
                "rules": json.dumps([]),
                "update_strategy": "add",
            },
            headers=headers,
        )

    assert response.status_code == 200

    # Create third version of the file
    third_file_path = TEST_DATA_DIR / "version_test_3.txt"
    third_content = "This is version 3 of the file for testing versioning."
    third_file_path.write_text(third_content)

    # Update with third file using "add" strategy
    with open(third_file_path, "rb") as f:
        response = await client.post(
            f"/documents/{doc_id}/update_file",
            files={"file": ("version_test_v3.txt", f, "text/plain")},
            data={
                "metadata": json.dumps({"test": True, "version": 3}),
                "rules": json.dumps([]),
                "update_strategy": "add",
            },
            headers=headers,
        )

    assert response.status_code == 200
    final_doc = response.json()

    # Verify the system_metadata has versioning info
    assert final_doc["system_metadata"]["version"] >= 3
    assert "update_history" in final_doc["system_metadata"]
    assert len(final_doc["system_metadata"]["update_history"]) >= 2  # At least 2 updates

    # Verify storage_files field exists and has multiple entries
    assert "storage_files" in final_doc
    assert len(final_doc["storage_files"]) >= 3  # Should have at least 3 files

    # Get most recent file's content through search
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "version 3 testing versioning",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )
    assert search_response.status_code == 200
    chunks = search_response.json()
    assert any(third_content in chunk["content"] for chunk in chunks)

    # Also check for version 1 content, which should still be in the merged content
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "version 1 testing versioning",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )
    assert search_response.status_code == 200
    chunks = search_response.json()
    # assert any(initial_content in chunk["content"] for chunk in chunks)

    # Clean up test files
    initial_file_path.unlink(missing_ok=True)
    second_file_path.unlink(missing_ok=True)
    third_file_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_folder_api_operations(client: AsyncClient):
    """Test folder API operations (create, list, get, add/remove documents)."""
    headers = create_auth_header()

    # Create a new folder
    folder_name = "Test API Folder"
    folder_description = "This is a test folder created via API"

    response = await client.post(
        "/folders",
        json={"name": folder_name, "description": folder_description},
        headers=headers,
    )

    assert response.status_code == 200
    folder = response.json()
    assert "id" in folder
    assert folder["name"] == folder_name
    assert folder["description"] == folder_description

    folder_id = folder["id"]

    # Create a document to add to the folder
    doc_content = "This is a test document for folder API testing."
    doc_id = await test_ingest_text_document(client, content=doc_content)

    # Add document to folder
    response = await client.post(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"

    # Get folder to verify document was added
    response = await client.get(
        f"/folders/{folder_id}",
        headers=headers,
    )

    assert response.status_code == 200
    folder = response.json()
    assert doc_id in folder["document_ids"]

    # List all folders
    response = await client.get(
        "/folders",
        headers=headers,
    )

    assert response.status_code == 200
    folders = response.json()
    assert len(folders) > 0
    assert any(f["id"] == folder_id for f in folders)

    # Remove document from folder
    response = await client.delete(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"

    # Get folder again to verify document was removed
    response = await client.get(
        f"/folders/{folder_id}",
        headers=headers,
    )

    assert response.status_code == 200
    folder = response.json()
    assert doc_id not in folder["document_ids"]

    # Verify document still exists in the system
    doc_response = await client.get(
        f"/documents/{doc_id}",
        headers=headers,
    )
    assert doc_response.status_code == 200


@pytest.mark.asyncio
async def test_folder_search_operations(client: AsyncClient):
    """Test search operations with folder scoping using the folder API."""
    headers = create_auth_header()

    # Create two test folders
    folder1_name = "Search Test Folder 1"
    response = await client.post(
        "/folders",
        json={"name": folder1_name},
        headers=headers,
    )
    assert response.status_code == 200
    folder1_id = response.json()["id"]

    folder2_name = "Search Test Folder 2"
    response = await client.post(
        "/folders",
        json={"name": folder2_name},
        headers=headers,
    )
    assert response.status_code == 200
    folder2_id = response.json()["id"]

    # Create documents with distinctive content for each folder
    doc1_content = "This document contains unique information about apples and bananas."
    doc1_id = await test_ingest_text_document(client, content=doc1_content)

    doc2_content = "This document has specific details about oranges and grapefruits."
    doc2_id = await test_ingest_text_document(client, content=doc2_content)

    # Add documents to respective folders
    await client.post(
        f"/folders/{folder1_id}/documents/{doc1_id}",
        headers=headers,
    )

    await client.post(
        f"/folders/{folder2_id}/documents/{doc2_id}",
        headers=headers,
    )

    # Test searching within folder1
    response = await client.post(
        "/retrieve/chunks",
        json={"query": "fruit", "folder_name": folder1_name},
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    assert all("apple" in chunk["content"].lower() or "banana" in chunk["content"].lower() for chunk in chunks)
    assert not any("orange" in chunk["content"].lower() or "grapefruit" in chunk["content"].lower() for chunk in chunks)

    # Test searching within folder2
    response = await client.post(
        "/retrieve/chunks",
        json={"query": "fruit", "folder_name": folder2_name},
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    assert all("orange" in chunk["content"].lower() or "grapefruit" in chunk["content"].lower() for chunk in chunks)
    assert not any("apple" in chunk["content"].lower() or "banana" in chunk["content"].lower() for chunk in chunks)

    # Test querying with folder scope
    response = await client.post(
        "/query",
        json={"query": "What fruits are mentioned?", "folder_name": folder1_name},
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert "completion" in result
    # Apples and bananas should be mentioned, not oranges or grapefruits
    apples_bananas_mentioned = "apple" in result["completion"].lower() or "banana" in result["completion"].lower()
    oranges_grapefruits_not_mentioned = (
        "orange" not in result["completion"].lower() and "grapefruit" not in result["completion"].lower()
    )
    assert apples_bananas_mentioned and oranges_grapefruits_not_mentioned


@pytest.mark.asyncio
async def test_auto_folder_creation_on_ingest(client: AsyncClient):
    """Test automatic folder creation when ingesting with a non-existent folder name."""
    headers = create_auth_header()

    # Generate a unique folder name that doesn't exist yet
    import uuid

    new_folder_name = f"Auto Created Folder {uuid.uuid4()}"

    # First verify the folder doesn't exist
    response = await client.get(
        "/folders",
        headers=headers,
    )
    assert response.status_code == 200
    initial_folders = response.json()
    assert not any(folder["name"] == new_folder_name for folder in initial_folders)

    # Ingest a document specifying the non-existent folder name
    doc_content = "This is a test document for automatic folder creation."

    response = await client.post(
        "/ingest/text",
        json={
            "content": doc_content,
            "metadata": {"auto_folder_test": True},
            "folder_name": new_folder_name,
        },
        headers=headers,
    )

    assert response.status_code == 200
    doc = response.json()
    doc_id = doc["external_id"]
    assert doc["system_metadata"]["folder_name"] == new_folder_name

    # List folders and verify the new folder was automatically created
    response = await client.get(
        "/folders",
        headers=headers,
    )

    assert response.status_code == 200
    folders = response.json()
    matching_folders = [f for f in folders if f["name"] == new_folder_name]
    assert len(matching_folders) == 1
    auto_created_folder = matching_folders[0]

    # Get the folder details
    folder_id = auto_created_folder["id"]
    response = await client.get(
        f"/folders/{folder_id}",
        headers=headers,
    )

    assert response.status_code == 200
    folder_details = response.json()

    # Verify our document is in the folder
    assert doc_id in folder_details["document_ids"]

    # Verify retrieving documents with the folder_name parameter works
    response = await client.post(
        "/documents",
        json={"auto_folder_test": True},
        headers=headers,
        params={"folder_name": new_folder_name},
    )

    assert response.status_code == 200
    folder_docs = response.json()
    assert len(folder_docs) == 1
    assert folder_docs[0]["external_id"] == doc_id


@pytest.mark.asyncio
async def test_folder_api_error_cases(client: AsyncClient):
    """Test error cases for folder API operations."""
    headers = create_auth_header()

    # Test getting non-existent folder
    non_existent_id = "folder_does_not_exist"
    response = await client.get(
        f"/folders/{non_existent_id}",
        headers=headers,
    )
    assert response.status_code == 404

    # Create a folder for further tests
    folder_name = "Error Test Folder"
    create_response = await client.post(
        "/folders",
        json={"name": folder_name},
        headers=headers,
    )
    assert create_response.status_code == 200
    folder_id = create_response.json()["id"]

    # Test adding non-existent document to folder
    response = await client.post(
        f"/folders/{folder_id}/documents/non_existent_doc_id",
        headers=headers,
    )
    assert response.status_code in [404, 500]  # Either not found or operation failed

    # Create a document to test with
    doc_id = await test_ingest_text_document(client, content="Test document for folder error tests")

    # Test adding document to non-existent folder
    response = await client.post(
        f"/folders/non_existent_folder_id/documents/{doc_id}",
        headers=headers,
    )
    assert response.status_code in [404, 500]  # Either not found or operation failed

    # Add document to folder first so we can test duplicate operations
    await client.post(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )

    # Test adding same document to folder twice (should be idempotent)
    response = await client.post(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )
    assert response.status_code == 200  # Should succeed with idempotent behavior

    # Test creating folder with same name (should be idempotent per user)
    response = await client.post(
        "/folders",
        json={"name": folder_name},
        headers=headers,
    )
    assert response.status_code == 200  # Should succeed with idempotent behavior

    # Test removing document that's not in folder (should be idempotent)
    # First remove it
    await client.delete(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )

    # Then try to remove it again
    response = await client.delete(
        f"/folders/{folder_id}/documents/{doc_id}",
        headers=headers,
    )
    assert response.status_code == 200  # Should succeed with idempotent behavior


@pytest.mark.asyncio
async def test_update_document_error_cases(client: AsyncClient):
    """Test error cases for document updates"""
    headers = create_auth_header()

    # Test updating non-existent document by ID
    response = await client.post(
        "/documents/non_existent_id/update_text",
        json={"content": "Test content for non-existent document", "metadata": {}},
        headers=headers,
    )
    assert response.status_code == 404

    # Test updating text without content (validation error)
    doc_id = await test_ingest_text_document(client)
    response = await client.post(
        f"/documents/{doc_id}/update_text",
        json={
            # Missing required content field
            "metadata": {"test": True}
        },
        headers=headers,
    )
    assert response.status_code == 422

    # Test updating with insufficient permissions
    if not get_settings().dev_mode:
        restricted_headers = create_auth_header(permissions=["read"])
        response = await client.post(
            f"/documents/{doc_id}/update_metadata",
            json={"restricted": True},
            headers=restricted_headers,
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_retrieve_chunks(client: AsyncClient):
    """Test retrieving document chunks"""
    upload_string = "The quick brown fox jumps over the lazy dog"
    # First ingest a document to search
    doc_id = await test_ingest_text_document(client, content=upload_string)

    headers = create_auth_header()

    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "jumping fox",
            "k": 1,
            "min_score": 0.0,
            "filters": {"external_id": doc_id},  # Add filter for specific document
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    results = list(response.json())
    assert len(results) > 0
    assert (not get_settings().USE_RERANKING) or results[0]["score"] > 0.5
    assert any(upload_string == result["content"] for result in results)


@pytest.mark.asyncio
async def test_retrieve_docs(client: AsyncClient):
    """Test retrieving full documents"""
    # First ingest a document to search
    content = (
        "Headaches can significantly impact daily life and wellbeing. "
        "Common triggers include stress, dehydration, and poor sleep habits. "
        "While over-the-counter pain relievers may provide temporary relief, "
        "it's important to identify and address the root causes. "
        "Maintaining good health through proper nutrition, regular exercise, "
        "and stress management can help prevent chronic headaches."
    )
    doc_id = await test_ingest_text_document(client, content=content)

    headers = create_auth_header()
    response = await client.post(
        "/retrieve/docs",
        json={
            "query": "Headaches, dehydration",
            "filters": {"test": True, "external_id": doc_id},  # Add filter for specific document
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    results = list(response.json())
    assert len(results) > 0
    assert results[0]["document_id"] == doc_id
    assert "score" in results[0]
    assert "metadata" in results[0]


@pytest.mark.asyncio
async def test_query_completion(client: AsyncClient):
    """Test generating completions from context"""
    # First ingest a document to use as context
    content = (
        "The benefits of exercise are numerous. Regular physical activity "
        "can improve cardiovascular health, strengthen muscles, enhance mental "
        "wellbeing, and help maintain a healthy weight. Studies show that "
        "even moderate exercise like walking can significantly reduce the risk "
        "of various health conditions."
    )
    await test_ingest_text_document(client, content=content)

    headers = create_auth_header()
    response = await client.post(
        "/query",
        json={
            "query": "What are the main benefits of exercise?",
            "k": 2,
            "temperature": 0.7,
            "max_tokens": 100,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert "completion" in result
    assert "usage" in result
    assert len(result["completion"]) > 0


@pytest.mark.asyncio
async def test_invalid_retrieve_params(client: AsyncClient):
    """Test error handling for invalid retrieve parameters"""
    headers = create_auth_header()

    # Test empty query
    response = await client.post("/retrieve/chunks", json={"query": "", "k": 1}, headers=headers)  # Empty query
    assert response.status_code == 422

    # Test invalid k
    response = await client.post("/retrieve/docs", json={"query": "test", "k": -1}, headers=headers)  # Invalid k
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_completion_params(client: AsyncClient):
    """Test error handling for invalid completion parameters"""
    headers = create_auth_header()

    # Test empty query
    response = await client.post(
        "/query",
        json={"query": "", "temperature": 2.0},  # Empty query  # Invalid temperature
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_chunks_default_reranking(client: AsyncClient):
    """Test retrieving chunks with default reranking behavior"""
    # First ingest some test documents
    _ = await test_ingest_text_document(client, "The quick brown fox jumps over the lazy dog. This is a test document.")
    _ = await test_ingest_text_document(
        client, "The lazy dog sleeps while the quick brown fox runs. Another test document."
    )

    headers = create_auth_header()
    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "What does the fox do?",
            "k": 2,
            "min_score": 0.0,
            # Not specifying use_reranking - should use default from config
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    # Verify chunks are ordered by score
    scores = [chunk["score"] for chunk in chunks]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


@pytest.mark.asyncio
async def test_retrieve_chunks_explicit_reranking(client: AsyncClient):
    """Test retrieving chunks with explicitly enabled reranking"""
    # First ingest some test documents
    _ = await test_ingest_text_document(client, "The quick brown fox jumps over the lazy dog. This is a test document.")
    _ = await test_ingest_text_document(
        client, "The lazy dog sleeps while the quick brown fox runs. Another test document."
    )

    headers = create_auth_header()
    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "What does the fox do?",
            "k": 2,
            "min_score": 0.0,
            "use_reranking": True,
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    # Verify chunks are ordered by score
    scores = [chunk["score"] for chunk in chunks]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


@pytest.mark.asyncio
async def test_retrieve_chunks_disabled_reranking(client: AsyncClient):
    """Test retrieving chunks with explicitly disabled reranking"""
    # First ingest some test documents
    await test_ingest_text_document(client, "The quick brown fox jumps over the lazy dog. This is a test document.")
    await test_ingest_text_document(
        client, "The lazy dog sleeps while the quick brown fox runs. Another test document."
    )

    headers = create_auth_header()
    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "What does the fox do?",
            "k": 2,
            "min_score": 0.0,
            "use_reranking": False,
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_reranking_affects_results(client: AsyncClient):
    """Test that reranking actually changes the order of results"""
    # First ingest documents with clearly different semantic relevance
    await test_ingest_text_document(client, "The capital of France is Paris. The city is known for the Eiffel Tower.")
    await test_ingest_text_document(client, "Paris is a city in France. It has many famous landmarks and museums.")
    await test_ingest_text_document(
        client, "Paris Hilton is a celebrity and businesswoman. She has nothing to do with France."
    )

    headers = create_auth_header()

    # Get results without reranking
    response_no_rerank = await client.post(
        "/retrieve/chunks",
        json={
            "query": "Tell me about the capital city of France",
            "k": 3,
            "min_score": 0.0,
            "use_reranking": False,
            "use_colpali": True,
        },
        headers=headers,
    )

    # Get results with reranking
    response_with_rerank = await client.post(
        "/retrieve/chunks",
        json={
            "query": "Tell me about the capital city of France",
            "k": 3,
            "min_score": 0.0,
            "use_reranking": True,
            "use_colpali": True,
        },
        headers=headers,
    )

    assert response_no_rerank.status_code == 200
    assert response_with_rerank.status_code == 200

    chunks_no_rerank = response_no_rerank.json()
    chunks_with_rerank = response_with_rerank.json()

    # Verify we got results in both cases
    assert len(chunks_no_rerank) > 0
    assert len(chunks_with_rerank) > 0

    # The order or scores should be different between reranked and non-reranked results
    # This test might be a bit flaky depending on the exact scoring, but it should work most of the time
    # given our carefully crafted test data
    scores_no_rerank = [c["score"] for c in chunks_no_rerank]
    scores_with_rerank = [c["score"] for c in chunks_with_rerank]
    assert scores_no_rerank != scores_with_rerank, "Reranking should affect the scores"


@pytest.mark.asyncio
async def test_retrieve_docs_with_reranking(client: AsyncClient):
    """Test document retrieval with reranking options"""
    # First ingest documents with clearly different semantic relevance
    await test_ingest_text_document(client, "The capital of France is Paris. The city is known for the Eiffel Tower.")
    await test_ingest_text_document(client, "Paris is a city in France. It has many famous landmarks and museums.")
    await test_ingest_text_document(
        client, "Paris Hilton is a celebrity and businesswoman. She has nothing to do with France."
    )

    headers = create_auth_header()

    # Test with default reranking (from config)
    response_default = await client.post(
        "/retrieve/docs",
        json={
            "query": "Tell me about the capital city of France",
            "k": 3,
            "min_score": 0.0,
        },
        headers=headers,
    )
    assert response_default.status_code == 200
    docs_default = response_default.json()
    assert len(docs_default) > 0

    # Test with explicit reranking enabled
    response_rerank = await client.post(
        "/retrieve/docs",
        json={
            "query": "Tell me about the capital city of France",
            "k": 3,
            "min_score": 0.0,
            "use_reranking": True,
        },
        headers=headers,
    )
    assert response_rerank.status_code == 200
    docs_rerank = response_rerank.json()
    assert len(docs_rerank) > 0

    # Test with reranking disabled
    response_no_rerank = await client.post(
        "/retrieve/docs",
        json={
            "query": "Tell me about the capital city of France",
            "k": 3,
            "min_score": 0.0,
            "use_reranking": False,
        },
        headers=headers,
    )
    assert response_no_rerank.status_code == 200
    docs_no_rerank = response_no_rerank.json()
    assert len(docs_no_rerank) > 0

    # Verify that reranking affects the order
    scores_rerank = [doc["score"] for doc in docs_rerank]
    scores_no_rerank = [doc["score"] for doc in docs_no_rerank]
    assert scores_rerank != scores_no_rerank, "Reranking should affect document scores"


@pytest.mark.asyncio
async def test_query_with_reranking(client: AsyncClient):
    """Test query completion with reranking options"""
    # First ingest documents with clearly different semantic relevance
    await test_ingest_text_document(client, "The capital of France is Paris. The city is known for the Eiffel Tower.")
    await test_ingest_text_document(client, "Paris is a city in France. It has many famous landmarks and museums.")
    await test_ingest_text_document(
        client, "Paris Hilton is a celebrity and businesswoman. She has nothing to do with France."
    )

    headers = create_auth_header()

    # Test with default reranking (from config)
    response_default = await client.post(
        "/query",
        json={
            "query": "What is the capital of France?",
            "k": 3,
            "min_score": 0.0,
            "max_tokens": 50,
        },
        headers=headers,
    )
    assert response_default.status_code == 200
    completion_default = response_default.json()
    assert "completion" in completion_default

    # Test with explicit reranking enabled
    response_rerank = await client.post(
        "/query",
        json={
            "query": "What is the capital of France?",
            "k": 3,
            "min_score": 0.0,
            "max_tokens": 50,
            "use_reranking": True,
        },
        headers=headers,
    )
    assert response_rerank.status_code == 200
    completion_rerank = response_rerank.json()
    assert "completion" in completion_rerank

    # Test with reranking disabled
    response_no_rerank = await client.post(
        "/query",
        json={
            "query": "What is the capital of France?",
            "k": 3,
            "min_score": 0.0,
            "max_tokens": 50,
            "use_reranking": False,
        },
        headers=headers,
    )
    assert response_no_rerank.status_code == 200
    completion_no_rerank = response_no_rerank.json()
    assert "completion" in completion_no_rerank

    # The actual responses might be different due to different chunk ordering,
    # but all should mention Paris as the capital
    assert "Paris" in completion_default["completion"]
    assert "Paris" in completion_rerank["completion"]
    assert "Paris" in completion_no_rerank["completion"]


# Knowledge Graph Tests


@pytest.fixture(scope="function", autouse=True)
async def cleanup_graphs():
    """Clean up graphs before each graph test. Assumes 'graphs' table exists."""
    # Create a fresh connection to the test database
    postgres_uri = settings.POSTGRES_URI
    if not postgres_uri:
        logger.warning("POSTGRES_URI not set, skipping graph cleanup")
        yield
        return

    engine = create_async_engine(postgres_uri)
    try:
        async with engine.begin() as conn:
            # First check if the graphs table exists in the public schema
            result = await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'graphs' AND table_schema = 'public'
                    );
                    """
                )
            )
            table_exists = result.scalar()

            if table_exists:
                # If table exists, delete all rows from it
                await conn.execute(text("DELETE FROM public.graphs"))
            else:
                # If table does not exist, this is a setup issue. Tests requiring it will fail.
                # Log a critical error. Graph-related tests will likely fail.
                # This fixture should not be responsible for creating schema.
                logger.warning(
                    "The 'public.graphs' table does not exist in test database. "
                    "Graph-related tests will likely fail."
                )
    except OperationalError as oe:  # Catch specific SQLAlchemy/DB driver operational errors
        logger.error(
            f"Operational error during graph cleanup/check: {oe}. "
            "This might indicate a connection or DB setup issue (e.g., permissions, DB down)."
        )
        # Just log error but don't fail test, as we're working with external server
        pass
    except Exception as e:
        logger.error(f"Unexpected error during graph cleanup: {e}")
        # Just log error but don't fail test, as we're working with external server
        pass
    finally:
        await engine.dispose()

    # This will run before each test function
    yield
    # Test runs here


@pytest.mark.asyncio
async def test_create_graph(client: AsyncClient):
    """Test creating a knowledge graph from documents."""
    # First ingest multiple documents with related content to extract entities and relationships
    doc_id1 = await test_ingest_text_document(
        client,
        content="Apple Inc. is a technology company headquartered in Cupertino, California. "
        "Tim Cook is the CEO of Apple. Steve Jobs was the co-founder of Apple.",
    )

    doc_id2 = await test_ingest_text_document(
        client,
        content="Microsoft is a technology company based in Redmond, Washington. "
        "Satya Nadella is the CEO of Microsoft. Bill Gates co-founded Microsoft.",
    )

    doc_id3 = await test_ingest_text_document(
        client,
        content="Tim Cook succeeded Steve Jobs as the CEO of Apple in 2011. "
        "Under Tim Cook's leadership, Apple became the world's first trillion-dollar company.",
    )

    headers = create_auth_header()
    graph_name = "test_tech_companies_graph"

    # Create graph using the document IDs
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "documents": [doc_id1, doc_id2, doc_id3]},
        headers=headers,
    )

    assert response.status_code == 200
    # Wait for background processing to finish
    await _wait_graph_completion(client, graph_name, headers)

    graph_resp = await client.get(f"/graph/{graph_name}", headers=headers)
    graph = graph_resp.json()

    # Verify graph structure
    assert graph["name"] == graph_name
    assert len(graph["document_ids"]) == 3
    assert all(doc_id in graph["document_ids"] for doc_id in [doc_id1, doc_id2, doc_id3])
    assert len(graph["entities"]) > 0  # Should extract entities like Apple, Microsoft, Tim Cook, etc.
    assert len(graph["relationships"]) > 0  # Should extract relationships like "Tim Cook is CEO of Apple"

    # Verify specific expected entities were extracted
    entity_labels = [entity["label"] for entity in graph["entities"]]
    assert any("Apple" in label for label in entity_labels)
    assert any("Microsoft" in label for label in entity_labels)
    assert any("Tim Cook" in label for label in entity_labels)

    # Verify entity types
    entity_types = set(entity["type"] for entity in graph["entities"])
    assert "ORGANIZATION" in entity_types or "COMPANY" in entity_types
    assert "PERSON" in entity_types

    # Verify entities have document references
    for entity in graph["entities"]:
        assert len(entity["document_ids"]) > 0
        assert entity["document_ids"][0] in [doc_id1, doc_id2, doc_id3]

    return graph_name, [doc_id1, doc_id2, doc_id3]


@pytest.mark.asyncio
async def test_get_graph(client: AsyncClient):
    """Test retrieving a knowledge graph by name."""
    # First create a graph
    graph_name, _ = await test_create_graph(client)

    # Then retrieve it
    headers = create_auth_header()
    response = await client.get(
        f"/graph/{graph_name}",
        headers=headers,
    )

    assert response.status_code == 200
    graph = response.json()

    # Verify correct graph was retrieved
    assert graph["name"] == graph_name
    assert len(graph["entities"]) > 0
    assert len(graph["relationships"]) > 0


@pytest.mark.asyncio
async def test_list_graphs(client: AsyncClient):
    """Test listing all accessible graphs."""
    # First create a graph
    graph_name, _ = await test_create_graph(client)

    # List all graphs
    headers = create_auth_header()
    response = await client.get(
        "/graphs",
        headers=headers,
    )

    assert response.status_code == 200
    graphs = response.json()

    # Verify the created graph is in the list
    assert len(graphs) > 0
    assert any(graph["name"] == graph_name for graph in graphs)


@pytest.mark.asyncio
async def test_create_graph_with_filters(client: AsyncClient):
    """Test creating a knowledge graph using metadata filters."""
    # Ingest test documents with specific metadata
    doc_id1 = await test_ingest_text_document_with_metadata(
        client,
        content="The solar system consists of the Sun and eight planets. "
        "Earth is the third planet from the Sun. Mars is the fourth planet.",
        metadata={"category": "astronomy", "subject": "planets"},
    )

    headers = create_auth_header()

    # Get the document to add specific metadata
    response = await client.get(f"/documents/{doc_id1}", headers=headers)
    assert response.status_code == 200

    # Create graph with filters - using metadata field which is renamed to doc_metadata in PostgresDatabase
    graph_name = "test_astronomy_graph"
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "filters": {"category": "astronomy"}},
        headers=headers,
    )

    assert response.status_code == 200
    graph = response.json()

    # Verify graph was created with the right document
    assert graph["name"] == graph_name
    assert doc_id1 in graph["document_ids"]
    assert len(graph["entities"]) > 0  # Should extract entities like Sun, Earth, Mars

    # Verify specific entities
    entity_labels = [entity["label"] for entity in graph["entities"]]
    assert any(label == "Sun" or "Sun" in label for label in entity_labels)
    assert any(label == "Earth" or "Earth" in label for label in entity_labels)

    return graph_name, doc_id1


@pytest.mark.asyncio
async def test_query_with_graph(client: AsyncClient):
    """Test query completion with knowledge graph enhancement."""
    # First create a graph and get its name
    graph_name, doc_ids = await test_create_graph(client)

    # Additional document that won't be in the graph but contains related information
    _ = await test_ingest_text_document(
        client,
        content="Apple has released a new iPhone model. The company's focus on innovation continues.",
    )

    headers = create_auth_header()

    # Query using the graph
    response = await client.post(
        "/query",
        json={
            "query": "Who is the CEO of Apple?",
            "graph_name": graph_name,
            "hop_depth": 2,
            "include_paths": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion contains relevant information from graph
    assert "completion" in result
    assert any(term in result["completion"] for term in ["Tim Cook", "Cook", "CEO", "Apple"])

    # Verify we have graph metadata when include_paths=True
    assert "metadata" in result, "Expected metadata in response when include_paths=True"
    assert "graph" in result["metadata"], "Expected graph metadata in response"
    assert result["metadata"]["graph"]["name"] == graph_name

    # Verify relevant entities includes expected entities
    assert "relevant_entities" in result["metadata"]["graph"]
    relevant_entities = result["metadata"]["graph"]["relevant_entities"]

    # At least one relevant entity should contain either Tim Cook or Apple
    has_tim_cook = any("Tim Cook" in entity or "Cook" in entity for entity in relevant_entities)
    has_apple = any("Apple" in entity for entity in relevant_entities)
    assert has_tim_cook or has_apple, "Expected relevant entities to include Tim Cook or Apple"

    # Now try without the graph for comparison
    response_no_graph = await client.post(
        "/query",
        json={
            "query": "Who is the CEO of Apple?",
        },
        headers=headers,
    )

    assert response_no_graph.status_code == 200


@pytest.mark.asyncio
async def test_graph_with_folder_and_user_scope(client: AsyncClient):
    """Test knowledge graph with folder and user scoping."""
    headers = create_auth_header()

    # Test folder
    folder_name = "test_graph_folder"

    # Test user
    user_id = "graph_test_user@example.com"

    # Ingest documents into folder with user scope using our helper function
    doc_id1 = await test_ingest_text_document_folder_user(
        client,
        content="Tesla is an electric vehicle manufacturer. Elon Musk is the CEO of Tesla.",
        metadata={"graph_scope_test": True},
        folder_name=folder_name,
        end_user_id=user_id,
    )

    doc_id2 = await test_ingest_text_document_folder_user(
        client,
        content="SpaceX develops spacecraft and rockets. Elon Musk is also the CEO of SpaceX.",
        metadata={"graph_scope_test": True},
        folder_name=folder_name,
        end_user_id=user_id,
    )

    # Also ingest a document outside the folder/user scope
    _ = await test_ingest_text_document_with_metadata(
        client,
        content="Elon Musk also founded Neuralink, a neurotechnology company.",
        metadata={"graph_scope_test": True},
    )

    # Create a graph with folder and user scope
    graph_name = "test_scoped_graph"
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "folder_name": folder_name, "end_user_id": user_id},
        headers=headers,
    )

    assert response.status_code == 200
    graph = response.json()

    # Verify graph was created with proper scoping
    assert graph["name"] == graph_name
    assert len(graph["document_ids"]) == 2
    assert all(doc_id in graph["document_ids"] for doc_id in [doc_id1, doc_id2])

    # Verify we have the expected entities
    entity_labels = [entity["label"].lower() for entity in graph["entities"]]
    assert any("tesla" in label for label in entity_labels)
    assert any("spacex" in label for label in entity_labels)
    assert any("elon musk" in label for label in entity_labels)

    # First, let's check the retrieved chunks directly to verify scope is working
    retrieve_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "What companies does Elon Musk lead?",
            "folder_name": folder_name,
            "end_user_id": user_id,
        },
        headers=headers,
    )

    assert retrieve_response.status_code == 200
    retrieved_chunks = retrieve_response.json()

    # Verify that none of the retrieved chunks contain "Neuralink"
    for chunk in retrieved_chunks:
        assert "neuralink" not in chunk["content"].lower()

    # First try querying without a graph to see if RAG works with just folder/user scope
    response_no_graph = await client.post(
        "/query",
        json={
            "query": "What companies does Elon Musk lead?",
            "folder_name": folder_name,
            "end_user_id": user_id,
        },
        headers=headers,
    )

    assert response_no_graph.status_code == 200
    result_no_graph = response_no_graph.json()

    # Verify the completion has the expected content
    completion_no_graph = result_no_graph["completion"].lower()
    print("Completion without graph:")
    print(completion_no_graph)
    assert "tesla" in completion_no_graph
    assert "spacex" in completion_no_graph
    assert "neuralink" not in completion_no_graph

    # Now test querying with graph and folder/user scope
    response = await client.post(
        "/query",
        json={
            "query": "What companies does Elon Musk lead?",
            "graph_name": graph_name,
            "folder_name": folder_name,
            "end_user_id": user_id,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Log source chunks and graph information used for completion
    print("\nSource chunks for graph-based completion:")
    for source in result["sources"]:
        print(f"Document ID: {source['document_id']}, Chunk: {source['chunk_number']}")

    # Check if there's graph metadata in the response
    if result.get("metadata") and "graph" in result.get("metadata", {}):
        print("\nGraph metadata used:")
        print(result["metadata"]["graph"])

    # Verify the completion has the expected content
    completion = result["completion"].lower()
    print("\nCompletion with graph:")
    print(completion)
    assert "tesla" in completion
    assert "spacex" in completion

    # Verify Neuralink isn't included (it was outside folder/user scope)
    assert "neuralink" not in completion

    # Test updating the graph with folder and user scope
    doc_id3 = await test_ingest_text_document_folder_user(
        client,
        content="The Boring Company was founded by Elon Musk in 2016.",
        metadata={"graph_scope_test": True},
        folder_name=folder_name,
        end_user_id=user_id,
    )

    # Update the graph
    update_response = await client.post(
        f"/graph/{graph_name}/update",
        json={
            "additional_documents": [doc_id3],
            "folder_name": folder_name,
            "end_user_id": user_id,
        },
        headers=headers,
    )

    assert update_response.status_code == 200
    updated_graph = update_response.json()

    # Verify graph was updated
    assert updated_graph["name"] == graph_name
    assert len(updated_graph["document_ids"]) == 3
    assert all(doc_id in updated_graph["document_ids"] for doc_id in [doc_id1, doc_id2, doc_id3])

    # Verify new entity was added
    updated_entity_labels = [entity["label"].lower() for entity in updated_graph["entities"]]
    assert any("boring company" in label for label in updated_entity_labels)

    # Test querying with updated graph
    response = await client.post(
        "/query",
        json={
            "query": "List all companies founded or led by Elon Musk",
            "graph_name": graph_name,
            "folder_name": folder_name,
            "end_user_id": user_id,
        },
        headers=headers,
    )

    assert response.status_code == 200
    updated_result = response.json()

    # Verify the completion includes the new company
    updated_completion = updated_result["completion"].lower()
    assert "tesla" in updated_completion
    assert "spacex" in updated_completion
    assert "boring company" in updated_completion


@pytest.mark.asyncio
async def test_batch_ingest_with_shared_metadata(client: AsyncClient):
    """Test batch ingestion with shared metadata for all files."""
    headers = create_auth_header()
    # Create test files
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    # Shared metadata for all files
    metadata = {"category": "test", "batch": "shared"}

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps(metadata),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 2
    assert len(result["errors"]) == 0

    # Verify all documents got the same metadata
    for doc in result["documents"]:
        assert doc["metadata"]["category"] == "test"
        assert doc["metadata"]["batch"] == "shared"


@pytest.mark.asyncio
async def test_batch_ingest_with_individual_metadata(client: AsyncClient):
    """Test batch ingestion with individual metadata per file."""
    headers = create_auth_header()
    # Create test files
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    # Individual metadata
    metadata = [
        {"category": "test1", "batch": "individual"},
        {"category": "test2", "batch": "individual"},
    ]

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps(metadata),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 2
    assert len(result["errors"]) == 0

    # Verify each document got its correct metadata
    assert result["documents"][0]["metadata"]["category"] == "test1"
    assert result["documents"][1]["metadata"]["category"] == "test2"


@pytest.mark.asyncio
async def test_batch_ingest_metadata_validation(client: AsyncClient):
    """Test validation when metadata list length doesn't match files."""
    headers = create_auth_header()
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    # Metadata list with wrong length
    metadata = [
        {"category": "test1"},
        {"category": "test2"},
        {"category": "test3"},  # Extra metadata
    ]

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps(metadata),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert "must match number of files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_batch_ingest_sequential(client: AsyncClient):
    """Test sequential batch ingestion."""
    headers = create_auth_header()
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    metadata = {"category": "test"}

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps(metadata),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "false",  # Process sequentially
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 2
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_batch_ingest_with_rules(client: AsyncClient):
    """Test batch ingestion with rules applied."""
    headers = create_auth_header()
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    # Test shared rules for all files
    shared_rules = [{"type": "natural_language", "prompt": "Extract keywords"}]

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": json.dumps(shared_rules),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 2
    assert len(result["errors"]) == 0

    # Test per-file rules
    per_file_rules = [
        [{"type": "natural_language", "prompt": "Extract keywords"}],  # Rules for first file
        [{"type": "metadata_extraction", "schema": {"title": "string"}}],  # Rules for second file
    ]

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": json.dumps(per_file_rules),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 2
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_batch_ingest_rules_validation(client: AsyncClient):
    """Test validation of rules format and length."""
    headers = create_auth_header()
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
    ]

    # Test invalid rules format
    invalid_rules = "not a list"

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": invalid_rules,
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]

    # Test per-file rules with wrong length
    per_file_rules = [
        [{"type": "natural_language", "prompt": "Extract keywords"}],  # Only one set of rules
    ]

    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": json.dumps(per_file_rules),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert "must match number of files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_batch_ingest_sequential_vs_parallel(client: AsyncClient):
    """Test both sequential and parallel batch ingestion."""
    headers = create_auth_header()
    files = [
        ("files", ("test1.txt", b"Test content 1")),
        ("files", ("test2.txt", b"Test content 2")),
        ("files", ("test3.txt", b"Test content 3")),
    ]

    # Test parallel processing
    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "true",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 3
    assert len(result["errors"]) == 0

    # Test sequential processing
    response = await client.post(
        "/ingest/files",
        files=files,
        data={
            "metadata": json.dumps({}),
            "rules": json.dumps([]),
            "use_colpali": "true",
            "parallel": "false",
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["documents"]) == 3
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_folder_scoping(client: AsyncClient):
    """Test document operations with folder scoping."""
    headers = create_auth_header()

    # Test folder 1
    folder1_name = "test_folder_1"
    folder1_content = "This is content in test folder 1."

    # Test folder 2
    folder2_name = "test_folder_2"
    folder2_content = "This is different content in test folder 2."

    # Ingest document into folder 1 using our helper function
    doc1_id = await test_ingest_text_document_folder_user(
        client,
        content=folder1_content,
        metadata={"folder_test": True},
        folder_name=folder1_name,
        end_user_id=None,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc1_id}", headers=headers)
    assert response.status_code == 200
    doc1 = response.json()
    assert doc1["system_metadata"]["folder_name"] == folder1_name

    # Ingest document into folder 2 using our helper function
    doc2_id = await test_ingest_text_document_folder_user(
        client,
        content=folder2_content,
        metadata={"folder_test": True},
        folder_name=folder2_name,
        end_user_id=None,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc2_id}", headers=headers)
    assert response.status_code == 200
    doc2 = response.json()
    assert doc2["system_metadata"]["folder_name"] == folder2_name

    # Verify we can get documents by folder
    response = await client.post(
        "/documents",
        json={"folder_test": True},
        headers=headers,
        params={"folder_name": folder1_name},
    )

    assert response.status_code == 200
    folder1_docs = response.json()
    assert len(folder1_docs) == 1
    assert folder1_docs[0]["external_id"] == doc1_id

    # Verify other folder's document isn't in results
    assert not any(doc["external_id"] == doc2_id for doc in folder1_docs)

    # Test querying with folder scope
    response = await client.post(
        "/query",
        json={"query": "What folder is this content in?", "folder_name": folder1_name},
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert "completion" in result

    # Test folder-specific chunk retrieval
    response = await client.post(
        "/retrieve/chunks",
        json={"query": "folder content", "folder_name": folder2_name},
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    assert folder2_content in chunks[0]["content"]

    # Test document update with folder preservation
    updated_content = "This is updated content in test folder 1."
    response = await client.post(
        f"/documents/{doc1_id}/update_text",
        json={
            "content": updated_content,
            "metadata": {"updated": True},
            "folder_name": folder1_name,  # This should match original folder
        },
        headers=headers,
    )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["system_metadata"]["folder_name"] == folder1_name


@pytest.mark.asyncio
async def test_user_scoping(client: AsyncClient):
    """Test document operations with end-user scoping."""
    headers = create_auth_header()

    # Test user 1
    user1_id = "test_user_1@example.com"
    user1_content = "This is content created by test user 1."

    # Test user 2
    user2_id = "test_user_2@example.com"
    user2_content = "This is different content created by test user 2."

    # Ingest document for user 1 using our helper function
    doc1_id = await test_ingest_text_document_folder_user(
        client,
        content=user1_content,
        metadata={"user_test": True},
        folder_name=None,
        end_user_id=user1_id,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc1_id}", headers=headers)
    assert response.status_code == 200
    doc1 = response.json()
    assert doc1["system_metadata"]["end_user_id"] == user1_id

    # Ingest document for user 2 using our helper function
    doc2_id = await test_ingest_text_document_folder_user(
        client,
        content=user2_content,
        metadata={"user_test": True},
        folder_name=None,
        end_user_id=user2_id,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc2_id}", headers=headers)
    assert response.status_code == 200
    doc2 = response.json()
    assert doc2["system_metadata"]["end_user_id"] == user2_id

    # Verify we can get documents by user
    response = await client.post(
        "/documents", json={"user_test": True}, headers=headers, params={"end_user_id": user1_id}
    )

    assert response.status_code == 200
    user1_docs = response.json()
    assert len(user1_docs) == 1
    assert user1_docs[0]["external_id"] == doc1_id

    # Verify other user's document isn't in results
    assert not any(doc["external_id"] == doc2_id for doc in user1_docs)

    # Test querying with user scope
    response = await client.post(
        "/query",
        json={"query": "What is my content?", "end_user_id": user1_id},
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert "completion" in result

    # Test updating document with user preservation
    updated_content = "This is updated content by test user 1."
    response = await client.post(
        f"/documents/{doc1_id}/update_text",
        json={
            "content": updated_content,
            "metadata": {"updated": True},
            "end_user_id": user1_id,  # Should preserve the user
        },
        headers=headers,
    )

    assert response.status_code == 200
    updated_doc = response.json()
    assert updated_doc["system_metadata"]["end_user_id"] == user1_id


@pytest.mark.asyncio
async def test_combined_folder_and_user_scoping(client: AsyncClient):
    """Test document operations with combined folder and user scoping."""
    headers = create_auth_header()

    # Test folder
    folder_name = "test_combined_folder"

    # Test users
    user1_id = "combined_test_user_1@example.com"
    user2_id = "combined_test_user_2@example.com"

    # Ingest document for user 1 in folder using our new helper function
    user1_content = "This is content by user 1 in the combined test folder."
    doc1_id = await test_ingest_text_document_folder_user(
        client,
        content=user1_content,
        metadata={"combined_test": True},
        folder_name=folder_name,
        end_user_id=user1_id,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc1_id}", headers=headers)
    assert response.status_code == 200
    doc1 = response.json()
    assert doc1["system_metadata"]["folder_name"] == folder_name
    assert doc1["system_metadata"]["end_user_id"] == user1_id

    # Ingest document for user 2 in folder using our new helper function
    user2_content = "This is content by user 2 in the combined test folder."
    doc2_id = await test_ingest_text_document_folder_user(
        client,
        content=user2_content,
        metadata={"combined_test": True},
        folder_name=folder_name,
        end_user_id=user2_id,
    )

    # Get the document to verify
    response = await client.get(f"/documents/{doc2_id}", headers=headers)
    assert response.status_code == 200
    doc2 = response.json()
    assert doc2["system_metadata"]["folder_name"] == folder_name
    assert doc2["system_metadata"]["end_user_id"] == user2_id

    # Get all documents in folder
    response = await client.post(
        "/documents",
        json={"combined_test": True},
        headers=headers,
        params={"folder_name": folder_name},
    )

    assert response.status_code == 200
    folder_docs = response.json()
    assert len(folder_docs) == 2

    # Get user 1's documents in the folder
    response = await client.post(
        "/documents",
        json={"combined_test": True},
        headers=headers,
        params={"folder_name": folder_name, "end_user_id": user1_id},
    )

    assert response.status_code == 200
    user1_folder_docs = response.json()
    assert len(user1_folder_docs) == 1
    assert user1_folder_docs[0]["external_id"] == doc1_id

    # Test querying with combined scope
    response = await client.post(
        "/query",
        json={
            "query": "What is in this folder for this user?",
            "folder_name": folder_name,
            "end_user_id": user2_id,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()
    assert "completion" in result

    # Test retrieving chunks with combined scope
    response = await client.post(
        "/retrieve/chunks",
        json={"query": "combined test folder", "folder_name": folder_name, "end_user_id": user1_id},
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    # Should only have user 1's content
    assert any(user1_content in chunk["content"] for chunk in chunks)
    assert not any(user2_content in chunk["content"] for chunk in chunks)


@pytest.mark.asyncio
async def test_system_metadata_filter_behavior(client: AsyncClient):
    """Test detailed behavior of system_metadata filtering."""
    headers = create_auth_header()

    # Create documents with different system metadata combinations

    # Document with folder only
    folder_only_content = "This document has only folder in system metadata."
    folder_only_id = await test_ingest_text_document_folder_user(
        client,
        content=folder_only_content,
        metadata={"filter_test": True},
        folder_name="test_filter_folder",
        end_user_id=None,  # Only folder, no user
    )

    # Get the document to verify
    response = await client.get(f"/documents/{folder_only_id}", headers=headers)
    assert response.status_code == 200

    # Document with user only
    user_only_content = "This document has only user in system metadata."
    user_only_id = await test_ingest_text_document_folder_user(
        client,
        content=user_only_content,
        metadata={"filter_test": True},
        folder_name=None,  # No folder, only user
        end_user_id="test_filter_user@example.com",
    )

    # Get the document to verify
    response = await client.get(f"/documents/{user_only_id}", headers=headers)
    assert response.status_code == 200

    # Document with both folder and user
    combined_content = "This document has both folder and user in system metadata."
    combined_id = await test_ingest_text_document_folder_user(
        client,
        content=combined_content,
        metadata={"filter_test": True},
        folder_name="test_filter_folder",
        end_user_id="test_filter_user@example.com",
    )

    # Get the document to verify
    response = await client.get(f"/documents/{combined_id}", headers=headers)
    assert response.status_code == 200

    # Test queries with different filter combinations

    # Filter by folder only
    response = await client.post(
        "/documents",
        json={"filter_test": True},
        headers=headers,
        params={"folder_name": "test_filter_folder"},
    )

    assert response.status_code == 200
    folder_filtered_docs = response.json()
    folder_doc_ids = [doc["external_id"] for doc in folder_filtered_docs]
    assert folder_only_id in folder_doc_ids
    assert combined_id in folder_doc_ids
    assert user_only_id not in folder_doc_ids

    # Filter by user only
    response = await client.post(
        "/documents",
        json={"filter_test": True},
        headers=headers,
        params={"end_user_id": "test_filter_user@example.com"},
    )

    assert response.status_code == 200
    user_filtered_docs = response.json()
    user_doc_ids = [doc["external_id"] for doc in user_filtered_docs]
    assert user_only_id in user_doc_ids
    assert combined_id in user_doc_ids
    assert folder_only_id not in user_doc_ids

    # Filter by both folder and user
    response = await client.post(
        "/documents",
        json={"filter_test": True},
        headers=headers,
        params={"folder_name": "test_filter_folder", "end_user_id": "test_filter_user@example.com"},
    )

    assert response.status_code == 200
    combined_filtered_docs = response.json()
    combined_doc_ids = [doc["external_id"] for doc in combined_filtered_docs]
    assert len(combined_filtered_docs) == 1
    assert combined_id in combined_doc_ids
    assert folder_only_id not in combined_doc_ids
    assert user_only_id not in combined_doc_ids

    # Test with chunk retrieval
    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "system metadata",
            "folder_name": "test_filter_folder",
            "end_user_id": "test_filter_user@example.com",
        },
        headers=headers,
    )

    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    # Should only have the combined document content
    assert any(combined_content in chunk["content"] for chunk in chunks)
    assert not any(folder_only_content in chunk["content"] for chunk in chunks)
    assert not any(user_only_content in chunk["content"] for chunk in chunks)


@pytest.mark.asyncio
async def test_delete_document(client: AsyncClient):
    """Test deleting a document and verifying it's gone."""
    # First ingest a document to delete
    content = "This is a test document that will be deleted."
    doc_id = await test_ingest_text_document(client, content=content)

    headers = create_auth_header()

    # Verify document exists
    response = await client.get(f"/documents/{doc_id}", headers=headers)
    assert response.status_code == 200

    # Verify document is searchable
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "test document deleted",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )
    assert search_response.status_code == 200
    chunks = search_response.json()
    assert len(chunks) > 0

    # Delete document
    delete_response = await client.delete(
        f"/documents/{doc_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    result = delete_response.json()
    assert result["status"] == "success"
    assert f"Document {doc_id} deleted successfully" in result["message"]

    # Verify document no longer exists
    response = await client.get(f"/documents/{doc_id}", headers=headers)
    assert response.status_code == 404

    # Verify document is no longer searchable
    search_response = await client.post(
        "/retrieve/chunks",
        json={
            "query": "test document deleted",
            "filters": {"external_id": doc_id},
        },
        headers=headers,
    )
    assert search_response.status_code == 200
    chunks = search_response.json()
    assert len(chunks) == 0  # No chunks should be found


@pytest.mark.asyncio
async def test_delete_document_permission_error(client: AsyncClient):
    """Test permissions handling for document deletion."""
    if get_settings().dev_mode:
        pytest.skip("Auth tests skipped in dev mode")

    # First ingest a document to delete
    content = "This is a test document for testing delete permissions."
    doc_id = await test_ingest_text_document(client, content=content)

    # Try to delete with read-only permission
    headers = create_auth_header(permissions=["read"])

    delete_response = await client.delete(
        f"/documents/{doc_id}",
        headers=headers,
    )
    assert delete_response.status_code == 403

    # Verify document still exists
    headers = create_auth_header()  # Full permissions
    response = await client.get(f"/documents/{doc_id}", headers=headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_nonexistent_document(client: AsyncClient):
    """Test deleting a document that doesn't exist."""
    headers = create_auth_header()

    delete_response = await client.delete(
        "/documents/nonexistent_document_id",
        headers=headers,
    )
    assert delete_response.status_code == 404


@pytest.mark.asyncio
async def test_cross_document_query_with_graph(client: AsyncClient):
    """Test cross-document information retrieval using knowledge graph."""
    # Create a graph with multiple documents containing related information
    doc_id1 = await test_ingest_text_document(
        client, content="Project Alpha was initiated in 2020. Jane Smith is the project lead."
    )

    doc_id2 = await test_ingest_text_document(
        client,
        content="Jane Smith has a PhD in Computer Science from MIT. She has 10 years of experience in AI research.",
    )

    doc_id3 = await test_ingest_text_document(
        client,
        content="Project Alpha aims to develop advanced natural language processing models for medical applications.",
    )

    headers = create_auth_header()
    graph_name = "test_project_graph"

    # Create graph using the document IDs
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "documents": [doc_id1, doc_id2, doc_id3]},
        headers=headers,
    )

    assert response.status_code == 200

    # Query that requires connecting information across documents
    response = await client.post(
        "/query",
        json={
            "query": "What is Jane Smith's background and what project is she leading?",
            "graph_name": graph_name,
            "hop_depth": 2,
            "include_paths": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion combines information from multiple documents
    assert "Jane Smith" in result["completion"]
    assert "PhD" in result["completion"] or "Computer Science" in result["completion"]
    assert "Project Alpha" in result["completion"]

    # Compare with non-graph query
    response_no_graph = await client.post(
        "/query",
        json={
            "query": "What is Jane Smith's background and what project is she leading?",
        },
        headers=headers,
    )

    assert response_no_graph.status_code == 200


@pytest.mark.asyncio
async def test_update_graph(client: AsyncClient):
    """Test updating a knowledge graph with new documents."""
    # Create initial graph with some documents
    doc_id1 = await test_ingest_text_document(
        client,
        content="SpaceX was founded by Elon Musk in 2002. It develops and manufactures spacecraft and rockets.",
    )

    doc_id2 = await test_ingest_text_document(
        client, content="Elon Musk is also the CEO of Tesla, an electric vehicle manufacturer."
    )

    headers = create_auth_header()
    graph_name = "test_update_graph"

    # Create initial graph
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "documents": [doc_id1, doc_id2]},
        headers=headers,
    )

    assert response.status_code == 200
    initial_graph = response.json()

    # Verify initial graph structure
    assert initial_graph["name"] == graph_name
    assert len(initial_graph["document_ids"]) == 2
    assert all(doc_id in initial_graph["document_ids"] for doc_id in [doc_id1, doc_id2])

    # Create some new documents to add to the graph
    doc_id3 = await test_ingest_text_document(
        client,
        content="The Starship is a spacecraft being developed by SpaceX. It's designed for missions to Mars.",
    )

    doc_id4 = await test_ingest_text_document(
        client,
        content="Gwynne Shotwell is the President and COO of SpaceX. She joined the company in 2002.",
    )

    # Update the graph with new documents
    update_response = await client.post(
        f"/graph/{graph_name}/update",
        json={"additional_documents": [doc_id3, doc_id4]},
        headers=headers,
    )

    assert update_response.status_code == 200
    updated_graph = update_response.json()

    # Verify updated graph structure
    assert updated_graph["name"] == graph_name
    assert len(updated_graph["document_ids"]) == 4
    assert all(doc_id in updated_graph["document_ids"] for doc_id in [doc_id1, doc_id2, doc_id3, doc_id4])

    # Verify new entities and relationships were added
    assert len(updated_graph["entities"]) > len(initial_graph["entities"])
    assert len(updated_graph["relationships"]) > len(initial_graph["relationships"])

    # Verify specific new entities were extracted
    entity_labels = [entity["label"].lower() for entity in updated_graph["entities"]]
    assert any("starship" in label for label in entity_labels)
    assert any("gwynne shotwell" in label for label in entity_labels)

    # Test updating with filters
    # Create a document with specific metadata
    doc_id5 = await test_ingest_text_document_with_metadata(
        client,
        content="The Falcon 9 is a reusable rocket developed by SpaceX.",
        metadata={"company": "spacex"},
    )

    # Verify metadata was set correctly
    doc_response = await client.get(f"/documents/{doc_id5}", headers=headers)
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    print(f"\nDEBUG - Document {doc_id5} metadata: {doc_data['metadata']}")

    # Update graph using filters
    print("\nDEBUG - Updating graph with filter: {'company': 'spacex'}")
    filter_update_response = await client.post(
        f"/graph/{graph_name}/update",
        json={"additional_filters": {"company": "spacex"}},
        headers=headers,
    )
    print(f"\nDEBUG - Filter update response status: {filter_update_response.status_code}")

    assert filter_update_response.status_code == 200
    filter_updated_graph = filter_update_response.json()

    assert len(filter_updated_graph["document_ids"]) == 5
    assert doc_id5 in filter_updated_graph["document_ids"]

    # Verify the new entity was added
    new_entity_labels = [entity["label"].lower() for entity in filter_updated_graph["entities"]]
    assert any("falcon 9" in label for label in new_entity_labels)

    # Test updating with both documents and filters
    doc_id6 = await test_ingest_text_document(
        client, content="The Tesla Cybertruck is an electric pickup truck announced in 2019."
    )

    doc_id7 = await test_ingest_text_document_with_metadata(
        client,
        content="Starlink is a satellite internet constellation developed by SpaceX.",
        metadata={"company": "spacex", "type": "satellite"},
    )

    # Update with both specific document and filter
    combined_update_response = await client.post(
        f"/graph/{graph_name}/update",
        json={"additional_documents": [doc_id6], "additional_filters": {"type": "satellite"}},
        headers=headers,
    )

    assert combined_update_response.status_code == 200
    combined_updated_graph = combined_update_response.json()

    # Verify both documents were added
    assert len(combined_updated_graph["document_ids"]) == 7
    assert doc_id6 in combined_updated_graph["document_ids"]
    assert doc_id7 in combined_updated_graph["document_ids"]

    # Verify new entities
    final_entity_labels = [entity["label"].lower() for entity in combined_updated_graph["entities"]]
    assert any("cybertruck" in label for label in final_entity_labels)
    assert any("starlink" in label for label in final_entity_labels)

    # Test querying with the updated graph
    query_response = await client.post(
        "/query",
        json={
            "query": "What things has SpaceX developed, names and types?",
            "graph_name": graph_name,
            "hop_depth": 3,
            "include_paths": True,
        },
        headers=headers,
    )

    assert query_response.status_code == 200
    query_result = query_response.json()

    # Verify the completion includes information from the added documents
    completion = query_result["completion"].lower()
    assert "starship" in completion
    assert "falcon 9" in completion
    assert "starlink" in completion


@pytest.mark.asyncio
async def test_create_graph_with_prompt_overrides(client: AsyncClient):
    """Test creating a knowledge graph with custom prompt overrides."""
    # First ingest multiple documents with related content to extract entities and relationships
    doc_id1 = await test_ingest_text_document(
        client,
        content="Apple Inc. is a technology company headquartered in Cupertino, California. "
        "Tim Cook is the CEO of Apple. Steve Jobs was the co-founder of Apple.",
    )

    doc_id2 = await test_ingest_text_document(
        client,
        content="Microsoft is a technology company based in Redmond, Washington. "
        "Satya Nadella is the CEO of Microsoft. Bill Gates co-founded Microsoft.",
    )

    headers = create_auth_header()
    graph_name = "test_graph_with_prompt_overrides"

    # Create custom prompt overrides
    extraction_override = EntityExtractionPromptOverride(
        prompt_template=(
            "Extract only companies and their CEOs from the following text, "
            "ignore other entities: {content}\n{examples}"
        ),
        examples=[
            {"label": "Example Corp", "type": "ORGANIZATION"},
            {"label": "Jane Smith", "type": "PERSON", "properties": {"role": "CEO"}},
        ],
    )

    resolution_override = EntityResolutionPromptOverride(
        examples=[
            {"canonical": "Apple Inc.", "variants": ["Apple", "Apple Computer"]},
            {"canonical": "Timothy Cook", "variants": ["Tim Cook", "Cook"]},
        ]
    )

    prompt_overrides = GraphPromptOverrides(
        entity_extraction=extraction_override, entity_resolution=resolution_override
    )

    # Create graph using the document IDs and custom prompt overrides
    response = await client.post(
        "/graph/create",
        json={
            "name": graph_name,
            "documents": [doc_id1, doc_id2],
            "prompt_overrides": json.loads(prompt_overrides.model_dump_json()),
        },
        headers=headers,
    )

    assert response.status_code == 200
    graph = response.json()

    # Verify graph structure
    assert graph["name"] == graph_name
    assert len(graph["document_ids"]) == 2
    assert all(doc_id in graph["document_ids"] for doc_id in [doc_id1, doc_id2])
    assert len(graph["entities"]) > 0
    assert len(graph["relationships"]) > 0

    # Verify that custom extraction worked (focus should be on companies and CEOs)
    entity_labels = [entity["label"] for entity in graph["entities"]]
    entity_types = [entity["type"] for entity in graph["entities"]]

    # Should capture companies
    assert any("Apple" in label for label in entity_labels)
    assert any("Microsoft" in label for label in entity_labels)

    # Should capture CEOs
    assert any("Tim Cook" in label for label in entity_labels)
    assert any("Satya Nadella" in label for label in entity_labels)

    # Should have ORGANIZATION and PERSON types
    assert "ORGANIZATION" in entity_types or "COMPANY" in entity_types
    assert "PERSON" in entity_types

    return graph_name, [doc_id1, doc_id2]


@pytest.mark.asyncio
async def test_update_graph_with_prompt_overrides(client: AsyncClient):
    """Test updating a knowledge graph with custom prompt overrides."""
    # Create initial graph with some documents
    doc_id1 = await test_ingest_text_document(
        client, content="Tesla is an electric vehicle manufacturer. Elon Musk is the CEO of Tesla."
    )

    doc_id2 = await test_ingest_text_document(
        client,
        content="SpaceX develops spacecraft and rockets. Elon Musk is also the CEO of SpaceX.",
    )

    headers = create_auth_header()
    graph_name = "test_update_graph_with_prompts"

    # Create initial graph with default settings
    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "documents": [doc_id1, doc_id2]},
        headers=headers,
    )

    assert response.status_code == 200

    # Create a new document to add to the graph
    doc_id3 = await test_ingest_text_document(
        client,
        content="The Boring Company was founded by Elon Musk. It focuses on tunnel construction technology.",
    )

    # Create custom prompt overrides for update
    extraction_override = EntityExtractionPromptOverride(
        prompt_template=(
            "Extract specifically company names and their founders " "from the following text: {content}\n{examples}"
        ),
        examples=[
            {"label": "Tech Company", "type": "ORGANIZATION"},
            {"label": "Founder Person", "type": "PERSON", "properties": {"role": "founder"}},
        ],
    )

    prompt_overrides = GraphPromptOverrides(entity_extraction=extraction_override)

    # Update the graph with new document and custom prompts
    update_response = await client.post(
        f"/graph/{graph_name}/update",
        json={
            "additional_documents": [doc_id3],
            "prompt_overrides": json.loads(prompt_overrides.model_dump_json()),
        },
        headers=headers,
    )

    assert update_response.status_code == 200
    updated_graph = update_response.json()

    # Verify updated graph structure
    assert updated_graph["name"] == graph_name
    assert len(updated_graph["document_ids"]) == 3
    assert all(doc_id in updated_graph["document_ids"] for doc_id in [doc_id1, doc_id2, doc_id3])

    # Verify new entity was added
    entity_labels = [entity["label"].lower() for entity in updated_graph["entities"]]
    assert any("boring company" in label for label in entity_labels)

    # Verify relationships include founder relationship (from custom prompt)
    relationship_types = [rel["type"].lower() for rel in updated_graph["relationships"]]
    # Check if any relationship type contains "found" or is exactly "founder"
    founder_relationship = any("found" in rel_type or rel_type == "founder" for rel_type in relationship_types)
    assert founder_relationship, "Expected to find a founder relationship due to custom prompt"

    return graph_name, [doc_id1, doc_id2, doc_id3]


@pytest.mark.asyncio
async def test_query_with_graph_and_prompt_overrides(client: AsyncClient):
    """Test querying with a graph and custom prompt overrides."""
    # First create a graph
    graph_name, doc_ids = await test_create_graph_with_prompt_overrides(client)

    headers = create_auth_header()

    # Create query prompt overrides
    query_prompt_override = {
        "entity_extraction": {
            "prompt_template": (
                "Extract specifically people and organizations from the following " "query: {content}\n{examples}"
            ),
            "examples": [
                {"label": "Apple", "type": "ORGANIZATION"},
                {"label": "CEO", "type": "ROLE"},
            ],
        },
        "entity_resolution": {
            "examples": [{"canonical": "Timothy Cook", "variants": ["Tim Cook", "Apple CEO", "Cook"]}]
        },
    }

    # Query using the graph with prompt overrides
    response = await client.post(
        "/query",
        json={
            "query": "Who is the CEO of Apple?",
            "graph_name": graph_name,
            "hop_depth": 2,
            "include_paths": True,
            "prompt_overrides": query_prompt_override,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion contains relevant information from graph
    assert "completion" in result
    assert any(term in result["completion"] for term in ["Tim Cook", "CEO", "Apple"])

    # Verify we have graph metadata
    assert "metadata" in result
    assert "graph" in result["metadata"]
    assert result["metadata"]["graph"]["name"] == graph_name

    # Get relevant entities to verify entity extraction worked
    assert "relevant_entities" in result["metadata"]["graph"]
    relevant_entities = result["metadata"]["graph"]["relevant_entities"]

    has_tim_cook = any("Tim" in entity or "Cook" in entity for entity in relevant_entities)
    has_apple = any("Apple" in entity for entity in relevant_entities)

    assert has_tim_cook, "Should extract Tim Cook as a relevant entity"
    assert has_apple, "Should extract Apple as a relevant entity"


@pytest.mark.asyncio
async def test_query_with_completion_override(client: AsyncClient):
    """Test querying with a custom completion prompt override."""
    # First ingest a document for testing
    await test_ingest_text_document(
        client,
        content=(
            "Tesla Inc. is an electric vehicle manufacturer founded in 2003. "
            "It produces electric cars, battery energy storage, solar panels, and related products. "
            "Elon Musk is the CEO. Its headquarters are in Austin, Texas. "
            "The company's mission is to accelerate the world's transition to sustainable energy."
        ),
    )

    headers = create_auth_header()

    # Define custom query prompt override
    query_prompt_override = {
        "query": {
            "prompt_template": (
                "Using the provided information, answer the following question in the style of a "
                "technical expert using '*' for bullet points: {question} with context: {context}"
            ),
        }
    }

    # Query with the custom prompt override
    response = await client.post(
        "/query",
        json={
            "query": "Who is the CEO of Apple?",
            "k": 4,
            "prompt_overrides": query_prompt_override,
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion contains relevant information
    assert "completion" in result
    assert any(term in result["completion"] for term in ["Tim Cook", "CEO", "Apple"])

    # Check that the style was applied (bullet points should be present)
    assert "*" in result["completion"]


@pytest.mark.asyncio
async def test_query_with_schema_structured_output(client: AsyncClient):
    """Test querying with schema for structured output."""
    # First ingest a document for testing
    _ = await test_ingest_text_document(
        client,
        content="Morphik is an AI platform built for retrieval-augmented generation. "
        "It was created in 2023 and supports features like ingestion, retrieval, "
        "and completion. The core is implemented using Python with FastAPI, and "
        "includes components for vector storage, embedding, and natural language "
        "processing.",
    )

    headers = create_auth_header()

    # Define a simple Pydantic schema for structured output
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "year_created": {"type": "integer"},
            "features": {"type": "array", "items": {"type": "string"}},
            "technologies": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "year_created", "features"],
    }

    # Query with the schema
    response = await client.post(
        "/query",
        json={
            "query": "What is Morphik, when was it created, and what features does it support?",
            "k": 3,
            "schema": schema,
            "temperature": 0.2,  # Low temperature for more deterministic structured output
            "use_reranking": False,  # Simplify the test
            "max_tokens": 500,  # Set reasonable token limit
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion is returned as structured data
    assert "completion" in result

    # Check the structured completion has the expected structure
    structured_data = result["completion"]
    assert "name" in structured_data
    assert "year_created" in structured_data
    assert "features" in structured_data

    # Verify the content matches the document
    assert structured_data["name"] == "Morphik"
    assert structured_data["year_created"] == 2023
    assert isinstance(structured_data["features"], list)

    # The features array should contain at least some of these items
    expected_features = ["ingestion", "retrieval", "completion"]
    assert any(feature in expected_features for feature in structured_data["features"])


@pytest.mark.asyncio
async def test_query_with_pydantic_model_schema(client: AsyncClient):
    """Test querying with a Pydantic model schema for structured output."""
    # First ingest a document for testing
    _ = await test_ingest_text_document(
        client,
        content="Tesla Inc. is an electric vehicle manufacturer founded in 2003. "
        "It produces electric cars, battery energy storage, solar panels, and related products. "
        "Elon Musk is the CEO. Its headquarters are in Austin, Texas. "
        "The company's mission is to accelerate the world's transition to sustainable energy.",
    )

    headers = create_auth_header()

    # Define the Pydantic model
    class CompanyInfo(pydantic.BaseModel):
        name: str
        founded_year: int
        ceo: str
        headquarters: str
        products: list[str]
        mission: str

    # Get the JSON schema from the Pydantic model
    company_schema = CompanyInfo.model_json_schema()

    # Query with the schema
    response = await client.post(
        "/query",
        json={
            "query": "Extract structured information about Tesla Inc.",
            "k": 3,
            "schema": company_schema,
            "temperature": 0.2,  # Low temperature for more deterministic structured output
            "use_reranking": False,  # Simplify the test
            "max_tokens": 500,  # Set reasonable token limit
        },
        headers=headers,
    )

    assert response.status_code == 200
    result = response.json()

    # Verify the completion is returned as structured data
    assert "completion" in result
    structured_data = result["completion"]

    # Validate the structured data against the Pydantic model (optional but good practice)
    try:
        validated_data = CompanyInfo(**structured_data)
    except pydantic.ValidationError as e:
        pytest.fail(f"Output validation failed: {e}")

    # Verify the content using the validated data
    assert validated_data.name == "Tesla Inc."
    assert validated_data.founded_year == 2003
    assert validated_data.ceo == "Elon Musk"
    assert "Austin" in validated_data.headquarters
    assert isinstance(validated_data.products, list)
    assert "sustainable energy" in validated_data.mission.lower()


@pytest.mark.asyncio
async def test_invalid_prompt_overrides(client: AsyncClient):
    """Test validation of invalid prompt overrides."""
    # Create test document
    doc_id = await test_ingest_text_document(client, content="Test content for invalid prompt overrides.")

    headers = create_auth_header()
    graph_name = "test_invalid_prompts_graph"

    # Test with invalid prompt override structure (invalid field)
    invalid_override = {
        "entity_extraction": {
            "prompt_template": "Valid template: {content}",
            "invalid_field": "This field doesn't exist",
        }
    }

    response = await client.post(
        "/graph/create",
        json={"name": graph_name, "documents": [doc_id], "prompt_overrides": invalid_override},
        headers=headers,
    )

    assert response.status_code in [400, 422]  # Either bad request or validation error

    # Test with invalid query field in graph context (should be rejected)
    invalid_field_override = {"query": {"prompt_template": "This field shouldn't be allowed in graph context"}}

    response = await client.post(
        "/graph/create",
        json={
            "name": graph_name + "_2",
            "documents": [doc_id],
            "prompt_overrides": invalid_field_override,
        },
        headers=headers,
    )

    assert response.status_code in [400, 422]  # Either bad request or validation error


@pytest.mark.asyncio
async def test_prompt_override_placeholder_validation(client: AsyncClient):
    """Test validation of required placeholders in prompt override templates."""
    # Create test document
    doc_id = await test_ingest_text_document(client, content="Test content for prompt placeholder validation.")

    headers = create_auth_header()

    # Test missing {content} placeholder in entity extraction prompt
    missing_content_override = {
        "entity_extraction": {
            "prompt_template": "Invalid template with only {examples} but missing content placeholder",
        }
    }

    response = await client.post(
        "/graph/create",
        json={
            "name": "test_missing_content",
            "documents": [doc_id],
            "prompt_overrides": missing_content_override,
        },
        headers=headers,
    )

    assert response.status_code in [400, 422]
    assert "missing" in response.json()["detail"].lower() and "content" in response.json()["detail"].lower()

    # Test missing {examples} placeholder in entity extraction prompt
    missing_examples_override = {
        "entity_extraction": {
            "prompt_template": "Invalid template with only {content} but missing examples placeholder",
        }
    }

    response = await client.post(
        "/graph/create",
        json={
            "name": "test_missing_examples",
            "documents": [doc_id],
            "prompt_overrides": missing_examples_override,
        },
        headers=headers,
    )

    assert response.status_code in [400, 422]
    assert "missing" in response.json()["detail"].lower() and "examples" in response.json()["detail"].lower()

    # Test missing placeholders in query prompt override
    missing_query_placeholders_override = {
        "query": {
            "prompt_template": "Invalid template with no required placeholders",
        }
    }

    response = await client.post(
        "/query",
        json={
            "query": "Test query",
            "prompt_overrides": missing_query_placeholders_override,
        },
        headers=headers,
    )

    assert response.status_code in [400, 422]
    assert "question" in response.json()["detail"].lower() and "context" in response.json()["detail"].lower()

    # Test valid prompt overrides with all required placeholders
    valid_extraction_override = {
        "entity_extraction": {
            "prompt_template": "Valid template with {content} and {examples} placeholders",
        }
    }

    response = await client.post(
        "/graph/create",
        json={
            "name": "test_valid_placeholders",
            "documents": [doc_id],
            "prompt_overrides": valid_extraction_override,
        },
        headers=headers,
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_multi_folder_list_scoping(client: AsyncClient):
    """Ensure endpoints correctly accept and enforce *multiple* folder names passed as a list."""
    headers = create_auth_header()

    # Create three distinct folders
    folder1_name = "mf_folder1"
    folder2_name = "mf_folder2"
    folder_other = "mf_folder_other"

    # Unique contents
    content_phrase = "multi-folder-unique-phrase"
    content1 = f"Document in {folder1_name} containing {content_phrase}."
    content2 = f"Document in {folder2_name} also containing {content_phrase}."
    other_content = "Document in other folder with different phrase."

    # Ingest documents in the three folders (no end_user scope for simplicity)
    doc1_id = await test_ingest_text_document_folder_user(
        client,
        content=content1,
        metadata={"mf_test": True},
        folder_name=folder1_name,
        end_user_id=None,
    )
    doc2_id = await test_ingest_text_document_folder_user(
        client,
        content=content2,
        metadata={"mf_test": True},
        folder_name=folder2_name,
        end_user_id=None,
    )
    doc_other_id = await test_ingest_text_document_folder_user(
        client,
        content=other_content,
        metadata={"mf_test": True},
        folder_name=folder_other,
        end_user_id=None,
    )

    # Helper: wait until ingestion workers finish so system_metadata is fully committed
    async def _wait_completion(document_id: str, max_tries: int = 10):
        for _ in range(max_tries):
            status_resp = await client.get(f"/documents/{document_id}/status", headers=headers)
            if status_resp.status_code == 200 and status_resp.json().get("status") == "completed":
                return
            await asyncio.sleep(1)

    await _wait_completion(doc1_id)
    await _wait_completion(doc2_id)
    await _wait_completion(doc_other_id)

    # ------------ List documents endpoint (multiple folder_name query params) ------------
    list_docs_url = "/documents"
    response = await client.post(
        list_docs_url, json={"mf_test": True, "folder_name": [folder1_name, folder2_name]}, headers=headers
    )
    assert response.status_code == 200
    docs = response.json()
    returned_ids = {d["external_id"] for d in docs}
    assert doc1_id in returned_ids
    assert doc2_id in returned_ids
    assert doc_other_id not in returned_ids

    # ------------ retrieve/docs with folder list ------------
    response = await client.post(
        "/retrieve/docs",
        json={
            "query": content_phrase,
            "folder_name": [folder1_name, folder2_name],
            "k": 5,
        },
        headers=headers,
    )
    assert response.status_code == 200
    docs_results = response.json()
    assert len(docs_results) > 0
    assert all(r["document_id"] in {doc1_id, doc2_id} for r in docs_results)

    # ------------ retrieve/chunks with folder list ------------
    response = await client.post(
        "/retrieve/chunks",
        json={
            "query": content_phrase,
            "folder_name": [folder1_name, folder2_name],
            "k": 5,
        },
        headers=headers,
    )
    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 0
    assert all(c["document_id"] in {doc1_id, doc2_id} for c in chunks)

    # ------------ batch/documents with folder list ------------
    response = await client.post(
        "/batch/documents",
        json={
            "document_ids": [doc1_id, doc2_id, doc_other_id],
            "folder_name": [folder1_name, folder2_name],
        },
        headers=headers,
    )
    assert response.status_code == 200
    batch_docs = response.json()
    returned_ids = {d["external_id"] for d in batch_docs}
    assert returned_ids == {doc1_id, doc2_id}

    # ------------ batch/chunks with folder list ------------
    sources = [
        {"document_id": doc1_id, "chunk_number": 0},
        {"document_id": doc2_id, "chunk_number": 0},
        {"document_id": doc_other_id, "chunk_number": 0},
    ]
    response = await client.post(
        "/batch/chunks",
        json={
            "sources": sources,
            "folder_name": [folder1_name, folder2_name],
        },
        headers=headers,
    )
    assert response.status_code == 200
    batch_chunks = response.json()
    assert len(batch_chunks) > 0
    assert all(ch["document_id"] in {doc1_id, doc2_id} for ch in batch_chunks)

    # ------------ query endpoint with folder list ------------
    response = await client.post(
        "/query",
        json={
            "query": f"Which folder contains {content_phrase}?",
            "folder_name": [folder1_name, folder2_name],
            "k": 2,
        },
        headers=headers,
    )
    assert response.status_code == 200
    result = response.json()
    # Ensure sources are scoped correctly
    assert "sources" in result and len(result["sources"]) > 0
    assert all(src["document_id"] in {doc1_id, doc2_id} for src in result["sources"])


@pytest.mark.asyncio
async def test_documents_not_in_folder(client: AsyncClient):
    """Test retrieving documents that are not in any folder (folder_name is null)."""
    headers = create_auth_header()

    # Ingest a document without a folder
    no_folder_content = "This document is not in any folder"
    doc_no_folder_id = await test_ingest_text_document(client, content=no_folder_content)

    # Ingest a document with a folder
    folder_name = "test_folder_for_null_check"
    folder_content = "This document is in a folder"
    doc_with_folder_id = await test_ingest_text_document_folder_user(
        client,
        content=folder_content,
        metadata={"test": "value"},
        folder_name=folder_name,
        end_user_id=None,
    )

    # Wait a bit for ingestion to complete
    await asyncio.sleep(2)

    # Test listing documents not in any folder (folder_name=null)
    response = await client.post("/documents", json={}, headers=headers, params={"folder_name": "null"})
    assert response.status_code == 200
    docs = response.json()

    # Check that we get exactly our documents with null folder_name
    found_doc_ids = {doc["external_id"] for doc in docs}

    # The document without folder should be in the results
    assert doc_no_folder_id in found_doc_ids, "Document without folder should be found when filtering by null folder"

    # The document with folder should NOT be in the results
    assert (
        doc_with_folder_id not in found_doc_ids
    ), "Document with folder should NOT be found when filtering by null folder"

    # Verify the returned document has null folder_name
    for doc in docs:
        if doc["external_id"] == doc_no_folder_id:
            assert doc["system_metadata"]["folder_name"] is None


@pytest.mark.asyncio
async def test_documents_in_folder_or_no_folder(client: AsyncClient):
    """Test retrieving documents either in a specific folder OR not in any folder."""
    headers = create_auth_header()

    # Ingest a document without a folder
    no_folder_content = "Document with no folder"
    doc_no_folder_id = await test_ingest_text_document(client, content=no_folder_content)

    # Ingest a document in folder A
    folder_a_name = "folder_a_for_mixed_test"
    folder_a_content = "Document in folder A"
    doc_folder_a_id = await test_ingest_text_document_folder_user(
        client,
        content=folder_a_content,
        metadata={"test": "folder_a"},
        folder_name=folder_a_name,
        end_user_id=None,
    )

    # Ingest a document in folder B
    folder_b_name = "folder_b_for_mixed_test"
    folder_b_content = "Document in folder B"
    doc_folder_b_id = await test_ingest_text_document_folder_user(
        client,
        content=folder_b_content,
        metadata={"test": "folder_b"},
        folder_name=folder_b_name,
        end_user_id=None,
    )

    # Wait a bit for ingestion to complete
    await asyncio.sleep(2)

    # Test listing documents in folder A OR not in any folder
    response = await client.post(
        "/documents", json={}, headers=headers, params={"folder_name": [folder_a_name, "null"]}
    )
    assert response.status_code == 200
    docs = response.json()

    # Track which documents we found
    found_doc_ids = {doc["external_id"] for doc in docs}

    # Should find: doc_no_folder_id and doc_folder_a_id
    # Should NOT find: doc_folder_b_id
    assert doc_no_folder_id in found_doc_ids, "Document without folder should be found"
    assert doc_folder_a_id in found_doc_ids, "Document in folder A should be found"
    assert doc_folder_b_id not in found_doc_ids, "Document in folder B should NOT be found"

    # Verify the folder_name values
    for doc in docs:
        if doc["external_id"] == doc_no_folder_id:
            assert doc["system_metadata"]["folder_name"] is None
        elif doc["external_id"] == doc_folder_a_id:
            assert doc["system_metadata"]["folder_name"] == folder_a_name


# ---------------------------------------------------------------------------
# Utility – wait for background graph builds to complete
# ---------------------------------------------------------------------------


async def _wait_graph_completion(
    client: AsyncClient,
    graph_name: str,
    headers: Dict[str, str],
    folder_name: str | list[str] | None = None,
    end_user_id: str | None = None,
    max_tries: int = 30,
):
    """Poll /graph/{graph_name} until system_metadata.status == 'completed'."""
    params: Dict[str, Any] = {}
    if folder_name is not None:
        params["folder_name"] = folder_name
    if end_user_id is not None:
        params["end_user_id"] = end_user_id

    for _ in range(max_tries):
        resp = await client.get(f"/graph/{graph_name}", headers=headers, params=params)
        if resp.status_code == 200:
            g = resp.json()
            if g.get("system_metadata", {}).get("status") == "completed":
                return g
        await asyncio.sleep(1)
    raise AssertionError(f"Graph {graph_name} did not complete within timeout")


# ---------------------------------------------------------------------------
# New tests – regression for PDF-named text & failed status propagation
# ---------------------------------------------------------------------------


async def _wait_doc_status(
    client: AsyncClient, doc_id: str, headers: Dict[str, str], *, target: str, timeout: int = 30
):
    """Poll /documents/{id}/status until status matches *target* or timeout."""
    import asyncio
    import time

    start = time.time()
    while time.time() - start < timeout:
        resp = await client.get(f"/documents/{doc_id}/status", headers=headers)
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status == target:
                return resp.json()
        await asyncio.sleep(1)
    raise AssertionError(f"Document {doc_id} did not reach status={target} within {timeout}s")


@pytest.mark.asyncio
async def test_ingest_text_named_pdf_success(client: AsyncClient):
    """Plain-text bytes with a .pdf name should still ingest successfully."""

    headers = create_auth_header()

    fake_pdf_bytes = b"This is actually plain text, not a PDF."

    response = await client.post(
        "/ingest/file",
        files={"file": ("fake.pdf", fake_pdf_bytes, "text/plain")},
        data={"metadata": json.dumps({"regression": "pdf_named_text"})},
        headers=headers,
    )

    assert response.status_code == 200
    doc = response.json()

    # Wait until worker completes (should be 'completed')
    status_info = await _wait_doc_status(client, doc["external_id"], headers, target="completed")

    assert status_info["status"] == "completed"


@pytest.mark.asyncio
async def test_ingest_empty_file_sets_failed_status(client: AsyncClient):
    """Uploading an empty file should fail and status should become 'failed'."""

    headers = create_auth_header()

    empty_bytes = b""  # zero-length

    response = await client.post(
        "/ingest/file",
        files={"file": ("empty.txt", empty_bytes, "text/plain")},
        data={"metadata": json.dumps({"regression": "empty_file"})},
        headers=headers,
    )

    assert response.status_code == 200
    doc = response.json()

    # Wait for the worker to mark as failed
    status_info = await _wait_doc_status(client, doc["external_id"], headers, target="failed")

    assert status_info["status"] == "failed"
    assert "error" in status_info and "No content chunks" in status_info["error"]


@pytest.mark.asyncio
async def test_chat_persistence(client: AsyncClient):
    """Ensure chat history is persisted across queries."""
    headers = create_auth_header()
    chat_id = str(uuid.uuid4())

    await test_ingest_text_document(client, content="Chat persistence doc")

    resp1 = await client.post(
        "/query",
        json={"query": "first", "chat_id": chat_id},
        headers=headers,
    )
    assert resp1.status_code == 200

    resp2 = await client.post(
        "/query",
        json={"query": "second", "chat_id": chat_id},
        headers=headers,
    )
    assert resp2.status_code == 200

    hist = await client.get(f"/chat/{chat_id}", headers=headers)
    assert hist.status_code == 200
    history = hist.json()
    assert len(history) >= 4
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
