import json
import logging
from typing import Any, Dict, List, Optional

import arq  # Added for Redis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from core.auth_utils import verify_token

# Attempt to import global document_service and redis_pool dependency from core.api
# This is a simplification; a more robust solution might use app.state or a dedicated dependency module
from core.dependencies import get_document_service, get_redis_pool
from core.models.auth import AuthContext

# Import DocumentService type for dependency injection hint
from core.services.document_service import DocumentService
from ee.services.connector_service import ConnectorService
from ee.services.connectors.base_connector import ConnectorAuthStatus, ConnectorFile  # Importing specific models

# from starlette.datastructures import URL  # Will be needed for oauth2callback


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ee/connectors",
    tags=["EE - Connectors"],
)


# Dependency to get ConnectorService
async def get_connector_service(auth: AuthContext = Depends(verify_token)) -> ConnectorService:
    # Should be caught by verify_token but as a safeguard
    if not auth.user_id and not auth.entity_id:
        logger.error("AuthContext is missing user_id and entity_id in get_connector_service.")
        raise HTTPException(status_code=401, detail="Invalid authentication context.")
    try:
        return ConnectorService(auth_context=auth)
    except ValueError as e:
        logger.error(f"Failed to initialize ConnectorService: {e}")
        # User-friendly error message
        raise HTTPException(status_code=500, detail="Connector service initialization error.")


# Placeholder for IngestFromConnectorRequest Pydantic model
class IngestFromConnectorRequest(BaseModel):
    file_id: str
    morphik_folder_name: Optional[str] = None
    morphik_end_user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None  # New field for custom metadata
    rules: Optional[List[Dict[str, Any]]] = None  # New field for custom rules


# Endpoints will be added below


@router.get("/{connector_type}/auth_status", response_model=ConnectorAuthStatus)
async def get_auth_status_for_connector(
    connector_type: str, connector_service: ConnectorService = Depends(get_connector_service)
):
    """Checks the current authentication status for the given connector type."""
    try:
        connector = await connector_service.get_connector(connector_type)
        status = await connector.get_auth_status()
        return status
    except ValueError as e:
        # Handle cases where the connector type is unsupported or other init errors
        logger.error(
            f"Value error getting auth status for {connector_type} for user {connector_service.user_identifier}: {e}"
        )
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        # Handle cases where the connector itself has issues connecting (e.g. to external service if checked early)
        logger.error(f"Connection error for {connector_type} for user {connector_service.user_identifier}: {e}")
        raise HTTPException(status_code=503, detail=f"Connector service unavailable: {str(e)}")
    except Exception as e:
        logger.exception(
            f"Unexpected error getting auth status for {connector_type} "
            f"for user {connector_service.user_identifier}: {e}"
        )
        raise HTTPException(status_code=500, detail="An internal server error occurred.")


@router.get("/{connector_type}/auth/initiate_url", response_model=Dict[str, str])
async def get_initiate_auth_url(
    request: Request,
    connector_type: str,
    app_redirect_uri: Optional[str] = None,
    service: ConnectorService = Depends(get_connector_service),
):
    """Return the provider's *authorization_url* for the given connector.

    The method mirrors the logic of the `/auth/initiate` endpoint but sends a
    JSON payload instead of a redirect so that browsers can stay on the same
    origin until they intentionally navigate away.
    """

    try:
        connector = await service.get_connector(connector_type)
        auth_details = await connector.initiate_auth()

        authorization_url = auth_details.get("authorization_url")
        state = auth_details.get("state")

        if not authorization_url or not state:
            logger.error(
                "Connector '%s' did not return authorization URL or state for user '%s'.",
                connector_type,
                service.user_identifier,
            )
            raise HTTPException(status_code=500, detail="Failed to initiate authentication with the provider.")

        # Store state and connector type in session for later validation.
        request.session["oauth_state"] = state
        request.session["connector_type_for_callback"] = connector_type
        if app_redirect_uri:
            request.session["app_redirect_uri"] = app_redirect_uri

        # Store AuthContext for the callback as a JSON string
        auth_context_json_str = service.auth_context.model_dump_json()  # Use .model_dump_json()
        request.session["oauth_auth_context_json"] = auth_context_json_str  # Store as JSON string

        logger.info("Prepared auth URL for '%s' for user '%s'.", connector_type, service.user_identifier)

        return {"authorization_url": authorization_url}

    except ValueError as ve:
        logger.warning("Auth URL preparation for '%s' failed: %s", connector_type, ve)
        if "Unsupported connector type" in str(ve):
            raise HTTPException(status_code=404, detail=str(ve))
        raise HTTPException(status_code=500, detail=str(ve))
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=f"Connector '{connector_type}' not fully implemented.")
    except Exception as exc:
        logger.exception("Error preparing auth URL for '%s': %s", connector_type, exc)
        raise HTTPException(status_code=500, detail="Internal server error preparing authentication URL.")


