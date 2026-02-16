# Feature 09: Multi-LLM Cost Optimization, PDF Resolution & Viewer UX

**Priority:** High
**Dependencies:** Feature 08 (Citation-First Verification)

---

## Part 1: Providers & API Keys

| Provider | User .env Key | litellm Env Key | litellm Prefix |
|----------|--------------|-----------------|----------------|
| NVIDIA NIM | `NVIDIA_API_KEY` | `NVIDIA_NIM_API_KEY` | `nvidia_nim/` |
| Google Gemini | `GEMINI_API_KEY` | `GEMINI_API_KEY` | `gemini/` |
| xAI (Grok) | `GROK_API_KEY` | `XAI_API_KEY` | `xai/` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | `anthropic/` |

Startup mapping required (NVIDIA_API_KEY→NVIDIA_NIM_API_KEY, GROK_API_KEY→XAI_API_KEY).

---

## Part 2: Model Selection (from NVIDIA Build Catalog)

### Primary Models

| Alias | litellm ID | Params | Tier | Abbrev | Provider |
|-------|-----------|--------|------|--------|----------|
| `gemini_flash` | `gemini/gemini-2.0-flash` | — | 0 | GF | Google |
| `llama_8b` | `nvidia_nim/meta/llama-3.1-8b-instruct` | 8B | 0 | L8 | NVIDIA |
| `qwq_32b` | `nvidia_nim/qwen/qwq-32b` | 32B | 0 | QwQ | NVIDIA |
| `llama_70b` | `nvidia_nim/meta/llama-3.3-70b-instruct` | 70B | 1 | L70 | NVIDIA |
| `grok_mini` | `xai/grok-3-mini-fast-beta` | — | 1 | GRK | xAI |
| `deepseek_v3` | `nvidia_nim/deepseek-ai/deepseek-v3.2` | 685B MoE | 2 | DS | NVIDIA |
| `sonnet` | `anthropic/claude-sonnet-4-5-20250929` | — | 3 | SON | Anthropic |

### Backup Models (from NVIDIA Catalog)

| Alias | litellm ID | Use If |
|-------|-----------|--------|
| `nemotron_9b` | `nvidia_nim/nvidia/nvidia-nemotron-nano-9b-v2` | Llama 8B fails |
| `mistral_24b` | `nvidia_nim/mistralai/mistral-small-24b-instruct` | QwQ fails |
| `nemotron_49b` | `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5` | Llama 70B fails |
| `ds_terminus` | `nvidia_nim/deepseek-ai/deepseek-v3.1-terminus` | DS V3.2 fails |
| `qwen3_235b` | `nvidia_nim/qwen/qwen3-235b-a22b` | Alternative Tier 2 |
| `gemini_25_flash` | `gemini/gemini-2.5-flash` | Need paid mid-range |

### Tier Composition

```
TIER 0 — 3 parallel voters (bulk verification)
├── gemini/gemini-2.0-flash               [GF]  Google   $0.10/$0.40
├── nvidia_nim/meta/llama-3.1-8b-instruct [L8]  NVIDIA   free tier
└── nvidia_nim/qwen/qwq-32b              [QwQ] NVIDIA   free tier

TIER 1 — 2 parallel voters (escalation)
├── nvidia_nim/meta/llama-3.3-70b-instruct [L70] NVIDIA  free tier
└── xai/grok-3-mini-fast-beta              [GRK] xAI     $0.30/$0.50

TIER 2 — 1 tiebreaker
└── nvidia_nim/deepseek-ai/deepseek-v3.2   [DS]  NVIDIA  free tier

TIER 3 — 1 frontier (absolute last resort)
└── anthropic/claude-sonnet-4-5-20250929   [SON] Anthropic $3/$15
```

**Design rationale:**
- Provider diversity in every tier (NVIDIA + Google + xAI + Anthropic)
- Architecture diversity (8B dense, 32B reasoning, 70B dense, 685B MoE)
- NVIDIA free tier for Tiers 0-2 means nearly zero marginal cost
- Claude Sonnet only as fallback when all else fails

---

## Part 3: Voting Protocol

### Flow

```
Round 1: Tier 0 — 3 cheap models in parallel
  GF + L8 + QwQ → vote
  2/3 agree? → ACCEPT                        Cost: ~$0.001
  Any says "contradicted"? → ESCALATE always
  No majority? → ESCALATE

Round 2: Tier 1 — 2 mid-range models in parallel
  L70 + GRK → vote
  Both agree? → ACCEPT                       Cost: ~$0.01
  Combined R1+R2 supermajority? → ACCEPT
  Still no? → ESCALATE

Round 3: Tier 2 — 1 premium model
  DS → verdict is final                      Cost: ~$0.02

Round 4: Tier 3 — only if Round 3 errors/cannot_verify
  SON → absolute final                       Cost: ~$0.25
```

