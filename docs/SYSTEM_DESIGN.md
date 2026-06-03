# SYSTEM DESIGN — Document Parsing API

> Production-grade design document covering architecture, REST API, folder structure,
> versioning, error handling, and operational concerns.

---

## 1. Current State Assessment

### Yang Sudah Bagus
- Modal serverless GPU — auto-scale, pay-per-use
- Separation image (sync) vs PDF (async background job)
- Deterministic element ID via SHA-256
- JSONL persistence di Modal Volume sebagai source of truth
- `secrets.compare_digest` untuk auth (timing-safe)
- Pinned dependency versions

### Pain Points yang Perlu Diperbaiki
| Area | Masalah |
|---|---|
| Folder structure | Flat — `api.py` 400+ baris, semua campur |
| API versioning | Tidak ada (`/parse/pdf` bukan `/v1/parse/pdf`) |
| Error handling | Inconsistent — mix `HTTPException` dan `JSONResponse` manual |
| Response shape | `metadata` pakai `**user_metadata` — bisa inject field sembarang |
| PDF background job | Metadata (filename, duration, page_range) tidak disimpan — hilang kalau `/result` dipanggil setelah cold Modal |
| `/result` vs `/download` | Redundant — keduanya return `PdfParseResult` |
| Logging | File log (`logs/parser.log`) tidak ada di Modal container |
| Health check | Terlalu simple — tidak ada readiness/liveness distinction |
| Auth | Hanya satu API key global — tidak ada per-client key |

---

