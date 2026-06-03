# Deployment Readiness Checklist

## Pre-Deployment Verification

### Phase 1: Structural Refactoring ✓
- [x] Folder structure organized (`src/api/`, `src/services/`, `src/models/`, `src/utils/`)
- [x] Monolithic `api.py` split into modular routers
- [x] Enums consolidated to `models/enums.py`
- [x] Business logic extracted to `services/parser_service.py`
- [x] Utilities consolidated to `utils/files.py`, `utils/auth.py`, `utils/logging.py`

### Phase 2: API Versioning (Breaking Changes) ✓
- [x] All endpoints prefixed with `/v1`
- [x] PDF submission returns 202 (async)
- [x] Job endpoints moved to `/v1/jobs/{job_id}/*`
- [x] Unified error response shape with `ErrorDetail` and `request_id`
- [x] Custom exception handlers for `AppException` and `RequestValidationError`

### Phase 3: Reliability ✓
- [x] Job metadata persisted to Modal Volume (`services/job_store.py`)
- [x] File size validation (PDF: 100MB, Image: 20MB)
- [x] `/ready` endpoint for readiness checks
- [x] Request ID middleware (`X-Request-ID` header)
- [x] Models downloaded at cold start via `@modal.enter()`
- [x] Structured logging with `request_id` context

### Phase 4: Auth & Observability ✓
- [x] Per-client key generation with format `dp_{environment}_{random64}`
- [x] SHA256 hashing for key storage (raw key never stored)
- [x] Auth system supports multiple hashed keys via `X_API_KEY_HASH` env var
- [x] Backward compatible with legacy `X_API_KEY` env var
- [x] Structured JSON logging with timestamp, level, logger, message, extra fields
- [x] CLI tool for key generation (`generated_secret.py`)
- [x] Request ID tracing across logs and API responses

---

## Files Created/Modified in Phase 4

### New Files
- `src/utils/key_gen.py` — Per-client key generation and hashing
- `docs/PHASE_4_SUMMARY.md` — Phase 4 implementation details
- `docs/DEPLOYMENT_CHECKLIST.md` — This file

### Modified Files
- `src/utils/auth.py` — Multi-key hashed validation + logging
- `src/utils/logging.py` — Structured JSON output
- `src/app.py` — Updated middleware logging format
- `generated_secret.py` — New per-client key format
- `.env.example` — New env var documentation

---

## Environment Setup

### Required Environment Variables

**For production (recommended)**:
```bash
# Generate via: python generated_secret.py --environment prod
X_API_KEY_HASH="abc123def456...,xyz789uvw012..."  # Comma-separated hashes

# OpenAI/Groq config
OPENAI_API_KEY=gsk_xxxx
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL_ID=meta-llama/llama-4-scout-17b-16e-instruct
```

**For development (fallback)**:
```bash
# Legacy single key (not recommended for production)
X_API_KEY=your-test-key
```

---

## Modal Deployment Steps

### 1. Generate API Keys
```bash
# Generate production key
python generated_secret.py --environment prod
# Note: save the raw key securely, give to clients
# Store the hash in Modal secret

# Generate dev key (optional)
python generated_secret.py --environment dev
```

### 2. Create/Update Modal Secret
```bash
# Create new secret
modal secret create parser-secret X_API_KEY_HASH="<hash1>,<hash2>"

# Or update existing
modal secret update parser-secret X_API_KEY_HASH="<hash1>,<hash2>"
```

### 3. Deploy
```bash
modal deploy deploy.py
```

### 4. Test Deployment
```bash
# Get Modal URL from deployment output
MODAL_URL="https://fahmi--document-parsing.modal.run"

# Test health endpoint (no auth required)
curl "$MODAL_URL/health"

# Test readiness endpoint (no auth required)
curl "$MODAL_URL/ready"

# Test with API key
API_KEY="dp_prod_xxxx..."
curl -X POST "$MODAL_URL/v1/parse/pdf" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@test.pdf"

# Verify response includes X-Request-ID header
curl -I -X GET "$MODAL_URL/health"
# Should show: X-Request-ID: <uuid>
```

---

## Monitoring & Observability