@router.get("/{connector_type}/oauth2callback")
async def connector_oauth_callback(
    request: Request,  # For accessing session and query parameters
    connector_type: str,  # From path, to verify against session
    code: Optional[str] = None,  # OAuth code from query parameters
    state: Optional[str] = None,  # State from query parameters
    error: Optional[str] = None,  # Optional error from OAuth provider
    error_description: Optional[str] = None,  # Optional error description
):
    """
    Handles the OAuth 2.0 callback from the authentication provider.
    Validates state, finalizes authentication, and stores credentials.
    """
    logger.info(
        f"Received OAuth callback for '{connector_type}'. Code: {'SET' if code else 'NOT_SET'}, "
        f"State: {'SET' if state else 'NOT_SET'}, Error: {error}"
    )

    if error:
        logger.error(f"OAuth provider returned error for '{connector_type}': {error} - {error_description}")
        raise HTTPException(status_code=400, detail=f"OAuth provider error: {error_description or error}")

    # --- Session Data Retrieval and Validation ---
    stored_state = request.session.pop("oauth_state", None)
    stored_connector_type = request.session.pop("connector_type_for_callback", None)
    auth_context_json_str = request.session.pop("oauth_auth_context_json", None)

    if not stored_state or not state or stored_state != state:
        logger.error(
            f"OAuth state mismatch for '{connector_type}'. Expected: '{stored_state}', "
            f"Received: '{state}'. IP: {request.client.host if request.client else 'unknown'}"
        )
        raise HTTPException(status_code=400, detail="Invalid OAuth state. Authentication failed.")

    if not stored_connector_type or stored_connector_type != connector_type:
        logger.error(
            f"Connector type mismatch in OAuth callback. Expected: '{stored_connector_type}', Path: '{connector_type}'."
        )
        raise HTTPException(status_code=400, detail="Connector type mismatch during OAuth callback.")

    if not auth_context_json_str:
        logger.error(f"AuthContext not found in session during OAuth callback for '{connector_type}'.")
        raise HTTPException(status_code=400, detail="Authentication context missing. Please restart the auth flow.")

    # --- Service and Connector Initialization ---
    try:
        auth_context = AuthContext(**json.loads(auth_context_json_str))
        service = ConnectorService(auth_context=auth_context)
        # connector variable will be defined by calling service.get_connector
        # but we need to ensure it's done within a try block that can handle connector-specific errors.
    except Exception as e:  # Covers AuthContext reconstruction and ConnectorService instantiation
        logger.error(f"Failed to reconstruct AuthContext or instantiate ConnectorService: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error during authentication setup.")

    # --- Code Validation (can now use service.user_identifier if needed in logs) ---
    if not code:
        user_id_for_log = service.user_identifier if "service" in locals() else "unknown user"
        logger.error(
            f"Authorization code not found in OAuth callback for '{connector_type}' for user '{user_id_for_log}'."
        )
        raise HTTPException(status_code=400, detail="Authorization code missing from provider callback.")

    # Reconstruct the full authorization response URL that the provider redirected to.
    authorization_response_url = str(request.url)
    logger.debug(f"Full authorization_response_url for '{connector_type}': {authorization_response_url}")

    try:
        # Now get the connector, as service is initialized
        connector = await service.get_connector(connector_type)

        auth_data = {
            "authorization_response_url": authorization_response_url,
            "state": state,
        }

        success = await connector.finalize_auth(auth_data)  # Correctly call on connector

        if success:
            logger.info(
                f"Successfully finalized authentication for '{connector_type}' for user '{service.user_identifier}'."
            )
            app_redirect_uri = request.session.pop("app_redirect_uri", None)
            if app_redirect_uri:
                logger.info(f"Redirecting to frontend app_redirect_uri: {app_redirect_uri}")
                return RedirectResponse(url=app_redirect_uri)
            else:
                logger.info("No app_redirect_uri found, showing generic success page.")
                html_content = """
                <html><head><title>Authentication Successful</title></head>
                <body><h1>Authentication Successful</h1>
                <p>You have successfully authenticated. You can now close this window and return to the application.</p>
                </body></html>
                """
                return HTMLResponse(content=html_content)
        else:
            logger.error(
                f"Failed to finalize auth for '{connector_type}' with user '{service.user_identifier}' "
                f"(connector returned False)."
            )
            raise HTTPException(status_code=500, detail="Failed to finalize authentication with the provider.")

    except ValueError as ve:
        logger.error(f"Error during OAuth callback for '{connector_type}' for user '{service.user_identifier}': {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except NotImplementedError:
        logger.error(f"Connector '{connector_type}' is not fully implemented for auth finalization.")
        raise HTTPException(status_code=501, detail=f"Connector '{connector_type}' not fully implemented.")
    except Exception as e:
        user_id_for_log = service.user_identifier if "service" in locals() else "unknown user"
        logger.exception(
            f"Unexpected error during OAuth callback for '{connector_type}' for user '{user_id_for_log}': {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error during authentication callback.")


# Response model for list_files
class FileListResponse(BaseModel):
    files: List[ConnectorFile]
    next_page_token: Optional[str] = None


@router.get("/{connector_type}/files", response_model=FileListResponse)
async def list_files_for_connector(
    connector_type: str,
    path: Optional[str] = None,  # Connector-specific path (e.g., folder_id)
    page_token: Optional[str] = None,
    q_filter: Optional[str] = None,  # Connector-specific search/filter query string
    page_size: int = 100,  # Default page size, can be overridden by query param
    service: ConnectorService = Depends(get_connector_service),
):
    """Lists files and folders from the specified connector."""
    try:
        connector = await service.get_connector(connector_type)
        # Pass all relevant parameters to the connector's list_files method
        # The connector itself will decide how to use them (e.g. in **kwargs or named params)
        file_listing = await connector.list_files(
            path=path,
            page_token=page_token,
            q_filter=q_filter,  # Pass the filter query
            page_size=page_size,  # Pass the page size
        )
        # Ensure the response from the connector matches the FileListResponse model.
        # The connector.list_files method should return a dict like:
        # {"files": [ConnectorFile, ...], "next_page_token": "..."}
        return file_listing
    except ValueError as ve:  # Raised by get_connector or if connector has issues
        logger.error(f"Error listing files for '{connector_type}' for user '{service.user_identifier}': {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except ConnectionError as ce:  # If connector.list_files raises connection issues
        logger.error(
            f"Connection error listing files for '{connector_type}' for user '{service.user_identifier}': {ce}"
        )
        raise HTTPException(status_code=503, detail=f"Connector service unavailable: {str(ce)}")
    except NotImplementedError:
        logger.error(f"Connector '{connector_type}' does not support listing files or is not fully implemented.")
        raise HTTPException(status_code=501, detail=f"File listing not implemented for connector '{connector_type}'.")
    except Exception as e:
        logger.exception(
            f"Unexpected error listing files for '{connector_type}' for user '{service.user_identifier}': {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error listing files.")


@router.post("/{connector_type}/ingest", response_model=Dict[str, Any])
async def ingest_file_from_connector(
    connector_type: str,
    ingest_request: IngestFromConnectorRequest,
    auth_context: AuthContext = Depends(verify_token),  # For DocumentService & connector
    connector_service: ConnectorService = Depends(get_connector_service),
    doc_service: DocumentService = Depends(get_document_service),
    redis_pool_instance: arq.ArqRedis = Depends(get_redis_pool),  # Retained as per original router structure
):
    """Downloads a file from the connector and ingests it into Morphik via DocumentService."""
    logger.info(
        f"Ingesting file_id: {ingest_request.file_id} from connector: {connector_type} "
        f"for user: {auth_context.user_id or auth_context.entity_id}"
    )
    try:
        connector = await connector_service.get_connector(connector_type)

        # 1. Get file metadata from connector
        file_metadata = await connector.get_file_metadata_by_id(ingest_request.file_id)
        if not file_metadata:
            logger.error(f"File not found via connector: {ingest_request.file_id}")
            raise HTTPException(status_code=404, detail="File not found via connector.")

        # 2. Download file content from connector
        file_content_stream = await connector.download_file_by_id(ingest_request.file_id)
        if not file_content_stream:
            logger.error(f"Failed to download file from connector: {ingest_request.file_id}")
            raise HTTPException(status_code=500, detail="Failed to download file from connector.")

        file_content_bytes = file_content_stream.getvalue()  # Assuming BytesIO

        # ----------------------------------------------------------
        # Detect actual MIME type from file bytes (fallback to API)
        # and fix filename extension when missing.
        # ----------------------------------------------------------
        import filetype as _ft

        detected_kind = _ft.guess(file_content_bytes)
        if detected_kind:
            # Use detected mime/extension when available
            actual_mime_type = detected_kind.mime
            actual_extension = detected_kind.extension
        else:
            # Fall back to connector-reported mime
            actual_mime_type = file_metadata.mime_type
            # Derive extension from mime if possible
            import mimetypes as _mtypes

            guessed_ext = _mtypes.guess_extension(actual_mime_type or "")
            actual_extension = guessed_ext.lstrip(".") if guessed_ext else None

        # Ensure filename has an extension so downstream parsers work
        filename_to_use = file_metadata.name
        if actual_extension and "." not in filename_to_use:
            filename_to_use = f"{filename_to_use}.{actual_extension}"

        # Clean metadata – keep only connector-specific fields that may be
        # useful for the user but drop UI/boolean helpers.
        cleaned_metadata = {}
        if file_metadata.modified_date:
            cleaned_metadata["modified_date"] = file_metadata.modified_date
        # You can add more whitelisted fields here if needed

        # Merge user-provided metadata with cleaned connector metadata
        final_metadata = cleaned_metadata.copy()
        if ingest_request.metadata:  # User-provided metadata
            final_metadata.update(ingest_request.metadata)

        # 3. Ingest into Morphik using DocumentService
        morphik_doc = await doc_service.ingest_file_content(
            file_content_bytes=file_content_bytes,
            filename=filename_to_use,
            content_type=actual_mime_type,
            metadata=final_metadata,  # Use merged metadata
            auth=auth_context,
            redis=redis_pool_instance,
            folder_name=ingest_request.morphik_folder_name,
            end_user_id=ingest_request.morphik_end_user_id,
            rules=ingest_request.rules,  # Pass user-provided rules
            use_colpali=True,  # As per previous request
        )

        return {
            "message": f"File '{file_metadata.name}' successfully queued for ingestion.",
            "morphik_document_id": morphik_doc.external_id,
            "status_path": f"/documents/{morphik_doc.external_id}/status",
        }

    except HTTPException:  # Re-raise HTTPExceptions directly
        raise
    except ValueError as ve:  # E.g., unsupported connector type
        logger.error(f"Value error during ingestion from {connector_type}: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception(f"Unexpected error ingesting from connector '{connector_type}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during file ingestion.")


@router.post("/{connector_type}/disconnect", response_model=Dict[str, Any])
async def disconnect_from_connector(
    connector_type: str,
    service: ConnectorService = Depends(get_connector_service),
):
    """Disconnects the user from the specified connector by removing stored credentials."""
    user_log_id = service.user_identifier
    logger.info(f"Attempting to disconnect from '{connector_type}' for user '{user_log_id}'.")
    try:
        connector = await service.get_connector(connector_type)
        success = await connector.disconnect()

        if success:
            logger.info(f"Successfully disconnected from '{connector_type}' for user '{user_log_id}'.")
            return {"status": "success", "message": f"Successfully disconnected from {connector_type}."}
        else:
            logger.warning(
                f"Disconnection from '{connector_type}' for user '{user_log_id}' "
                f"indicated failure by connector (returned False)."
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to disconnect from {connector_type}. An issue occurred on the server."
            )

    except ValueError as ve:  # From get_connector
        logger.error(f"ValueError during disconnect from '{connector_type}' for user '{user_log_id}': {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except ConnectionError as ce:  # If connector.disconnect had an issue
        logger.error(f"ConnectionError during disconnect from '{connector_type}' for user '{user_log_id}': {ce}")
        raise HTTPException(status_code=503, detail=f"Connector service error during disconnect: {str(ce)}")
    except Exception as e:
        logger.exception(f"Unexpected error during disconnect from '{connector_type}' for user '{user_log_id}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error during disconnect operation.")