## 2. Target Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Client                           │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼──────────────────────────────┐
│              Modal ASGI Web App                     │
│         FastAPI + Versioned Router (/v1)            │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  /parse/pdf │  │/parse/image │  │  /jobs/*    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         │ spawn          │ remote          │ poll   │
└─────────┼────────────────┼────────────────┼─────────┘
          │                │                │
┌─────────▼────────────────▼────────────────▼─────────┐
│              Modal GPU Container (A10G)              │
│                  DocumentParser cls                  │
│                                                     │
│   parse_pdf() ──► preprocess ──► docling ──► export │
│   parse_image() ─► preprocess ──► docling ──► export│
└──────────────────────────┬──────────────────────────┘
                           │ commit
          ┌────────────────▼────────────────┐
          │       Modal Volume (JSONL)       │
          │   parser-results / job-meta      │
          └──────────────────────────────────┘
```

---

## 3. Folder Structure

```
.
├── deploy.py                    # Modal deploy entrypoint
├── generated_secret.py          # CLI tool generate API key
├── pyproject.toml
├── .env.example
├── SYSTEM_DESIGN.md
│
└── src/
    ├── __init__.py
    │
    ├── app.py                   # FastAPI app factory + router registration
    ├── modal_app.py             # Modal App, image, DocumentParser cls
    │
    ├── api/
    │   ├── __init__.py
    │   ├── v1/
    │   │   ├── __init__.py
    │   │   ├── router.py        # include semua sub-router v1
    │   │   ├── parse.py         # POST /v1/parse/pdf, POST /v1/parse/image
    │   │   └── jobs.py          # GET /v1/jobs/{job_id}/status
    │   │                        # GET /v1/jobs/{job_id}/result
    │   │                        # GET /v1/jobs/{job_id}/download
    │   └── health.py            # GET /health, GET /ready
    │
    ├── core/
    │   ├── __init__.py
    │   ├── parser.py            # build_pdf_converter, build_image_converter
    │   ├── exporter.py          # export_raw_elements
    │   └── preprocess.py        # preprocess_pdf, preprocess_image
    │
    ├── models/
    │   ├── __init__.py
    │   ├── enums.py             # JobStatusEnum, ElementTypeEnum
    │   ├── request.py           # PdfParseRequest, ImageParseRequest (Form models)
    │   └── response.py          # JobSubmitted, ImageParseResult, PdfParseResult, errors
    │
    ├── services/
    │   ├── __init__.py
    │   ├── parser_service.py    # orchestrate spawn/remote, build result — logic keluar dari router
    │   └── job_store.py         # read/write job metadata ke Modal Volume
    │
    ├── utils/
    │   ├── __init__.py
    │   ├── auth.py              # verify_api_key
    │   ├── files.py             # validate_ext, read_upload, save_jsonl
    │   └── logging.py           # setup_logging
    │
    └── vision/
        ├── __init__.py
        ├── core/types.py
        ├── crop.py
        └── rotation.py
```

### Prinsip
- **`api/`** — hanya routing dan request/response shaping. Tidak ada business logic.
- **`services/`** — semua orchestration logic. Router hanya call service.
- **`core/`** — pure parsing logic, tidak tahu tentang HTTP atau Modal.
- **`models/`** — Pydantic models dipisah per concern (enums, request, response).

---

## 4. REST API Design

### Base URL
```
https://{modal-app}.modal.run/v1
```

### Versioning Strategy
- URL path versioning: `/v1/`, `/v2/`
- Header `API-Version` untuk minor changes dalam major version
- Breaking changes → major version bump
- Deprecated endpoints tetap hidup minimum 3 bulan dengan header `Deprecation: true`

### Endpoints

#### Parse

```
POST /v1/parse/image
Content-Type: multipart/form-data
X-API-Key: {key}

Body:
  file        (required) Image file — .jpg .jpeg .png .webp
  metadata    (optional) JSON string: {"company": "Acme", "year": 2024}
  enable_rotate (optional) bool, default false
  enable_crop   (optional) bool, default false

Response 200: ImageParseResult
Response 422: ValidationError
Response 401: Unauthorized
Response 500: InternalError
```

```
POST /v1/parse/pdf
Content-Type: multipart/form-data
X-API-Key: {key}

Body:
  file        (required) PDF file
  metadata    (optional) JSON string: {"company": "Acme", "year": 2024}
  start_page  (optional) int
  end_page    (optional) int
  enable_rotate (optional) bool
  enable_crop   (optional) bool

Response 202: JobSubmitted  ← bukan 200, karena async
Response 422: ValidationError
Response 401: Unauthorized
```

#### Jobs (PDF only)

```
GET /v1/jobs/{job_id}/status
X-API-Key: {key}

Response 200: JobStatus (processing | done | error | expired)
Response 404: JobNotFound
```

```
GET /v1/jobs/{job_id}/result
X-API-Key: {key}

Response 200: PdfParseResult
Response 202: still processing
Response 404: JobNotFound
Response 500: JobFailed
```

```
GET /v1/jobs/{job_id}/download
X-API-Key: {key}

Response 200: application/json attachment — sama dengan /result tapi downloadable
Response 202: still processing
Response 404: JobNotFound
```

#### Health

```
GET /health          — liveness: server up? (tidak butuh auth)
GET /ready           — readiness: models loaded? (tidak butuh auth)
```

### HTTP Status Code Convention
| Situasi | Code |
|---|---|
| Sync success | 200 |
| Async submitted | 202 |
| Still processing (poll) | 202 |
| Validation error | 422 |
| Auth failed | 401 |
| Not found / expired | 404 |
| Parsing error (Modal side) | 500 |
| Server misconfiguration | 500 |

---

## 5. Error Handling

### Unified Error Response Shape
Semua error — baik dari FastAPI exception handler maupun manual raise — harus return shape yang sama:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "start_page must be <= end_page",
    "details": {},
    "request_id": "req_abc123"
  }
}
```

### Error Codes
```python
class ErrorCode(StrEnum):
    VALIDATION_ERROR    = "VALIDATION_ERROR"     # 422 — input tidak valid
    UNSUPPORTED_FILE    = "UNSUPPORTED_FILE"      # 422 — ekstensi tidak didukung
    AUTH_FAILED         = "AUTH_FAILED"           # 401
    JOB_NOT_FOUND       = "JOB_NOT_FOUND"         # 404
    JOB_EXPIRED         = "JOB_EXPIRED"           # 404
    JOB_STILL_RUNNING   = "JOB_STILL_RUNNING"     # 202
    PARSING_FAILED      = "PARSING_FAILED"        # 500 — error dari Modal worker
    INTERNAL_ERROR      = "INTERNAL_ERROR"        # 500 — unexpected
```

### Implementation
- Daftarkan custom exception handlers di `app.py` via `@app.exception_handler`
- Buat `AppException(code, message, status_code)` base class
- **Tidak ada `JSONResponse` manual di router** — semua lewat exception atau Pydantic response model
- FastAPI `RequestValidationError` di-intercept dan di-reshape ke format yang sama

### Request ID
- Generate `request_id` di middleware untuk setiap request
- Inject ke response header `X-Request-ID` dan ke error body
- Berguna untuk tracing di logs

---

## 6. Job Metadata Persistence

### Masalah Sekarang
Metadata PDF job (filename, duration, page_range, user_metadata) hanya ada di Modal FunctionCall result — yang expire setelah 7 hari dan tidak bisa di-query setelah container die.

### Solusi: Job Metadata Store di Modal Volume

Simpan metadata job ke file JSON terpisah di Modal Volume saat job selesai:

```
/results/
  jobs/
    {job_id}.meta.json      ← metadata job
    {job_id}.jsonl          ← raw elements (JSONL)
```

`{job_id}.meta.json`:
```json
{
  "job_id": "fc-xxx",
  "filename": "report.pdf",
  "extension": ".pdf",
  "submitted_at": "2026-06-03T01:00:00Z",
  "completed_at": "2026-06-03T01:02:34Z",
  "duration_seconds": 154.2,
  "total_pages": 50,
  "start_page": 1,
  "end_page": 50,
  "element_count": 312,
  "output_path": "report_20260603_010234.jsonl",
  "user_metadata": {"company": "Acme", "year": 2024}
}
```

Dengan ini:
- `/result` dan `/download` bisa reconstruct `PdfParseResult` lengkap tanpa bergantung pada Modal FunctionCall
- Metadata tidak hilang meski FunctionCall expire
- Bisa tambah endpoint `GET /v1/jobs` (list all jobs) di masa depan

---

## 7. Response Models

### `ImageParseResult`
```json
{
  "job_id": "uuid",
  "status": "done",
  "page_count": 1,
  "metadata": {
    "filename": "receipt.jpg",
    "extension": ".jpg",
    "duration_seconds": 3.21,
    "company": "Acme"
  },
  "full_content": "East Repair Inc.\n\nItem 1...",
  "table_markdown": "| Item | Price |\n|---|---|\n| A | 10 |"
}
```

### `PdfParseResult`
```json
{
  "job_id": "fc-xxx",
  "status": "done",
  "page_count": 50,
  "metadata": {
    "filename": "report.pdf",
    "extension": ".pdf",
    "duration_seconds": 154.2,
    "page_range": {"start": 1, "end": 50},
    "company": "Acme",
    "year": 2024
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

### `metadata` Field Design
- Field fixed (`filename`, `extension`, `duration_seconds`, `page_range`) → typed Pydantic fields
- User-supplied (`company`, `year`, dll) → `extra_fields: dict[str, Any]` yang eksplisit, **bukan `**kwargs`**
- Ini mencegah user inject field yang bisa conflict dengan fixed fields

---

## 8. Auth Design

### Sekarang
Single global `X_API_KEY` env var.

### Target: Per-Client Key dengan Prefix
```
Format: dp_{environment}_{random64}
Contoh: dp_prod_xK9mN2...
         dp_dev_aB3cD4...
```

- Prefix `dp_` untuk identify token type (document-parser)
- Environment prefix untuk distinguish prod vs dev key
- Key di-hash (SHA-256) sebelum disimpan — raw key hanya muncul sekali saat generate
- Validasi: lookup hash di env/secret store, compare dengan `secrets.compare_digest`
- Future: bisa extend ke database lookup untuk multi-tenant

---

## 9. Logging & Observability

### Structured Logging
Ganti format string biasa ke structured JSON log:

```json
{
  "timestamp": "2026-06-03T01:05:56Z",
  "level": "INFO",
  "logger": "src.api.v1.parse",
  "request_id": "req_abc123",
  "job_id": "fc-xxx",
  "event": "pdf_parse_submitted",
  "filename": "report.pdf",
  "file_size_bytes": 2048000
}
```

### Di Modal Container
- Loguru output ke `sys.stdout` saja (tidak ke file) — Modal sudah capture stdout
- Log rotation tidak diperlukan karena container ephemeral
- Tambah `job_id` ke setiap log line selama parsing

### Key Events yang Harus Di-log
| Event | Level | Fields |
|---|---|---|
| Request received | INFO | request_id, endpoint, filename, file_size |
| Job submitted | INFO | request_id, job_id |
| Parse started | INFO | job_id, filename, total_pages |
| Parse completed | INFO | job_id, duration_seconds, element_count |
| Parse failed | ERROR | job_id, error, traceback |
| Auth failed | WARNING | request_id, ip |

---

## 10. Operational Concerns

### Modal Config Recommendations
```python
@app.cls(
    gpu="A10G",
    timeout=1800,           # 30 menit — cukup untuk PDF 500+ halaman
    scaledown_window=900,   # 15 menit warm — kurangi cold start untuk batch job
    min_containers=0,       # scale to zero saat idle
    max_containers=10,      # cap concurrent containers
)
@modal.concurrent(
    max_inputs=5,           # max 5 job per container
    target_inputs=2,        # scale up kalau ada 2+ job pending
)
```

### File Size Limits
Tambahkan validasi ukuran file di endpoint sebelum baca bytes:

```python
MAX_PDF_SIZE  = 100 * 1024 * 1024   # 100 MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024   # 20 MB
```

### Timeout Strategy
- Image: tidak ada timeout (`.remote.aio()`) — Modal container timeout = 1800s
- PDF: job di-spawn, tidak ada HTTP timeout. Client harus poll.
- Poll interval recommendation di `JobSubmitted.message`: "Poll every 10-30 seconds"

### Cold Start
- Model volume di-mount — models tidak perlu download ulang
- `scaledown_window=900` — container tetap warm 15 menit setelah last request
- Pertimbangkan `keep_warm=1` untuk production high-traffic

---

## 11. Migration Plan (Current → Target)

### Phase 1 — Structural (tidak breaking)
- [ ] Refactor folder structure sesuai section 3
- [x] Pisah `api.py` ke `api/v1/parse.py` dan `api/v1/jobs.py`
- [x] Pindah enum ke `models/enums.py`
- [x] Buat `services/parser_service.py` — keluarkan logic dari router

### Phase 2 — API (breaking, butuh versioning)
- [x] Tambah prefix `/v1` ke semua endpoint
- [x] Ganti `/result/{job_id}` dan `/download/{job_id}` → `/jobs/{job_id}/result` dan `/jobs/{job_id}/download`
- [x] Fix `POST /parse/pdf` status code: 200 → 202
- [x] Unified error response shape + custom exception handlers

### Phase 3 — Reliability
- [x] Implement job metadata store (`services/job_store.py`)
- [x] Structured logging dengan `request_id`
- [x] File size validation
- [x] Download model saat cold start, jadi ketika hit endpoint pertama kali langsung parse tanpa download model terlebih dahulu

### Phase 4 — Auth & Observability
- [x] Per-client key dengan prefix
- [x] Structured JSON log output
- [x] Request ID middleware
