# Annual Report Parser

A production-grade REST API for parsing bilingual (Indonesian/English) corporate annual reports from PDF and image formats. Built on Docling, deployed on Modal.com with GPU acceleration.

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
- [Troubleshooting](#troubleshooting)
- [Performance Notes](#performance-notes)

---

## Overview

This service accepts PDF or image files containing corporate annual reports and returns structured JSON elements including text, tables (as Markdown), and figure descriptions. Each element carries full provenance metadata (page number, bounding box, section, company, year).

Key capabilities:

- Bilingual OCR (Indonesian and English) via SuryaOCR
- Accurate table extraction with TableFormer
- Figure/chart description via LLM (Groq)
- Optional per-page auto-rotation and whitespace cropping before parsing
- Page range filtering to parse only specific sections of a document
- Asynchronous job processing with polling — suitable for large documents
- Full-page content aggregation per page number

---

## Architecture

```
Client
  |
  POST /parse/pdf  or  POST /parse/image
  |
  FastAPI (Modal web endpoint — CPU container)
  |-- Auth: X-API-Key header validation
  |-- Input validation: file type, page range
  |
  Function.spawn() --> GPU Container (A10G)
                         |
                         |-- preprocess_pdf() / preprocess_image()
                         |     PyMuPDF: set_rotation(), set_cropbox()
                         |     Vision: RotationDetector, ContentCropper
                         |
                         |-- Docling converter
                         |     SuryaOCR (id + en)
                         |     TableFormer ACCURATE
                         |     docling-layout-heron
                         |     PictureDescriptionApiOptions -> Groq LLM
                         |
                         |-- export_raw_elements()
                         |     Per-element: text, table, figure
                         |     Per-page: full_content aggregation
                         |
                         --> JSONL saved to Modal Volume
  |
  GET /status/{job_id}   --> Poll until done
  GET /result/{job_id}   --> Retrieve full element list
```

---

## Repository Structure

```
api-document-parsing/
|
|-- src/
|   |-- __init__.py
|   |-- modal_app.py          # Modal App definition, GPU functions
|   |-- api.py                # FastAPI routes
|   |
|   |-- core/
|   |   |-- __init__.py
|   |   |-- parser.py         # Docling converter builders
|   |   |-- exporter.py       # DoclingDocument -> list[dict]
|   |   `-- preprocess.py     # PDF and image preprocessing
|   |
|   |-- models/
|   |   |-- __init__.py
|   |   |-- request.py        # Pydantic request schemas
|   |   `-- response.py       # Pydantic response schemas
|   |
|   `-- utils/
|       |-- __init__.py
|       |-- auth.py           # API key middleware
|       `-- logging.py        # Loguru setup
|
|-- src/vision/               # Image preprocessing utilities
|   |-- __init__.py
|   |-- rotation.py           # RotationDetector, AutoRotate
|   |-- crop.py               # ContentCropper
|   `-- core/
|       `-- types.py          # RotationAngle, RotationResult
|
|-- deploy.py                 # Modal deploy entry point
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

### Generate API Key

```bash
uv run generated_secret.py
```

### Environment Variables

Copy the example file:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `API_KEY` | Yes | Master API key for all endpoints |
| `GROQ_API_KEY` | Yes | Groq API key for figure description |
| `GROQ_BASE_URL` | Yes | `https://api.groq.com/openai/v1` |
| `GROQ_MODEL_ID` | No | Default: `llama-3.3-70b-versatile` |

### Modal Secret

All environment variables must be stored as a Modal Secret named `parser-secret`:

```bash
uv run modal secret create parser-secret \
  API_KEY=sk-your-key-here \
  GROQ_API_KEY=gsk_xxxxxxxxxxxx \
  GROQ_BASE_URL=https://api.groq.com/openai/v1 \
  GROQ_MODEL_ID=llama-3.3-70b-versatile
```

To update an existing secret:

```bash
uv run modal secret create parser-secret --force \
  API_KEY=sk-new-key \
  GROQ_API_KEY=gsk_xxxxxxxxxxxx \
  GROQ_BASE_URL=https://api.groq.com/openai/v1
```

---

## Development

### Running locally with Modal (recommended)

Modal `serve` mode provides hot-reload and streams logs to your terminal. The app runs on Modal infrastructure but responds to local code changes immediately.

```bash
uv run modal serve deploy.py
```

This will print a temporary URL such as:

```
https://your-username--annual-report-parser-web-dev.modal.run
```

Use this URL for testing during development. The URL is only active while `modal serve` is running.

### Testing the API locally

Health check:

```bash
curl https://<your-serve-url>/health
```

Parse a PDF (pages 1 to 5):

```bash
curl -X POST https://<your-serve-url>/parse/pdf \
  -H "X-API-Key: sk-your-key" \
  -F "file=@./sample.pdf" \
  -F "company=ANTAM" \
  -F "year=2024" \
  -F "start_page=1" \
  -F "end_page=5"
```

Poll status:

```bash
curl https://<your-serve-url>/status/<job_id> \
  -H "X-API-Key: sk-your-key"
```

Retrieve result:

```bash
curl https://<your-serve-url>/result/<job_id> \
  -H "X-API-Key: sk-your-key"
```

### Interactive API docs

Open in browser while `modal serve` is running:

```
https://<your-serve-url>/docs
```

---

## Deployment

### Deploy to production

```bash
uv run modal deploy deploy.py
```

This registers the app permanently. The production URL format is:

```
https://your-username--annual-report-parser-web.modal.run
```

Unlike `serve`, the deployed app keeps running after the command exits.

### Managing deployments

List all active apps:

```bash
uv run modal app list
```

Stop a running app:

```bash
uv run modal app stop annual-report-parser
```

View live logs from a deployed app:

```bash
uv run modal app logs annual-report-parser
```

### GPU configuration

GPU type is set in `src/modal_app.py`:

```python
GPU_CONFIG = "A10G"    # 24GB VRAM — default
# GPU_CONFIG = "L40S"  # 48GB VRAM — for very large documents
```

To change GPU type, update the variable and redeploy.

### Modal Volume

Parsed output files (JSONL) are stored in a Modal Volume named `parser-results`. To inspect:

```bash
uv run modal volume ls parser-results
```

To download a specific output file:

```bash
uv run modal volume get parser-results ANTAM_2024_report.jsonl ./local_output/
```

---

## API Reference

All endpoints require the header:

```
X-API-Key: <your-api-key>
```

### POST /parse/pdf

Parse a PDF annual report.

**Form parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | PDF file |
| `company` | string | Yes | Company name, e.g. `PT Antam` |
| `year` | integer | Yes | Report year, e.g. `2024` |
| `start_page` | integer | No | Start page, 1-indexed inclusive |
| `end_page` | integer | No | End page, 1-indexed inclusive |
| `enable_rotate` | boolean | No | Auto-detect and correct page rotation |
| `enable_crop` | boolean | No | Auto-crop whitespace margins |

**Response 202:**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "submitted",
  "message": "PDF parsing started. Poll GET /status/fc-01..."
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

### POST /parse/image

Parse a single image file (JPG, PNG, TIFF, BMP).

**Form parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | Image file |
| `company` | string | Yes | Company name |
| `year` | integer | Yes | Report year |
| `enable_rotate` | boolean | No | Auto-detect and correct image rotation |
| `enable_crop` | boolean | No | Auto-crop whitespace margins |

**Response 202:** Same structure as `/parse/pdf`.

---

### GET /status/{job_id}

Poll the status of a submitted job.

**Response 202 — still processing:**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "processing"
}
```

**Response 200 — done:**

```json
{
  "job_id": "fc-01KKWGK5XF08SGJQKVXD0DBQ3M",
  "status": "done",
  "element_count": 342,
  "output_path": "PT_Antam_2024_report.jsonl"
}
```

**Response 404 — expired:**

```json
{
  "job_id": "fc-01...",
  "status": "expired",
  "error": "Job not found or expired (>7 days)"
}
```

---

### GET /result/{job_id}

Retrieve the full parsed element list. Only call after `/status` returns `done`.

**Response 200:**

```json
{
  "job_id": "fc-01...",
  "status": "done",
  "element_count": 342,
  "elements": [ ... ]
}
```

**Response 202:** Job still processing, try again later.

---

### GET /health

Returns service health. No authentication required.

```json
{ "status": "ok" }
```

---

## Output Schema

Each element in the `elements` array follows this structure:

```json
{
  "element_type": "text",
  "label": "paragraph",
  "content": "Laporan Posisi Keuangan Konsolidasian...",
  "table_markdown": null,
  "full_content": "Full aggregated text of all elements on this page...",
  "metadata": {
    "source": "ANTAM_801_821.pdf",
    "company": "PT Antam",
    "year": 2024,
    "doc_ref": "#/texts/2",
    "page": 5,
    "pages": [5],
    "bbox": {
      "l": 56.7,
      "t": 112.3,
      "r": 540.1,
      "b": 145.8
    },
    "level": 1
  }
}
```

### Element types

| element_type | Description |
|---|---|
| `text` | Regular paragraph, caption, footnote |
| `heading` | Section header detected by layout model |
| `table` | Extracted table. `content` and `table_markdown` contain Markdown |
| `figure` | Image or chart. `content` contains LLM-generated description |

### full_content field

`full_content` contains all element content from the same page concatenated with double newlines. This field is identical across all elements on the same page. It is intended for use cases where full-page context is needed alongside individual element retrieval.

---

## Troubleshooting

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

### Job returns 500 after status shows done

This usually means the GPU function raised an exception that was caught and stored by Modal. Check the container logs:

```bash
modal app logs annual-report-parser
```

Look for the traceback associated with the `fc-` function call ID.

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

### Batch processing multiple documents

Submit all jobs first, then poll. Do not wait for each job to complete before submitting the next:

```python
job_ids = []
for pdf_path in pdf_list:
    response = requests.post("/parse/pdf", ...)
    job_ids.append(response.json()["job_id"])

# Poll all jobs concurrently
for job_id in job_ids:
    while True:
        status = requests.get(f"/status/{job_id}", ...).json()
        if status["status"] == "done":
            break
        time.sleep(10)
```

### Page range for large documents

For annual reports with 200+ pages, always use `start_page` and `end_page` to limit parsing to relevant sections. Financial statements are typically found in the final 30 to 50 percent of the document.