### Consensus Rules

| Type | Condition | Confidence |
|------|-----------|------------|
| Unanimous | All agree | mean(confidences) + 0.05 |
| Supermajority | ≥2/3 agree | mean(agreeing) |
| Majority | >1/2 agree | mean(agreeing) - 0.03 |
| Escalate | No majority | — |

Special: "contradicted" from ANY model → always escalate.
"cannot_verify" votes are excluded (abstain).

### Data Models

```python
class ModelVote(BaseModel):
    model_name: str          # "Gemini 2.0 Flash"
    model_id: str            # "gemini/gemini-2.0-flash"
    abbreviation: str        # "GF"
    tier: int                # 0
    verdict: str             # "supported"
    confidence: float        # 0.85
    reasoning: str           # full text
    evidence_quotes: list[str]
    response_time_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float

class VotingRecord(BaseModel):
    votes: list[ModelVote]
    consensus_type: str       # "unanimous" | "supermajority" | "majority" | "tiebreaker"
    final_tier: int           # which tier resolved it
    escalation_path: list[int]  # [0] or [0, 1] or [0, 1, 2]
    agreement_ratio: float    # 1.0, 0.67, 0.60, etc.
```

---

## Part 4: Manuscript Viewer — Multi-Model UX

### 4.1 Design Philosophy

**Problem:** Each claim now has 3-7 model opinions. Showing all of this risks information overload — the user came to verify citations, not study AI model behavior.

**Solution: Progressive Disclosure with 4 layers.** Each layer requires a deliberate user action (click/expand) to reveal. Most users only need Layers 1-2.

### 4.2 The Four Layers

```
┌──────────────────────────────────────────────────────────┐
│ LAYER 1 — SURFACE (always visible, zero clicks)          │
│                                                          │
│ The manuscript text with colored inline highlights.      │
│ Each highlight has a tiny superscript badge:             │
│                                                          │
│ "...hydrogels reduce rejection rates⁽³/³⁾..."           │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                        │
│  (green bg = supported, badge = 3/3 models agree)        │
│                                                          │
│ Color = verdict. Badge = agreement. That's it.           │
└──────────────────────────────────────────────────────────┘
         │
         │ user clicks highlight
         ▼
┌──────────────────────────────────────────────────────────┐
│ LAYER 2 — SUMMARY (evidence panel, right side)           │
│                                                          │
│ ┌──────────────────────────────────────┐                 │
│ │  ● Supported  87%                    │                 │
│ │  ────────────────────────            │                 │
│ │  Unanimous • Tier 0 • 3 models      │                 │
│ │                                      │                 │
│ │  Jury:  🟢GF  🟢L8  🟢QwQ          │                 │
│ │                                      │                 │
│ │  "The source text explicitly states  │                 │
│ │  that hydrogel-based delivery        │                 │
│ │  systems create a localized          │                 │
│ │  immunosuppressive environment..."   │                 │
│ │                                      │                 │
│ │  Evidence from source:               │                 │
│ │  > "hydrogel-encapsulated tacrolimus │                 │
│ │    extended graft survival from      │                 │
│ │    8 to 45 days"                     │                 │
│ │                                      │                 │
│ │  ▸ Show model opinions (3)          │                 │
│ │  ▸ Verification details             │                 │
│ └──────────────────────────────────────┘                 │
│                                                          │
│ Key: the reasoning shown is from the BEST model          │
│ (highest confidence among agreeing models).              │
│ Users see ONE clear explanation, not three.              │
└──────────────────────────────────────────────────────────┘
         │
         │ user clicks "Show model opinions"
         ▼
┌──────────────────────────────────────────────────────────┐
│ LAYER 3 — MODEL DETAIL (accordion below summary)         │
│                                                          │
│ Each model as a collapsible card:                        │
│                                                          │
│ ┌─ 🟢 Gemini 2.0 Flash ──── Tier 0 ─────────────┐      │
│ │  Supported • 85%                                │      │
│ │                                                 │      │
│ │  "The source paper directly addresses this      │      │
│ │  claim on page 4, where the authors describe    │      │
│ │  hydrogel-encapsulated drug delivery reducing   │      │
│ │  rejection in murine models."                   │      │
│ │                                                 │      │
│ │  Evidence: "hydrogel-encapsulated tacrolimus     │      │
│ │  extended graft survival from 8 to 45 days"     │      │
│ │                                                 │      │
│ │  ⏱ 1.2s  •  📊 847 tokens  •  💰 $0.0003      │      │
│ └─────────────────────────────────────────────────┘      │
│                                                          │
│ ┌─ 🟢 Llama 3.1 8B ──────── Tier 0 ─────────────┐      │
│ │  Supported • 82%              (collapsed)       │      │
│ └─────────────────────────────────────────────────┘      │
│                                                          │
│ ┌─ 🟢 QwQ 32B ──────────── Tier 0 ──────────────┐      │
│ │  Supported • 88%              (collapsed)       │      │
│ └─────────────────────────────────────────────────┘      │
│                                                          │
│ Only the FIRST card (best model) is expanded by          │
│ default. Others are collapsed (click to expand).         │
└──────────────────────────────────────────────────────────┘
         │
         │ user clicks "Verification details"
         ▼
┌──────────────────────────────────────────────────────────┐
│ LAYER 4 — META (debug/power-user info)                   │
│                                                          │
│ Escalation Timeline (only if escalated):                 │
│ ┌────────────────────────────────────────────────┐       │
│ │ Round 1 (Tier 0)  →  Round 2 (Tier 1)         │       │
│ │ 🟢GF 🔴L8 🟡QwQ     🟡L70 🟡GRK              │       │
│ │ No majority          2/2: partial              │       │
│ │                      ✓ Resolved                │       │
│ └────────────────────────────────────────────────┘       │
│                                                          │
│ Cost: $0.0089 for this claim (5 model calls)             │
│                                                          │
│ ┌ Raw JSON ──────────────────────────────────┐           │
│ │ { "votes": [...], "consensus_type": ... }  │           │
│ └────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────┘
```

