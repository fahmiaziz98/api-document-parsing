# API Document Parsing

A production-grade REST API for parsing bilingual (Indonesian/English) documents from PDF and image formats. Built on Docling, deployed on [Modal.com](https://modal.com) with GPU acceleration.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Output Schema](#output-schema)
- [Documentation](#documentation)
- [Authentication Setup (Per-Client Keys)](#authentication-setup-per-client-keys)
- [Troubleshooting](#troubleshooting)
- [Performance Notes](#performance-notes)

---

## Overview

This service accepts PDF or image files containing documents and returns structured JSON elements including text, tables (as Markdown), and figure descriptions.

Key capabilities:

- Bilingual OCR (Indonesian and English) via SuryaOCR
- Accurate table extraction with TableFormer
- Figure/chart description via LLM (configurable via `BASE_URL` / `MODEL_ID`)
- Optional per-page auto-rotation and whitespace cropping before parsing
- Page range filtering to parse only specific sections of a document
- Asynchronous job processing with polling — suitable for large documents
- Full-page content aggregation per page number
- **Dynamic metadata**: pass any key-value pairs (e.g. `company`, `year`, `label`, `type`) at submission time
- **JSONL download**: fetch the output file directly via `GET /download/{job_id}`
- Deterministic element `id` (SHA-256) for deduplication and traceability

---

## Architecture

```
Client
  |
  POST /v1/parse/pdf  or  POST /v1/parse/image
  |
  FastAPI (Modal web endpoint — CPU container)
  |-- Auth: X-API-Key header validation
  |-- Input validation: file type, metadata JSON, page range
  |
  [/v1/parse/pdf path]
  |
  Function.spawn() --> GPU Container (A10G)
                         |
                         |-- preprocess_pdf()
                         |     PyMuPDF: set_rotation(), set_cropbox()
                         |     Vision: RotationDetector, ContentCropper
                         |
                         |-- Docling converter
                         |     SuryaOCR (id + en)
                         |     TableFormer ACCURATE
                         |     docling-layout-heron
                         |     PictureDescriptionApiOptions -> LLM
                         |
                         |-- export_raw_elements()
                         |
                         --> JSONL saved to Modal Volume
  |
  GET /v1/jobs/{job_id}/status   --> Poll until done
  GET /v1/jobs/{job_id}/result   --> Retrieve full element list
  GET /v1/jobs/{job_id}/download --> Download JSONL file

  [/v1/parse/image path — synchronous, no polling]
  |
  Function.call() --> GPU Container (A10G)  [immediate invocation, waits for result]
                         |
                         |-- preprocess_image()
                         |-- Docling converter (same as PDF)
                         |-- export_raw_elements()
                         |-- JSONL saved
                         |
                         --> Returns parsed elements immediately (200)
```


---

## Repository Structure

```
api-document-parsing/
|
|-- src/
|   |-- __init__.py
|   |-- app.py                # FastAPI app factory
|   |-- modal_app.py          # Modal App definition, GPU functions
|   |
|   |-- api/
|   |   |-- __init__.py
|   |   |-- health.py         # GET /health
|   |   |
|   |   `-- v1/
|   |       |-- __init__.py
|   |       |-- router.py     # Combines v1 routes
|   |       |-- parse.py      # POST /v1/parse/pdf, POST /v1/parse/image
|   |       `-- jobs.py       # GET /v1/jobs/{job_id}/status, /result, /download
|   |
|   |-- core/
|   |   |-- __init__.py
|   |   |-- parser.py         # Docling converter builders
|   |   |-- exporter.py       # DoclingDocument -> list[dict]
|   |   `-- preprocess.py     # PDF and image preprocessing
|   |
|   |-- models/
|   |   |-- __init__.py
|   |   |-- enums.py          # JobStatusEnum, ElementTypeEnum
|   |   |-- request.py        # Pydantic request schemas
|   |   `-- response.py       # Pydantic response schemas
|   |
|   |-- services/
|   |   |-- __init__.py
|   |   |-- parser_service.py # Orchestration logic for parsing
|   |   `-- job_store.py      # Job metadata persistence
|   |
|   |-- utils/
|   |   |-- __init__.py
|   |   |-- auth.py           # Per-client API key validation
|   |   |-- files.py          # File validation and parsing
|   |   `-- logging.py        # Structured logging setup
|   |
|   `-- vision/               # Image preprocessing utilities
|       |-- __init__.py
|       |-- rotation.py       # RotationDetector, AutoRotate
|       |-- crop.py           # ContentCropper
|       `-- core/
|           `-- types.py      # RotationAngle, RotationResult
|
|-- docs/
|   |-- SYSTEM_DESIGN.md      # Architecture and design decisions
|   |-- DEVELOPER_GUIDE.md    # Detailed development guide
|   |-- DEPLOYMENT_CHECKLIST.md
|
|
|-- deploy.py                 # Modal deploy entry point
|-- generated_secret.py       # CLI tool for API key generation
|-- pyproject.toml
|-- .env.example
`-- README.md
```

---

## Prerequisites

- Python 3.12 or higher
- [Modal CLI](https://modal.com/docs/guide) installed and authenticated
- A Groq API key (for figure description via LLM)
- A GPU is required for local development with full Docling pipeline. For local testing without GPU, use CPU mode (slower, see Development section)

---

## Installation

We strongly recommend using [`uv`](https://docs.astral.sh/uv/) for incredibly fast Python dependency management.

### 1. Clone the repository

```bash
git clone https://github.com/fahmiaziz98/api-document-parsing.git
cd api-document-parsing
```

### 2. Install dependencies with `uv`

Install the project and create an isolated virtual environment automatically:

**For Production (runtime dependencies only):**
```bash
uv sync --no-dev
```

**For Development (includes linters, testing tools, etc.):**
```bash
uv sync 
```

### 3. Activate the environment

If you need to run local commands, you can activate the environment created by `uv`:

```bash
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows
```

*(Tip: You can also use `uv run <command>` to run scripts without explicitly activating the environment.)*

### 4. Authenticate Modal

```bash
uv run modal setup
```

Follow the browser prompt to link your Modal account.

---

## Configuration

### Generate Per-Client API Keys

Generate API keys for each client/environment:

```bash
uv run generated_secret.py --environment prod
```

Output:
```
Raw Key (give to client):    dp_prod_xK9mN2pQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOp
SHA256 Hash (store on server): abc123def456789...
```

The **raw key** is what clients use in their requests. The **hash** is stored on the server.

### Environment Variables

Copy the example file:

```bash
cp .env.example .env
```

**Authentication (choose one):**

| Variable | Required | Description |
|---|---|---|
| `X_API_KEY_HASH` | Yes (recommended) | SHA256 hashes of per-client keys (comma or newline-separated) |
| `X_API_KEY` | Optional (legacy) | Legacy single global API key (deprecated) |

**LLM Configuration:**

| Variable | Required | Description |
|---|---|---|
| `OPENAI_BASE_URL` | Yes | LLM API base URL, e.g. `https://api.groq.com/openai/v1` |
| `OPENAI_API_KEY` | Yes | LLM API key for figure description |
| `OPENAI_MODEL_ID` | Yes | Vision LM model ID |

### Modal Secret

All environment variables must be stored as a Modal Secret named `parser-secret`:

```bash
# Generate a production key first
uv run generated_secret.py --environment prod

# Create Modal secret with the SHA256 hash
uv run modal secret create parser-secret \
  X_API_KEY_HASH='abc123def456...,xyz789uvw012...' \
  OPENAI_BASE_URL='https://api.groq.com/openai/v1' \
  OPENAI_API_KEY='gsk_your_api_key' \
  OPENAI_MODEL_ID='meta-llama/llama-4-scout-17b-16e-instruct'
```

To update an existing secret:

```bash
uv run modal secret create parser-secret --force \
  X_API_KEY_HASH='new_hash_here' \
  OPENAI_BASE_URL='https://api.groq.com/openai/v1' \
  OPENAI_API_KEY='new_api_key' \
  OPENAI_MODEL_ID='meta-llama/llama-4-scout-17b-16e-instruct'
```

**Note:** For multiple clients, add their hashes separated by commas or newlines in `X_API_KEY_HASH`.

---

## Development

### Running locally with Modal (recommended)

Modal `serve` mode provides hot-reload and streams logs to your terminal. The app runs on Modal infrastructure but responds to local code changes immediately.

```bash
uv run modal serve deploy.py
```

This will print a temporary URL such as:

```
https://your-username--api-document-parsing-web-dev.modal.run
```

Use this URL for testing during development. The URL is only active while `modal serve` is running.

### Testing the API locally

Health check:

```bash
curl https://<your-serve-url>/health
```

Parse a PDF (pages 1 to 5, with custom metadata):

```bash
curl -X POST https://<your-serve-url>/v1/parse/pdf \
  -H "X-API-Key: dp_prod_xK9mN2..." \
  -F "file=@./sample.pdf" \
  -F 'metadata={"company":"PT Antam","year":2024,"label":"annual-report"}' \
  -F "start_page=1" \
  -F "end_page=5"
```

Parse with no metadata (all fields optional):

```bash
curl -X POST https://<your-serve-url>/v1/parse/pdf \
  -H "X-API-Key: dp_prod_xK9mN2..." \
  -F "file=@./sample.pdf"
```

Response (202 Accepted, job submitted):

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "submitted",
  "message": "Job submitted. Poll /v1/jobs/{job_id}/status for results."
}
```

Parse a single image (returns result immediately, no polling):

```bash
curl -X POST https://<your-serve-url>/v1/parse/image \
  -H "X-API-Key: dp_prod_xK9mN2..." \
  -F "file=@./invoice.jpg" \
  -F 'metadata={"doc_type":"invoice","year":2024}'
```

Response (200 OK, immediate result):

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "page_count": 1,
  "metadata": {...},
  "full_content": "...",
  "table_markdown": null
}
```

Poll status (PDF only):

```bash
curl https://<your-serve-url>/v1/jobs/<job_id>/status \
  -H "X-API-Key: dp_prod_xK9mN2..."
```

Retrieve result (JSON):

```bash
curl https://<your-serve-url>/v1/jobs/<job_id>/result \
  -H "X-API-Key: dp_prod_xK9mN2..."
```

Download JSONL file:

```bash
curl -O -J https://<your-serve-url>/v1/jobs/<job_id>/download \
  -H "X-API-Key: dp_prod_xK9mN2..."
# saves: report_20260603_120000.jsonl
```

### Interactive API docs

Open in browser while `modal serve` is running:

```
https://<your-serve-url>/docs
```

### Structured Logging

The API outputs structured JSON logs to stdout. Each log entry includes:
- `timestamp`: ISO 8601 format
- `level`: Log level (INFO, WARNING, ERROR, etc.)
- `logger`: Source module
- `message`: Log message
- `request_id`: Unique ID for request tracing
- `job_id`: Job ID if applicable (during parsing)

This makes logs suitable for aggregation platforms like DataDog, Splunk, or similar.

---

## Deployment

### Deploy to production

```bash
uv run modal deploy deploy.py
```

This registers the app permanently. The production URL format is:

```
https://your-username--api-document-parsing-web.modal.run
```

Unlike `serve`, the deployed app keeps running after the command exits.

### Managing deployments

List all active apps:

```bash
uv run modal app list
```

Stop a running app:

```bash
uv run modal app stop api-document-parsing
```

View live logs from a deployed app:

```bash
uv run modal app logs api-document-parsing
```

### GPU configuration

GPU type is set in `src/modal_app.py`:

```python
GPU_CONFIG = "A10G"    # 24GB VRAM — default
# GPU_CONFIG = "L40S"  # 48GB VRAM — for very large documents
```

To change GPU type, update the variable and redeploy.

### Modal Volume

Parsed output files (JSONL) are stored in a Modal Volume named `parser-results`. Output filenames follow the pattern `{original_name}_{YYYYMMDD_HHMMSS}.jsonl`, e.g. `report_20260603_120000.jsonl`.

To list all output files:

```bash
uv run modal volume ls parser-results
```

To download a specific output file:

```bash
uv run modal volume get parser-results report_20260603_120000.jsonl ./local_output/
```

Or use the API directly:

```bash
curl -O -J https://<your-deploy-url>/v1/jobs/<job_id>/download \
  -H "X-API-Key: dp_prod_..."
```

---

## API Reference

**Base URL:** `https://<your-modal-app>/v1`

All endpoints require the header:

```
X-API-Key: <your-raw-api-key>
```

### POST /v1/parse/pdf

Parse a PDF document asynchronously (returns immediately with job ID).

**Form parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | file | Yes | — | PDF file (`.pdf`) |
| `metadata` | string (JSON) | No | `{}` | Arbitrary key-value metadata, e.g. `{"company":"PT Antam","year":2024,"label":"annual-report"}` |
| `start_page` | integer | No | `null` | Start page (1-indexed, inclusive) |
| `end_page` | integer | No | `null` | End page (1-indexed, inclusive) |
| `enable_rotate` | boolean | No | `false` | Auto-detect and correct page rotation |
| `enable_crop` | boolean | No | `false` | Auto-crop whitespace margins |

**Response 202 — job submitted:**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "submitted",
  "message": "Job submitted. Poll /v1/jobs/{job_id}/status for results."
}
```

**Page range behavior:**

| start_page | end_page | Result |
|---|---|---|
| null | null | Full document |
| 3 | null | Page 3 to last page |
| null | 10 | Page 1 to 10 |
| 3 | 10 | Page 3 to 10 |

---

### POST /v1/parse/image

Parse a single image file synchronously (returns results immediately, no polling).

**Form parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | file | Yes | — | Image file (`.jpg`, `.jpeg`, `.png`, `.webp`) |
| `metadata` | string (JSON) | No | `{}` | Arbitrary key-value metadata |
| `enable_rotate` | boolean | No | `false` | Auto-detect and correct image rotation |
| `enable_crop` | boolean | No | `false` | Auto-crop whitespace margins |

**Response 200 — immediate result:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "page_count": 1,
  "metadata": {
    "filename": "receipt.jpg",
    "extension": ".jpg",
    "duration_seconds": 3.21,
    "extra_fields": {
      "company": "Acme",
      "year": 2024
    }
  },
  "full_content": "East Repair Inc.\n\nItem 1...",
  "table_markdown": "| Item | Price |\n|---|---|\n| A | 10 |"
}
```

No polling needed — results are available immediately.

---

### GET /v1/jobs/{job_id}/status

Poll the current status of a submitted PDF job.

**Response 200 — done:**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "done",
  "element_count": 342,
  "output_path": "report_20260603_120000.jsonl"
}
```

**Response 200 — still processing (with 202 in practice):**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "processing"
}
```

**Response 404 — expired or not found:**

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "Job not found or expired (>7 days)",
    "request_id": "req_abc123"
  }
}
```

---

### GET /v1/jobs/{job_id}/result

Retrieve the full parsed PDF result with all pages and elements. Only call after `/status` returns `done`.

**Response 200:**

```json
{
  "job_id": "fc-01...",
  "status": "done",
  "page_count": 50,
  "metadata": {
    "filename": "report.pdf",
    "extension": ".pdf",
    "duration_seconds": 154.2,
    "page_range": {"start": 1, "end": 50},
    "extra_fields": {
      "company": "Acme",
      "year": 2024
    }
  },
  "full_content": [
    {"page": 1, "content": "..."},
    {"page": 2, "content": "..."}
  ],
  "table_markdown": [
    {"page": 3, "content": "| col | col |..."}
  ]
}
```

**Response 202:** Job still processing, try again later.

---

### GET /v1/jobs/{job_id}/download

Download the generated JSONL output file for a completed job.

**Response 200 — JSONL file download:**

```bash
curl -O -J https://<your-modal-app>/v1/jobs/fc-01KKWGK5XF08SGJQKVXD0DBQ3M/download \
  -H "X-API-Key: dp_prod_..."
# saves: report_20260603_120000.jsonl
```

**Response 202:** Job still processing.

**Response 404:** Job not found or expired.

---

### GET /health

Liveness check (no authentication required).

```json
{ "status": "ok" }
```

---

## Output Schema

### PDF Parse Result

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "done",
  "page_count": 50,
  "metadata": {
    "filename": "report.pdf",
    "extension": ".pdf",
    "duration_seconds": 154.2,
    "page_range": {"start": 1, "end": 50},
    "extra_fields": {
      "company": "PT Antam",
      "year": 2024,
      "label": "annual-report"
    }
  },
  "full_content": [
    {"page": 1, "content": "Page 1 text..."},
    {"page": 2, "content": "Page 2 text..."}
  ],
  "table_markdown": [
    {"page": 3, "content": "| col1 | col2 |\n|---|---|\n| val1 | val2 |"}
  ]
}
```

### Image Parse Result

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "page_count": 1,
  "metadata": {
    "filename": "invoice.jpg",
    "extension": ".jpg",
    "duration_seconds": 3.21,
    "extra_fields": {
      "doc_type": "invoice",
      "year": 2024
    }
  },
  "full_content": "Invoice text content...",
  "table_markdown": "| Item | Amount |\n|---|---|\n| Service | $100 |"
}
```

### Response Headers

All successful responses include:

```
X-Request-ID: req_550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json
```

The `X-Request-ID` header can be used for tracing logs and debugging.

### Metadata Fields

**Fixed fields** (always present):
- `filename`: Original uploaded filename
- `extension`: File extension (e.g., `.pdf`, `.jpg`)
- `duration_seconds`: Parsing duration in seconds (rounded to 2 decimals)
- `page_range` (PDF only): `{"start": 1, "end": 50}` — pages that were parsed
- `extra_fields`: User-supplied metadata from the `metadata` form parameter

**extra_fields**

The `extra_fields` object contains all key-value pairs from the `metadata` form parameter passed at submission time. For example:

```bash
curl -X POST https://<url>/v1/parse/pdf \
  -H "X-API-Key: dp_prod_..." \
  -F "file=@report.pdf" \
  -F 'metadata={"company":"Acme","year":2024,"label":"Q1-2024"}'
```

Results in:

```json
{
  "metadata": {
    "filename": "report.pdf",
    "extension": ".pdf",
    "duration_seconds": 120.5,
    "extra_fields": {
      "company": "Acme",
      "year": 2024,
      "label": "Q1-2024"
    }
  }
}
```

### JSONL File Format

Each line in the downloaded JSONL file represents one parsed element:

```json
{"id": "a3f8d2c1e4b7...", "element_type": "text", "label": "paragraph", "content": "...", "metadata": {...}}
{"id": "b4f9e3d2f5c8...", "element_type": "table", "label": "table", "content": "...", "metadata": {...}}
```

Each element has:
- `id`: SHA-256 deterministic ID (same document = same ID)
- `element_type`: `text`, `heading`, `table`, or `figure`
- `label`: Specific element label (e.g., `paragraph`, `title`)
- `content`: Extracted text or Markdown
- `metadata`: Document, page, and user-supplied metadata

---

## Documentation

For detailed information about the project, refer to these comprehensive guides:

| Document | Purpose |
|---|---|
| `docs/SYSTEM_DESIGN.md` | Architecture, API design, folder structure, versioning strategy |
| `docs/DEVELOPER_GUIDE.md` | Quick start, key generation, structured logging, debugging |
| `docs/DEPLOYMENT_CHECKLIST.md` | Step-by-step deployment to production |

---

## Authentication Setup (Per-Client Keys)

The API uses per-client API keys instead of a shared master key. This allows you to:

- Revoke access for individual clients without affecting others
- Track usage per client
- Rotate keys independently

### How it works

1. **Generate a key** for each client:
   ```bash
   uv run generated_secret.py --environment prod
   ```
   Output:
   ```
   Raw Key:  dp_prod_xK9mN2pQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOp
   Hash:     abc123def456789...
   ```

2. **Give the raw key** to the client (e.g., FE team)

3. **Store the hash** on the server in `X_API_KEY_HASH` env var

4. When clients make requests, they send the raw key in the `X-API-Key` header

5. The server hashes the incoming key and compares it against stored hashes (timing-safe comparison)

### Multiple clients

To support multiple clients, separate their hashes with commas or newlines:

```bash
uv run modal secret create parser-secret --force \
  X_API_KEY_HASH='hash1_here,hash2_here,hash3_here' \
  OPENAI_BASE_URL='...' \
  OPENAI_API_KEY='...' \
  OPENAI_MODEL_ID='...'
```

Each client uses their own raw key, and the server validates against the list of hashes.

---

## Troubleshooting

### 401 Unauthorized — Invalid API Key

**Error:** `{"error": {"code": "AUTH_FAILED", "message": "Invalid API key"}}`

**Solution:**

1. Verify you're using the **raw key**, not the hash
2. Verify the header name is `X-API-Key` (case-sensitive)
3. Verify the key matches one of the hashes stored in `X_API_KEY_HASH`
4. Regenerate a key if needed: `uv run generated_secret.py --environment prod`

---

### 422 Validation Error — Invalid metadata JSON

**Error:** `{"error": {"code": "VALIDATION_ERROR", "message": "metadata must be valid JSON"}}`

**Solution:**

Ensure the `metadata` form parameter is valid JSON:

```bash
# ❌ Wrong — single quotes, unquoted keys
-F 'metadata={'company':'Acme'}'

# ✅ Correct — double quotes, proper JSON
-F 'metadata={"company":"Acme"}'
```

---

### 422 Validation Error — start_page > end_page

**Error:** `start_page must be <= end_page`

**Solution:**

Ensure `start_page` is less than or equal to `end_page`. Leave both empty to parse the entire document.

---

### Job returns 500 after status shows done

**Symptom:** `/v1/jobs/{job_id}/status` returns `done`, but `/v1/jobs/{job_id}/result` returns 500 error

**Reason:** The GPU function raised an exception during parsing. Check the container logs:

```bash
uv run modal app logs api-document-parsing
```

Look for the traceback associated with the job's function call ID.

---

### Modal serve times out — request takes too long

**Reason:** Modal requests have a default timeout of ~120 seconds. PDFs with 500+ pages may exceed this.

**Solution:** 

For large documents, use the async job submission (`POST /v1/parse/pdf` returns 202 immediately). Then poll for results:

```bash
# Submit job (returns immediately with job_id)
curl -X POST https://<url>/v1/parse/pdf \
  -H "X-API-Key: dp_prod_..." \
  -F "file=@huge_document.pdf"

# Poll until done
curl https://<url>/v1/jobs/<job_id>/status \
  -H "X-API-Key: dp_prod_..."
```

---

### ModuleNotMountable: vision has no spec

Modal cannot find a local module via Python's import mechanism.

**Fix:** Use `add_local_dir` instead of `add_local_python_source` in `modal_app.py`:

```python
.add_local_dir("src", remote_path="/root/src")
```

Ensure `vision/` is inside `src/` and imported as `src.vision`.

---

### No matching distribution found for docling-surya

`docling-surya` requires Python 3.12. Check that your Modal image specifies the correct version:

```python
modal.Image.debian_slim(python_version="3.12")
```

---

### CropBox not in MediaBox

Occurs when `set_cropbox()` is called with coordinates that fall outside the page's MediaBox, typically after a 90-degree rotation changes the page dimensions.

**Fix:** Always use `page.mediabox` (not `page.rect`) as the coordinate reference when computing cropbox, and apply the intersection operator before setting:

```python
cropbox = cropbox & page.mediabox
```

---

### TypeError: NoneType object is not subscriptable (page_range)

Docling does not accept `None` inside a page range tuple. Always resolve both ends of the range to concrete integers before passing to `converter.convert()`.

---

### OCR running on every page despite native PDF text

This happens when pages have been re-rendered to raster images before being saved back to PDF. Ensure that rotation and crop operations use `set_rotation()` and `set_cropbox()` (PyMuPDF native operations) and do not reconstruct the PDF from rendered page images.

---

### AsyncUsageWarning in FastAPI endpoint

Blocking Modal interfaces used inside async FastAPI handlers cause performance issues. Replace all `.spawn()` calls with `await .spawn.aio()` and all `.get()` calls with `await .get.aio()`.

---

## Performance Notes

### Reducing cold start time

Modal containers start from scratch on the first request after a period of inactivity. Model weights (layout, OCR, TableFormer) are downloaded on first run. To persist weights across restarts, use a Modal Volume for model caching:

```python
model_volume = modal.Volume.from_name("docling-models", create_if_missing=True)

@app.function(
    volumes={
        "/results": results_volume,
        "/root/.cache": model_volume,   # cache HuggingFace and Docling models
    }
)
```

The `scaledown_window=900` (15 minutes) keeps the container warm for follow-up requests.

### Batch processing multiple documents

Submit all jobs first, then poll. Do not wait for each job to complete before submitting the next:

```python
job_ids = []
for pdf_path in pdf_list:
    response = requests.post("https://<url>/v1/parse/pdf", ...)
    job_ids.append(response.json()["job_id"])

# Poll all jobs concurrently
for job_id in job_ids:
    while True:
        status = requests.get(f"https://<url>/v1/jobs/{job_id}/status", ...).json()
        if status["status"] == "done":
            break
        time.sleep(10)
```

### Page range for large documents

For annual reports with 200+ pages, always use `start_page` and `end_page` to limit parsing to relevant sections. Financial statements are typically found in the final 30 to 50 percent of the document.

### Polling intervals

Recommended polling interval: **10-30 seconds**. Polling too frequently wastes API calls; polling too infrequently increases perceived latency.
