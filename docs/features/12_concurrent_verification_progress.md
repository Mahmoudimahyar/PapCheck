# Feature 12: Concurrent Verification & Pipeline Progress UI

**Priority:** High
**Dependencies:** Feature 08 (Citation-First), Feature 11 (Retry Workflow)
**Status:** Designed

---

## Problem Statement

### Speed
The "Verify Claims" stage processes claims **sequentially** — one LLM call at a time. For a 122-reference manuscript producing ~304 claims, this means ~304 serial LLM calls. At ~2-4 seconds per call, that's **10-20 minutes** for verification alone. With the retry workflow (Feature 11), some claims make 2-4 LLM calls, making it even slower.

Every other pipeline stage (parsing, matching, gap resolution) completes in seconds. Verification is the bottleneck by 100x.

### Progress Visibility
The current pipeline tracker shows stage-level status (running/complete) with basic current/total counts, but:
- No percentage displayed
- No estimated time remaining
- No throughput rate (claims/second)
- No per-claim granularity during verification
- User has no idea if "34/304" means 2 minutes or 20 minutes remaining

---

## Solution Overview

### 1. Concurrent LLM Calls
Run N claims in parallel using `asyncio.Semaphore` + `asyncio.gather()`. The existing `asyncio.to_thread(litellm.completion(...))` pattern already supports this — each call runs in its own thread.

```
BEFORE (sequential):
  Claim 1 ──[LLM 2.5s]──→ Claim 2 ──[LLM 3s]──→ Claim 3 ──→ ...
  Total: 304 × ~3s = ~15 minutes

AFTER (concurrent, N=10):
  Claim 1  ──[LLM]──→
  Claim 2  ──[LLM]──→
  Claim 3  ──[LLM]──→
  ...       (10 at a time)
  Claim 10 ──[LLM]──→
  Total: 304 / 10 × ~3s = ~1.5 minutes (10x speedup)
```

### 2. Granular Progress Tracking
Enhanced SSE events that emit after EACH claim completes, with computed ETA:

```json
{
  "stage": 5,
  "status": "running",
  "progress": {
    "current": 47,
    "total": 304,
    "percent": 15.5,
    "rate": 3.2,
    "elapsed_seconds": 14.7,
    "estimated_remaining_seconds": 80.3
  },
  "message": "Verifying claims... 47/304"
}
```

### 3. Minimalistic Progress UI
A clean, compact progress display that fits the existing shadcn/Tailwind aesthetic.

---

## Part 1: Concurrent Verification Engine

### Architecture

```
┌──────────────────────────────────────────┐
│           Verification Orchestrator       │
│                                           │
│  claims[] ──→ Semaphore(N=10)            │
│               │                           │
│         ┌─────┴─────┐                    │
│         │ Worker Pool │                   │
│         │  (N slots)  │                   │
│         └─────┬─────┘                    │
│               │                           │
│    ┌──────────┼──────────┐               │
│    ▼          ▼          ▼               │
│  verify()  verify()  verify()  ...       │
│    │          │          │               │
│    ▼          ▼          ▼               │
│  result    result    result              │
│    │          │          │               │
│    └──────────┼──────────┘               │
│               ▼                           │
│         progress_callback()               │
│         (emit SSE event)                  │
└──────────────────────────────────────────┘
```

### Concurrency Configuration

```python
class ConcurrencyConfig(BaseModel):
    """Configuration for concurrent verification."""
    max_concurrent_claims: int = 10          # claims processed in parallel
    max_concurrent_per_provider: dict[str, int] = {
        "anthropic": 5,      # Claude rate limits (~50 RPM)
        "nvidia_nim": 10,    # NVIDIA NIM is generous
        "gemini": 8,         # Google rate limits vary
        "xai": 5,            # Grok limits
    }
    retry_delay_on_rate_limit: float = 2.0   # seconds to wait on 429
    max_retries_on_rate_limit: int = 3
```

### Provider-Level Rate Limiting

Each LLM provider has its own semaphore to prevent hitting rate limits:

```python
class ProviderSemaphores:
    """Per-provider concurrency limits."""
    def __init__(self, config: ConcurrencyConfig):
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._config = config
    
    def get(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            limit = self._config.max_concurrent_per_provider.get(provider, 5)
            self._semaphores[provider] = asyncio.Semaphore(limit)
        return self._semaphores[provider]
```

### The Concurrent Verification Function