### 4.3 Jury Panel Component

The compact strip in Layer 2. Design rules:

**When unanimous (most common case):**
```
Jury:  🟢GF  🟢L8  🟢QwQ    ← simple, quiet
```
Small colored dots with 2-3 letter abbreviation. No extra detail. Clean.

**When there's disagreement (draws attention):**
```
Jury:  🟢GF  🔴L8  🟡QwQ    ⚠ 1 dissent
```
An amber warning badge appears. The dissenting model's dot draws the eye.

**When escalated (rare, interesting):**
```
Jury:  🟢GF 🔴L8 🟡QwQ  │  🟡L70 🟡GRK  → Partial
       ─── Tier 0 ───    │  ── Tier 1 ──
```
A vertical separator between rounds. Clear visual progression.

**Interaction:**
- Hover on any dot → tooltip: "Gemini 2.0 Flash: Supported (85%)"
- Click dot → scrolls to that model's detail card in Layer 3

**Colors (light mode / dark mode):**
- Supported: `#16a34a` / `#4ade80`
- Partial: `#d97706` / `#fbbf24`
- Not supported: `#dc2626` / `#f87171`
- Contradicted: `#991b1b` / `#ef4444` (darker red + pulse border)
- Cannot verify: `#6b7280` / `#9ca3af`

### 4.4 Consensus Badge

A pill-shaped badge in Layer 2, right after the confidence:

| Type | Badge | Color |
|------|-------|-------|
| Unanimous | `Unanimous ✓` | Green background |
| Supermajority | `2/3 Agree` | Light green |
| Majority | `Majority` | Amber |
| Tiebreaker | `Tiebreaker ⚖` | Blue |
| Escalated | `Escalated →` | Orange border |

### 4.5 Model Detail Card

```typescript
interface ModelDetailCardProps {
  vote: ModelVote;
  isExpanded: boolean;
  onToggle: () => void;
}
```

**Header (always visible):**
```
[●] Gemini 2.0 Flash          Tier 0    Supported 85%
```
- Colored dot matching verdict
- Model name
- Tier badge (small gray pill: "T0", "T1", "T2", "T3")
- Verdict + confidence

**Body (when expanded):**
- Reasoning text (full paragraph)
- Evidence quotes (indented, styled as blockquotes)
- Footer: `⏱ 1.2s  •  📊 847 tokens  •  💰 $0.0003`

**Design rule:** First card (highest confidence agreeing model) is expanded. All others collapsed. This prevents wall-of-text on expand.

### 4.6 Escalation Timeline

Only rendered when `escalation_path.length > 1`.

**Desktop (horizontal):**
```
 Round 1            →         Round 2           →  Resolved
┌─────────────────┐    ┌─────────────────┐
│ 🟢GF 🔴L8 🟡QwQ│───▶│ 🟡L70  🟡GRK   │───▶ ✓ Partial (78%)
│ No majority     │    │ 2/2 agree       │
└─────────────────┘    └─────────────────┘
```

