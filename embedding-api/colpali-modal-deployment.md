# Deploying the Colpali Embedding Model to Modal

This guide provides step-by-step instructions for deploying the Colpali embedding model as a scalable API using [Modal](https://modal.com/).

---

## Prerequisites

- A [Modal](https://modal.com/) account
- Access to the `colpali_modal_app.py` script (typically found in `morphik-external/scripts/colpali_modal_app.py`)
- API keys for HuggingFace and your Colpali service (for authentication)
- Docker (optional, for local testing)

---

## 1. Prepare Environment Variables

You will need the following environment variables/secrets:

- `HUGGINGFACE_TOKEN`: For downloading models from HuggingFace
- `SERVICE_API_KEY`: A strong random key for authenticating requests to your Modal endpoint

Set these up in your Modal dashboard under **Secrets**.

---

## 2. Review and Configure `colpali_modal_app.py`

- Ensure the script is present at `morphik-external/scripts/colpali_modal_app.py`.
- Confirm the model name and processor are correct for your use case.
- The script should reference the environment variables above.

---

## 3. Deploy to Modal

From your project root, run:

```bash
modal deploy morphik-external/scripts/colpali_modal_app.py
```

Modal will build the Docker image, deploy the application, and provide you with a public URL for the `generate_embeddings_endpoint` (e.g., `https://your-username--colpali-embedding-service-prod-colpalimodalservice-generate-embeddings-endpoint.modal.run`).

---

## 4. Configure Morphik to Use the Modal Endpoint

1. **Update `morphik.toml`:**

   In `morphik-core/morphik.toml`, set:
   ```toml
   [morphik]
   enable_colpali = true
   colpali_mode = "api"
   morphik_embedding_api_domain = "PASTE_YOUR_MODAL_ENDPOINT_URL_HERE"
   ```

2. **Update `.env` for Morphik Core:**

   In `morphik-core/.env`, add:
   ```env
   MORPHIK_EMBEDDING_API_KEY="YOUR_STRONG_RANDOM_API_KEY"
   ```
   This should match the `SERVICE_API_KEY` used in Modal.

---

## 5. Test the Deployment

You can test the endpoint directly with curl:

```bash
curl -X POST \
  -H "Authorization: Bearer <SERVICE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"input_type": "text", "inputs": ["Hello world!"]}' \
  https://<modal-app-url>/embeddings
```

You should receive a JSON response with embeddings.

---

## 6. Integration Notes

- The Morphik backend will use the Modal endpoint for all Colpali embedding requests when `colpali_mode = "api"` is set.
- Ensure your Modal endpoint and API key are kept secure.
- Monitor usage and logs in the Modal dashboard for troubleshooting.

---

## References
- [Modal Documentation](https://modal.com/docs)
- [HuggingFace Documentation](https://huggingface.co/docs)
- [Morphik Documentation](../site-documentation/09-api-reference.md) 