```python
async def verify_claims_concurrent(
    claims: list[Claim],
    references: dict[int, Reference],
    config: ConcurrencyConfig,
    progress_callback: Callable[[int, int, float], Awaitable[None]] | None = None,
) -> list[VerificationResult]:
    """Verify all claims concurrently with rate limiting.
    
    Args:
        claims: all claims to verify
        references: map of reference_id → Reference
        config: concurrency limits
        progress_callback: async fn(completed, total, elapsed_seconds)
    """
    semaphore = asyncio.Semaphore(config.max_concurrent_claims)
    provider_sems = ProviderSemaphores(config)
    results: list[VerificationResult | None] = [None] * len(claims)
    completed = 0
    start_time = time.monotonic()
    lock = asyncio.Lock()

    async def verify_one(index: int, claim: Claim) -> None:
        nonlocal completed
        async with semaphore:
            provider = _get_provider_for_claim(claim, references)
            async with provider_sems.get(provider):
                try:
                    result = await verify_single_claim(claim, references)
                    results[index] = result
                except RateLimitError:
                    await _retry_with_backoff(index, claim, results, config)
                except Exception as e:
                    results[index] = _make_error_result(claim, e)
                finally:
                    async with lock:
                        completed += 1
                        if progress_callback:
                            elapsed = time.monotonic() - start_time
                            await progress_callback(completed, len(claims), elapsed)

    tasks = [verify_one(i, claim) for i, claim in enumerate(claims)]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    return [r for r in results if r is not None]
```

### Rate Limit Handling

When a 429 (rate limit) response comes back:
1. Wait `retry_delay_on_rate_limit` seconds (exponential backoff: 2s, 4s, 8s)
2. Retry up to `max_retries_on_rate_limit` times
3. If still failing, reduce the provider semaphore by 1 (adaptive throttling)
4. Log the rate limit hit for monitoring

```python
async def _retry_with_backoff(
    index: int,
    claim: Claim,
    results: list,
    config: ConcurrencyConfig,
) -> None:
    for attempt in range(config.max_retries_on_rate_limit):
        delay = config.retry_delay_on_rate_limit * (2 ** attempt)
        logger.warning("Rate limited, retry %d in %.1fs", attempt + 1, delay)
        await asyncio.sleep(delay)
        try:
            result = await verify_single_claim(claim, references)
            results[index] = result
            return
        except RateLimitError:
            continue
    results[index] = _make_error_result(claim, RateLimitError("Exhausted retries"))
```

### Error Isolation

One failed claim must NOT crash the entire batch. Each claim is independently wrapped:
- Timeout per claim: 30 seconds (configurable)
- On timeout: mark as `cannot_verify` with reason `llm_error`
- On exception: mark as `cannot_verify` with reason `llm_error`, log full traceback
- On rate limit: retry with backoff, then error

---

## Part 2: Progress Tracking Engine

### ProgressTracker Class

```python
class ProgressTracker:
    """Track progress for a pipeline stage with ETA computation."""
    
    def __init__(self, total: int, stage_name: str):
        self.total = total
        self.stage_name = stage_name
        self.completed = 0
        self.start_time = time.monotonic()
        self._recent_times: deque[float] = deque(maxlen=20)  # rolling window for rate
    
    def tick(self) -> ProgressSnapshot:
        """Record one item completed, return current snapshot."""
        now = time.monotonic()
        self._recent_times.append(now)
        self.completed += 1
        
        elapsed = now - self.start_time
        rate = self._compute_rate()
        remaining_items = self.total - self.completed
        estimated_remaining = remaining_items / rate if rate > 0 else 0.0
        
        return ProgressSnapshot(
            current=self.completed,
            total=self.total,
            percent=round(self.completed / self.total * 100, 1) if self.total > 0 else 0,
            rate=round(rate, 2),
            elapsed_seconds=round(elapsed, 1),
            estimated_remaining_seconds=round(estimated_remaining, 1),
        )
    
    def _compute_rate(self) -> float:
        """Compute items/second using rolling window for smooth ETA."""
        if len(self._recent_times) < 2:
            elapsed = time.monotonic() - self.start_time
            return self.completed / elapsed if elapsed > 0 else 0.0
        window_duration = self._recent_times[-1] - self._recent_times[0]
        if window_duration <= 0:
            return 0.0
        return (len(self._recent_times) - 1) / window_duration
```

### ProgressSnapshot Model

```python
class ProgressSnapshot(BaseModel):
    current: int
    total: int
    percent: float          # 0.0 to 100.0
    rate: float             # items per second
    elapsed_seconds: float
    estimated_remaining_seconds: float
```

### SSE Event Format (Enhanced)

The existing SSE event format is extended — fully backward compatible:

```json
{
  "stage": 5,
  "stage_name": "verify_claims",
  "status": "running",
  "progress": {
    "current": 47,
    "total": 304,
    "percent": 15.5,
    "rate": 3.2,
    "elapsed_seconds": 14.7,
    "estimated_remaining_seconds": 80.3
  },
  "message": "Verifying claims... 47/304 (~1m 20s remaining)"
}
```

New fields added to the existing `progress` object: `percent`, `rate`, `estimated_remaining_seconds`. Existing `current`, `total`, `elapsed_seconds` remain unchanged.

### Apply Progress to ALL Stages

Not just verification — every stage gets a ProgressTracker:

| Stage | Items Tracked | Typical Speed |
|-------|-------------|---------------|
| 1. Parse DOCX | paragraphs parsed | instant |
| 2. Extract Citations | citations found | instant |
| 3. Match PDFs | references matched | < 5s |
| 4. Resolve Gaps | references resolved | 10-30s (API calls) |
| 5. Verify Claims | claims verified | **1-20 min (the bottleneck)** |
| 6. Generate Report | sections written | < 5s |

Stages 1-3 and 6 are so fast they'll flash 0→100%. That's fine — the UI handles it gracefully. The progress display is most valuable for stages 4 and 5.

---

## Part 3: Progress UI Component

### Design Philosophy
- **Minimalistic**: no clutter, no unnecessary elements
- **Informative at a glance**: percentage + ETA visible without clicking
- **Fits shadcn/Tailwind**: uses existing design system components
- **Progressive disclosure**: compact by default, expandable for details

### Component: `pipeline-progress.tsx`

Replaces or enhances the existing `pipeline-tracker.tsx`.

```
┌─────────────────────────────────────────────┐
│  RefCheck Verification Pipeline              │
│                                              │
│  ✅ Parse Manuscript          3s             │
│  ✅ Extract Citations         1s  (304 found)│
│  ✅ Match PDFs               4s  (95 matched)│
│  ✅ Resolve Gaps            28s  (27 pending)│
│  🔄 Verify Claims    ━━━━━━━━━░░░  72%      │
│     219/304 · 3.2/s · ~26s left             │
│  ○  Generate Report                          │
│                                              │
└─────────────────────────────────────────────┘
```

### Detailed Layout

**Each stage row:**
```
[StatusIcon] [Stage Name]      [Duration/Progress]
```

**StatusIcon states:**
- `○` (muted gray circle) — pending
- `🔄` (spinner animation) — running
- `✅` (green check) — complete
- `❌` (red x) — error

**Running stage (expanded):**
```
🔄 Verify Claims    ━━━━━━━━━░░░  72%
   219/304 · 3.2/s · ~26s left
```

The progress bar uses shadcn's `Progress` component (thin, 4px height). Below it, a single line of metadata in muted text:
- `{current}/{total}` — absolute progress
- `{rate}/s` — throughput
- `~{time} left` — estimated remaining (formatted as "26s", "2m 15s", "8m")

**Completed stage:**
```
✅ Verify Claims     2m 14s  (304 verified)
```

Shows total duration and a summary count.

### Time Formatting

```typescript
function formatDuration(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const min = Math.floor(seconds / 60);
    const sec = Math.round(seconds % 60);
    if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
    const hrs = Math.floor(min / 60);
    const remainMin = min % 60;
    return `${hrs}h ${remainMin}m`;
}
```

### ETA Smoothing

To prevent the ETA from jittering wildly (e.g., "26s left" → "42s left" → "19s left"), use exponential moving average on the frontend:

```typescript
const SMOOTHING = 0.3;
smoothedEta = SMOOTHING * newEta + (1 - SMOOTHING) * previousEta;
```

### Animation

- Progress bar: CSS transition `width 300ms ease-out` for smooth filling
- Spinner: shadcn's `Loader2` icon with `animate-spin`
- Stage completion: brief fade from running → complete
- No bounce, no pulse, no attention-grabbing animations — just smooth transitions

### Overall Progress (Optional Header)

If the user wants a single high-level indicator:
```
━━━━━━━━━━━━━━━━━━━━━░░░░  Stage 5/6 · ~26s remaining
```

A thin bar at the very top showing overall pipeline progress across all 6 stages.

---

## Part 4: Concurrency for Other Pipeline Stages

### Gap Resolution (Stage 4)

Currently resolves references one at a time (API calls to CrossRef, PubMed, Unpaywall). Apply concurrency here too:

```python
async def resolve_gaps_concurrent(
    references: list[Reference],
    config: ConcurrencyConfig,
    progress_callback: Callable | None = None,
) -> list[Reference]:
    semaphore = asyncio.Semaphore(config.max_concurrent_claims)  # reuse same limit
    # ... same pattern as verify_claims_concurrent
```