**Mobile (vertical):**
```
Round 1 (Tier 0)
  🟢GF 🔴L8 🟡QwQ
  No majority
       │
       ▼
Round 2 (Tier 1)
  🟡L70 🟡GRK
  2/2 agree
       │
       ▼
✓ Resolved: Partial (78%)
```

### 4.7 Results Page Cost Card

New card on the results overview page:

```
┌─ Verification Cost ──────────────────────────┐
│                                              │
│  Total: $4.43     Models: 7     Calls: 1,905 │
│                                              │
│  ██████████████████░░  93% resolved Tier 0   │
│  ████░░░░░░░░░░░░░░░░   5% escalated Tier 1  │
│  ██░░░░░░░░░░░░░░░░░░   1.5% Tier 2          │
│  ░░░░░░░░░░░░░░░░░░░░   0.5% Tier 3          │
│                                              │
│  By model:                                   │
│  GF  $0.32  │ L8  $0.00  │ QwQ $0.00        │
│  L70 $0.00  │ GRK $0.28  │ DS  $0.00        │
│  SON $1.25  │                                │
└──────────────────────────────────────────────┘
```

### 4.8 Pipeline Tracker (during verification)

Real-time updates:
```
Verifying claims...  245/500  ━━━━━━━━━━░░░░░  49%
Cost: $1.82  •  Tier 0: 380 ✓  •  Escalated: 12  •  Tier 2: 3
```

### 4.9 UX Rules Summary

1. **Default = minimal.** Layer 1-2 only. No auto-expansion.
2. **Best reasoning wins.** Layer 2 shows ONE explanation (highest confidence agreeing model), not all three.
3. **Disagreement is interesting.** When models disagree, draw visual attention (warning badge, colored border).
4. **Agreement is boring.** When all agree, keep it quiet (simple "3/3 ✓").
5. **Cost is secondary.** Show in Layer 4 and results page, not cluttering the evidence panel.
6. **Abbreviations are consistent.** Same 2-3 letter codes everywhere (GF, L8, QwQ, L70, GRK, DS, SON).
7. **Lazy load Layer 3-4 data.** Don't bloat the initial manuscript load.

---

## Part 5: PDF Resolution Fixes

### 5.1 OCR Fallback (scanned PDFs)
- pytesseract + Pillow for image-based pages
- Detection: page has <50 chars text → try OCR at 300 DPI
- Graceful degradation if pytesseract not installed

### 5.2 Supplement Detection
- Score PDF URLs: penalize `_si_`, `supplement`, `supporting`
- Post-download: check first page text for supplement indicators
- If supplement, try next URL

### 5.3 Paywalled Papers
- Abstract-only verification (cap confidence at 0.60)
- Unpaywall API integration (legal OA versions)
- PubMed Central fallback
- User prompt to upload

### 5.4 Wrong Reference Mapping
- Handled by Feature 08 deterministic mapper
- Additional: topic coherence check before verification

---

## Part 6: Cost Projection

### 122-reference manuscript

| Task | Calls | Est. Cost |
|------|-------|-----------|
| Scope resolution (GF only) | 150 | $0.15 |
| Verification Tier 0 (3×) | 1,500 | ~$0.75 |
| Verification Tier 1 (2×) | 200 | ~$0.30 |
| Verification Tier 2 (1×) | 20 | ~$0.00 |
| Verification Tier 3 (1×) | 5 | ~$1.25 |
| Missing citations (GF) | 30 | $0.03 |
| **Total** | **~1,905** | **~$2.48** |

**Cost reduction: ~99% ($208 → $2.48)**
(NVIDIA free tier makes Tiers 0-2 nearly free. Cost dominated by rare Tier 3 calls.)

---

## Part 7: API Changes

### Evidence endpoint adds voting record

`GET /api/sessions/{id}/evidence/{claim_id}`
```json
{
  "voting_record": {
    "votes": [{ "model_name": "...", "abbreviation": "GF", ... }],
    "consensus_type": "unanimous",
    "final_tier": 0,
    "escalation_path": [0],
    "agreement_ratio": 1.0
  }
}
```

### Manuscript endpoint adds lightweight summary per claim

`GET /api/sessions/{id}/manuscript` adds per-claim:
```json
{
  "consensus_type": "unanimous",
  "final_tier": 0,
  "model_count": 3,
  "agreeing_count": 3
}
```

### Session status adds cost

`GET /api/sessions/{id}/status` adds:
```json
{
  "cost": {
    "total_usd": 4.43,
    "calls": 1905,
    "by_tier": {"0": 1500, "1": 200, "2": 20, "3": 5}
  }
}
```