### Structured Logs
All logs now output to stdout in JSON format:
```json
{
  "timestamp": "2026-06-03T12:30:45Z",
  "level": "INFO",
  "logger": "src.api.v1.parse",
  "message": "PDF parse request",
  "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "filename": "report.pdf",
  "file_size_bytes": 2048000
}
```

### Log Aggregation
Configure your log aggregation system to parse JSON:
- **CloudWatch**: Use `awslogs-json` log driver
- **Datadog**: Automatically parses JSON with proper attributes
- **ELK Stack**: Use Logstash JSON codec

### Key Metrics to Monitor
- `request_id` — Trace end-to-end request flow
- `duration_seconds` — Performance tracking
- `file_size_bytes` — Usage patterns
- `error` level logs — Issues and failures
- Auth failures (`Invalid API key attempt`) — Security monitoring

---

## Migration Path from Previous Version

### For Existing Clients

1. **Request new API key**:
   ```bash
   python generated_secret.py --environment prod
   ```

2. **Receive raw key** (shown only once):
   ```
   dp_prod_xK9mN2pQ7rS1tU3vW5xY7zA9bC1dE3fG5...
   ```

3. **Update client code**:
   - Replace old `X-API-Key` header value with new per-client key
   - No other changes needed (API shape remains the same)

4. **Test with new key**:
   ```bash
   curl -X POST https://api.modal.run/v1/parse/pdf \
     -H "X-API-Key: dp_prod_xK9mN2pQ7rS1tU3vW5xY7zA9bC1dE3fG5..." \
     -F "file=@document.pdf"
   ```

### Backward Compatibility
- **Legacy keys still work** — `X_API_KEY` env var fallback
- **No API changes** — all endpoints maintain same paths and response shapes
- **Gradual migration** — can run both old and new keys simultaneously

---

## Post-Deployment Validation

### 1. Health & Readiness
```bash
# Should return 200
curl https://api.modal.run/health
curl https://api.modal.run/ready
```

### 2. Auth System
```bash
# Should return 401
curl -H "X-API-Key: invalid" https://api.modal.run/v1/parse/pdf

# Should return 422 (no file) but 401 before it gets there
curl https://api.modal.run/v1/parse/pdf

# Should work with valid key
curl -H "X-API-Key: $VALID_KEY" https://api.modal.run/v1/parse/pdf
```

### 3. Request ID Tracing
```bash
# Should include X-Request-ID in response headers
curl -i https://api.modal.run/health
# Look for: X-Request-ID: <uuid>
```

### 4. Structured Logs
- Check Modal logs (CloudWatch/Datadog)
- Verify JSON format is valid
- Confirm `request_id` appears in all logs for a single request

---

## Rollback Plan

If issues occur post-deployment:

1. **Revert Modal deployment**:
   ```bash
   git checkout HEAD~1
   modal deploy deploy.py
   ```

2. **Clear cached keys**:
   ```bash
   modal secret update parser-secret X_API_KEY_HASH=""
   # Fall back to legacy X_API_KEY if configured
   ```

3. **Notify clients** if API key format changed

---

## Success Criteria

- ✓ All endpoints accessible at `/v1/*`
- ✓ `/health` returns 200 without auth
- ✓ `/ready` returns 200 with models loaded
- ✓ PDF submission returns 202 with job_id
- ✓ Image parsing returns 200 with results
- ✓ All responses include `X-Request-ID` header
- ✓ Auth rejects invalid/missing keys with 401
- ✓ All logs output valid JSON format
- ✓ Multi-client keys work correctly
- ✓ Legacy key support maintains backward compatibility

---

## Support & Documentation

- **SYSTEM_DESIGN.md** — Architecture and design decisions
- **PHASE_4_SUMMARY.md** — Phase 4 implementation details
- **Generated keys** — Never share raw keys; use hashes in env vars
- **Logs** — JSON format suitable for grep, jq, log aggregation tools

Example log queries:
```bash
# Find all requests for a specific job
cat logs.json | jq 'select(.job_id == "fc-xxx")'

# Find auth failures
cat logs.json | jq 'select(.level == "WARNING" and .message | contains("Invalid API key"))'

# Get request timeline
cat logs.json | jq 'select(.request_id == "f47ac10b...") | [.timestamp, .message]'
```