API rate limits for gap resolution:
- CrossRef: 50 req/s with polite pool (mailto header)
- PubMed: 10 req/s without API key, 30 req/s with API key
- Unpaywall: 100 req/s with email
- Semantic Scholar: 100 req/s

Safe default: 5 concurrent gap resolution tasks.

### PDF Matching (Stage 3)

PDF matching is mostly local (DOI comparison, fuzzy title matching). Only the LLM fallback matcher needs concurrency limits. Apply semaphore only to LLM fallback calls.

---

## Part 5: Configuration & Defaults

### Environment Variables

```
REFCHECK_MAX_CONCURRENT_CLAIMS=10       # parallel claim verifications
REFCHECK_MAX_CONCURRENT_RESOLVE=5       # parallel gap resolution tasks
REFCHECK_CLAIM_TIMEOUT_SECONDS=30       # per-claim timeout
REFCHECK_RATE_LIMIT_RETRY_DELAY=2.0     # initial backoff on 429
REFCHECK_RATE_LIMIT_MAX_RETRIES=3       # max retries per rate limit
```

### Sensible Defaults by Provider

| Provider | Default Concurrent | Reasoning |
|----------|-------------------|-----------|
| Anthropic | 5 | ~50 RPM on standard tier |
| NVIDIA NIM | 10 | Generous free tier |
| Google Gemini | 8 | Standard quota |
| xAI (Grok) | 5 | Beta tier limits |

### Adaptive Throttling

If the system detects 3+ rate limit errors in 10 seconds for a provider:
1. Reduce that provider's semaphore by 2
2. Log a warning: "Reducing {provider} concurrency to {new_limit}"
3. After 60 seconds without rate limits, restore original limit

---

## Part 6: Interaction with Multi-LLM (Feature 09)

When multi-LLM voting is active:
- **Within-claim parallelism**: Tier 0's 3 models already run in parallel (Feature 09)
- **Across-claim parallelism**: This feature (Feature 12) runs N claims in parallel
- **Combined**: 10 claims × 3 models = 30 concurrent LLM calls at peak

The provider-level semaphores prevent this from overloading any single provider. Each claim's voting flow (Tier 0 → Tier 1 → ...) runs as a single async task. The across-claim semaphore limits how many voting flows run simultaneously.

```
Claim 1:  [GF + L8 + QwQ] → [vote] → [maybe escalate]
Claim 2:  [GF + L8 + QwQ] → [vote] → [done]
Claim 3:  [GF + L8 + QwQ] → [vote] → [L70 + GRK] → [vote] → [done]
...
(10 claims flowing through tiers simultaneously)
```

---

## Done Criteria

**Concurrency:**
- [ ] Claims verified concurrently via `asyncio.Semaphore` + `asyncio.gather()`
- [ ] Configurable concurrency limit (default 10)
- [ ] Per-provider rate limit semaphores
- [ ] Rate limit retry with exponential backoff
- [ ] Adaptive throttling on repeated 429s
- [ ] Per-claim timeout (30s default)
- [ ] One claim's failure doesn't crash the batch
- [ ] Gap resolution also runs concurrently (default 5)
- [ ] Verification is ≥5x faster than sequential for 100+ claims

**Progress Tracking:**
- [ ] ProgressTracker computes: current, total, percent, rate, elapsed, ETA
- [ ] ETA uses rolling window (last 20 items) for smooth estimate
- [ ] SSE events emitted per claim completion with full progress snapshot
- [ ] All 6 pipeline stages emit progress events (not just verify)

**Progress UI:**
- [ ] Each stage shows: status icon, name, duration OR progress
- [ ] Running stage shows: thin progress bar + percent + metadata line
- [ ] Metadata line: `{current}/{total} · {rate}/s · ~{time} left`
- [ ] ETA smoothed on frontend (exponential moving average)
- [ ] Progress bar animates smoothly (CSS transition)
- [ ] Completed stages show duration + summary count
- [ ] Time formatted: "26s", "2m 15s", "1h 3m"
- [ ] Works for both fast stages (flash to 100%) and slow stages (gradual fill)
- [ ] Fits existing shadcn/Tailwind design system
- [ ] No excessive animations — smooth and professional

**Quality:**
- [ ] All existing tests pass
- [ ] `ruff check src/` → 0 errors
- [ ] `mypy src/` → 0 errors
- [ ] `cd frontend && npm run build` → success
- [ ] No file exceeds 200 lines
