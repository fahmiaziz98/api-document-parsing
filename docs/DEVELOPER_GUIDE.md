# Developer Quick Reference - Document Parsing API

## Quick Start

### For Local Development

#### 1. Setup Environment
```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# For local testing, set legacy key (temporary)
echo "X_API_KEY=test-key-123" >> .env
```

#### 2. Generate a Test API Key
```bash
# Generate dev environment key
python generated_secret.py --environment dev

# Output example:
# Raw Key: dp_dev_aBcDeFgHiJkLmNoPqRsT...
# Hash: a1b2c3d4e5f6...

# Store the hash in .env
echo "X_API_KEY_HASH=a1b2c3d4e5f6..." >> .env
```

#### 3. Run Locally
```bash
# Start the app (using uvicorn for local development)
uvicorn src.app:web_app --reload --host 0.0.0.0 --port 8000
```

#### 4. Test Endpoints
```bash
# Health check (no auth required)
curl http://localhost:8000/health

# Readiness check (no auth required)
curl http://localhost:8000/ready

# Parse image (with auth)
curl -X POST http://localhost:8000/v1/parse/image \
  -H "X-API-Key: dp_dev_aBcDeFgHiJkLmNoPqRsT..." \
  -F "file=@receipt.jpg"

# Parse PDF (with auth)
curl -X POST http://localhost:8000/v1/parse/pdf \
  -H "X-API-Key: dp_dev_aBcDeFgHiJkLmNoPqRsT..." \
  -F "file=@document.pdf"
```

---

## API Authentication

### Generate Client Keys

```bash
# Production key
python generated_secret.py --environment prod

# Development key
python generated_secret.py --environment dev

# Staging key
python generated_secret.py --environment staging
```

The tool outputs:
- **Raw Key**: Give this to the client (shown only once)
- **Hash**: Store in `X_API_KEY_HASH` environment variable

### Store Hashes in Environment

#### Single Key
```bash
export X_API_KEY_HASH="abc123def456..."
```

#### Multiple Keys
```bash
# Option 1: Comma-separated
export X_API_KEY_HASH="hash1,hash2,hash3"

# Option 2: Newline-separated
export X_API_KEY_HASH="hash1
hash2
hash3"
```

### Use API Key in Requests

```bash
# All endpoints require X-API-Key header
curl -X POST https://api.example.com/v1/parse/pdf \
  -H "X-API-Key: dp_prod_aBcDeFgHiJkLmNoPqRsT..." \
  -F "file=@document.pdf"
```

---

## Structured Logging

### Understanding JSON Logs

All logs output structured JSON:
```json
{
  "timestamp": "2026-06-03T12:30:45.123456Z",
  "level": "INFO",
  "logger": "src.api.v1.parse",
  "message": "PDF parse request",
  "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "filename": "report.pdf",
  "file_size_bytes": 2048000,
  "auth_mode": "hashed"
}
```

### Querying Logs

```bash
# Pretty print JSON logs
cat logs.json | jq '.'

# Filter by log level
cat logs.json | jq 'select(.level == "ERROR")'

# Find all logs for a request
cat logs.json | jq 'select(.request_id == "f47ac10b-58cc-4372-a567-0e02b2c3d479")'

# Get auth failures
cat logs.json | jq 'select(.level == "WARNING" and .auth_mode != null)'

# Timeline of a single request
cat logs.json | jq -r 'select(.request_id == "f47ac10b...") | "\(.timestamp) \(.level) \(.message)"'
```

### Development vs Production Logging

```python
# In development - colored output (no JSON)
from src.utils.logging import setup_logging
setup_logging(json_output=False)

# In production - JSON output (default)
from src.utils.logging import setup_logging
setup_logging(json_output=True)  # Default
```

---

## API Endpoints

### Health & Readiness
```
GET /health           200 OK (no auth required)
GET /ready            200 OK (no auth required)
```

### Image Parsing (Synchronous)
```
POST /v1/parse/image
X-API-Key: {key}

Response: 200 OK with ImageParseResult
```

### PDF Parsing (Asynchronous)
```
POST /v1/parse/pdf
X-API-Key: {key}

Response: 202 ACCEPTED with JobSubmitted
  - job_id: "fc-xxx"
  - message: "Poll GET /v1/jobs/{job_id}/status"
```

### Job Status
```
GET /v1/jobs/{job_id}/status
X-API-Key: {key}

Response: 200 OK with JobStatus
  - status: "submitted" | "processing" | "done" | "error" | "expired"
```

### Job Result
```
GET /v1/jobs/{job_id}/result
X-API-Key: {key}

Response: 200 OK with PdfParseResult (when done)
Response: 202 ACCEPTED (still processing)
Response: 404 Not Found (job expired after 7 days)
```

### Job Download
```
GET /v1/jobs/{job_id}/download
X-API-Key: {key}

Response: 200 OK with JSON attachment
  - Same as /result but with Content-Disposition header
```

---

## Request Tracing

### Request ID Flow

Every request gets a UUID that flows through:

```
HTTP Request
  ↓
[add_request_id middleware] → generates UUID
  ↓
request.state.request_id = "f47ac10b..."
  ↓
Handler logs: extra={"request_id": "f47ac10b..."}
  ↓
Response header: X-Request-ID: f47ac10b...
  ↓
JSON log: "request_id": "f47ac10b..."
```

### Using Request ID

```bash
# Get request ID from response header
REQUEST_ID=$(curl -i http://localhost:8000/health | grep X-Request-ID | cut -d' ' -f2)

# Use it to trace through logs
cat logs.json | jq "select(.request_id == \"$REQUEST_ID\")"
```

---

## Error Handling

### Response Format

All errors follow the same structure:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "start_page must be <= end_page",
    "details": {
      "validation_errors": [...]
    },
    "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  }
}
```

### Common Error Codes

| Code | Status | Meaning |
|------|--------|---------|
| `VALIDATION_ERROR` | 422 | Invalid request data |
| `UNSUPPORTED_FILE` | 422 | Wrong file type |
| `AUTH_FAILED` | 401 | Invalid/missing API key |
| `JOB_NOT_FOUND` | 404 | Job expired or doesn't exist |
| `JOB_EXPIRED` | 404 | Result older than 7 days |
| `PARSING_FAILED` | 500 | Modal worker error |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## File Size Limits

- **PDF**: 100 MB max
- **Image**: 20 MB max

Exceeding limits returns 422 with clear error message.

---

## Debugging

### Check Auth System

```python
# Test key hashing
from src.utils.key_gen import hash_api_key, generate_api_key

raw_key, stored_hash = generate_api_key("dev")
print(f"Raw: {raw_key}")
print(f"Hash: {stored_hash}")

# Verify comparison
verified_hash = hash_api_key(raw_key)
print(f"Verified: {verified_hash}")
assert verified_hash == stored_hash
```

### View Structured Logs

```python
# Test JSON logging
import json
import sys
from loguru import logger
from src.utils.logging import setup_logging

setup_logging(json_output=True)
logger.info("Test message", extra={"test_field": "value"})
# Output: {"timestamp": "...", "level": "INFO", "logger": "__main__", "message": "Test message", "test_field": "value"}
```

### Test Request ID Tracing

```bash
# Check X-Request-ID header
curl -i http://localhost:8000/health | grep X-Request-ID

# Use request ID in logs
REQUEST_ID="..."
cat logs.json | jq "select(.request_id == \"$REQUEST_ID\")" | head -20
```

---

## Environment Variables Reference

| Variable | Type | Required | Example |
|----------|------|----------|---------|
| `X_API_KEY_HASH` | string | Yes (or X_API_KEY) | `abc123,def456` |
| `X_API_KEY` | string | Legacy fallback | `sk-xxx` |
| `OPENAI_API_KEY` | string | Yes | `gsk_xxxx` |
| `OPENAI_BASE_URL` | string | Yes | `https://api.groq.com/openai/v1` |
| `OPENAI_MODEL_ID` | string | Yes | `meta-llama/llama-4-scout-17b-16e-instruct` |

---

## File Structure Reference

```
src/
├── app.py                          # FastAPI app + middleware
├── modal_app.py                    # Modal GPU class + model loading
│
├── api/
│   ├── health.py                   # GET /health, GET /ready
│   └── v1/
│       ├── parse.py                # POST /parse/pdf, /parse/image
│       ├── jobs.py                 # GET /jobs/{job_id}/*
│       └── router.py               # Route combiner
│
├── services/
│   ├── parser_service.py           # Orchestration logic
│   └── job_store.py                # Metadata persistence
│
├── utils/
│   ├── auth.py                     # API key verification (NEW in Phase 4)
│   ├── key_gen.py                  # Key generation (NEW in Phase 4)
│   ├── logging.py                  # JSON structured logging (NEW in Phase 4)
│   ├── files.py                    # File validation
│   └── errors.py                   # Error handling
│
├── models/
│   ├── enums.py                    # JobStatusEnum, ElementTypeEnum
│   ├── request.py                  # Pydantic request models
│   └── response.py                 # Pydantic response models
│
└── core/
    ├── parser.py                   # Docling converters
    ├── exporter.py                 # Element export
    └── preprocess.py               # Image/PDF preprocessing
```

---

## Helpful Commands

```bash
# Generate new API key
python generated_secret.py --environment prod

# Run app locally with auto-reload
uvicorn src.app:web_app --reload

# Deploy to Modal
modal deploy deploy.py

# Check Modal logs
modal logs {app_name}

# Parse JSON logs with jq
cat logs.json | jq 'select(.level == "ERROR") | {timestamp, message}'

# Pretty print single log entry
echo '{"timestamp":"..."}' | jq '.'

# Count log entries by level
cat logs.json | jq -r '.level' | sort | uniq -c
```

---

## Next Steps

1. **Deploy**: Follow `docs/DEPLOYMENT_CHECKLIST.md`
2. **Monitor**: Check logs for JSON format correctness
3. **Clients**: Distribute new API keys generated via `generated_secret.py`
4. **Test**: Verify all endpoints work with new auth system
