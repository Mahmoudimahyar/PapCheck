# RefCheck AI — Frontend Specification

**Stack:** Next.js 15 (App Router) · shadcn/ui · Tailwind CSS v4 · Recharts · TanStack Query · react-hook-form + Zod
**Aesthetic:** Scientific/academic — clean, muted, trustworthy. Think journal website, not SaaS landing page.

---

## Architecture

```
frontend/
├── src/
│   ├── app/                          # Next.js App Router
│   │   ├── layout.tsx                # Root layout (theme provider, fonts)
│   │   ├── page.tsx                  # Upload page (home)
│   │   ├── verify/[sessionId]/
│   │   │   ├── page.tsx              # Pipeline progress page
│   │   │   ├── review/page.tsx       # Reference review & matching
│   │   │   ├── results/page.tsx      # Verification results dashboard
│   │   │   └── report/page.tsx       # Report preview & download
│   │   └── globals.css               # Tailwind base styles
│   ├── components/
│   │   ├── ui/                       # shadcn auto-generated (DO NOT EDIT)
│   │   └── refcheck/                 # Custom components
│   │       ├── upload-zone.tsx
│   │       ├── reference-table.tsx
│   │       ├── pdf-match-card.tsx
│   │       ├── gap-dashboard.tsx
│   │       ├── pipeline-tracker.tsx
│   │       ├── claim-review-card.tsx      # V1
│   │       ├── verification-badge.tsx     # V1
│   │       ├── results-chart.tsx          # V1
│   │       ├── results-table.tsx          # V1
│   │       ├── human-review-modal.tsx     # V2
│   │       └── report-preview.tsx         # V2
│   ├── lib/
│   │   ├── api.ts                    # API client (fetch wrapper)
│   │   ├── sse.ts                    # SSE connection manager
│   │   ├── types.ts                  # TypeScript types (mirror Pydantic models)
│   │   └── utils.ts                  # Formatting helpers (cn, date, etc.)
│   └── hooks/
│       ├── use-pipeline-sse.ts       # SSE hook for pipeline progress
│       ├── use-session.ts            # Session state management
│       └── use-theme.ts              # Light/dark mode
├── public/                           # Static assets
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── components.json                   # shadcn configuration
```

---

## Design System

### Colors (CSS variables in globals.css)

```
Light mode:
  --background:    #FAFAF9 (warm off-white)
  --foreground:    #1C1917 (near-black)
  --card:          #FFFFFF
  --border:        #E7E5E4
  --muted:         #78716C (warm gray for secondary text)

  --success:       #16A34A (green — supported)
  --warning:       #D97706 (amber — partially supported / uncertain)
  --destructive:   #DC2626 (red — contradicted / not supported)
  --unverifiable:  #9CA3AF (gray — cannot verify)
  --info:          #2563EB (blue — informational)

Dark mode:
  Same semantic colors with adjusted lightness for dark backgrounds.
  Use shadcn's built-in dark mode CSS variable system.
```

### Typography

```
Font stack:
  Headings: Inter (clean, scientific feel)
  Body: Inter
  Monospace: JetBrains Mono (for DOIs, IDs, code)

Scale:
  Page title:     text-2xl font-semibold
  Section header: text-lg font-medium
  Body:           text-sm (default)
  Caption/meta:   text-xs text-muted-foreground
```

### Component Library (shadcn/ui)

Install these components via `npx shadcn@latest add [name]`:

**MVP:**
- button, card, badge, table, input, label, separator
- dialog, dropdown-menu, tooltip, toast
- progress, tabs, scroll-area
- sheet (mobile sidebar)
- toggle (dark mode)

**V1 additions:**
- accordion (expandable reference rows)
- collapsible (report sections)
- select (filter dropdowns)
- slider (confidence threshold filter)

**V2 additions:**
- alert-dialog (human review confirmation)
- command (keyboard shortcuts)
- radio-group (Tier 3 verdict selection)

---

## Pages — Detailed Specifications

### Page 1: Upload (MVP)

**Route:** `/` (home page)
**Purpose:** Researcher uploads manuscript and PDFs.

**Layout:**
```
┌─────────────────────────────────────────────┐
│  RefCheck AI                    [🌙 toggle]  │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │                                     │    │
│  │   📄 Drop your manuscript here      │    │
│  │      (.docx files only)             │    │
│  │      [Browse files]                 │    │
│  │                                     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │                                     │    │
│  │   📁 Drop reference PDFs here       │    │
│  │      (optional — we'll try to       │    │
│  │       find papers automatically)    │    │
│  │      [Browse files]                 │    │
│  │                                     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Uploaded PDFs: 47 files                    │
│  ┌──────────────────────────────────────┐   │
│  │ Smith2020_DrugX.pdf          ✓ Ready │   │
│  │ Jones_etal_2019.pdf          ✓ Ready │   │
│  │ ...                                  │   │
│  └──────────────────────────────────────┘   │
│                                             │
│         [ Start Verification → ]            │
│                                             │
└─────────────────────────────────────────────┘
```

**Behavior:**
- Manuscript zone accepts exactly one `.docx` file (replace on re-drop)
- PDF zone accepts multiple files, drag-drop or browse
- File list shows name + status badge (Ready / Error / Duplicate)
- "Start Verification" disabled until manuscript uploaded
- On click: POST to `/api/sessions` → redirect to `/verify/[sessionId]`

**Component map:**
- `upload-zone.tsx`: Reusable drop zone (wraps shadcn `Card`)
- File list: shadcn `Table` with `Badge` per row

---

### Page 2: Pipeline Progress (MVP)

**Route:** `/verify/[sessionId]`
**Purpose:** Show real-time pipeline progress via SSE.

**Layout:**
```
┌──────────────────────────────────────────────┐
│  RefCheck AI    Session #abc123   [🌙]       │
├──────────────────────────────────────────────┤
│                                              │
│  Pipeline Progress                           │
│                                              │
│  ✅ 1. Parse Manuscript         12 sec       │
│     └ 142 references extracted               │
│                                              │
│  ✅ 2. Match PDFs               8 sec        │
│     └ 47/142 matched (3 need confirmation)   │
│                                              │
│  🔄 3. Resolve Gaps             ...          │
│     └ 34/95 resolved  ████████░░ 36%        │
│     └ 12 open-access downloaded              │
│                                              │
│  ○  4. Generate Report          waiting      │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  ⚠ 3 PDFs need your confirmation       │  │
│  │  [Review matches →]                    │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
```

**Behavior:**
- Connects to SSE endpoint on mount: `GET /api/sessions/{id}/events`
- Each stage shows: status icon (✅🔄○❌), name, elapsed time, sub-status
- Progress bars for stages processing multiple items
- Intervention prompts appear inline when pipeline pauses for user input
- "Review matches" navigates to review page; pipeline continues for non-blocked stages
- When complete: auto-navigates to results (V1) or report download (MVP)

**SSE event format:**
```typescript
type PipelineEvent = {
  stage: 1 | 2 | 3 | 4 | 5 | 6;
  status: "running" | "complete" | "error" | "needs_input";
  progress?: { current: number; total: number };
  message?: string;
  elapsed_seconds?: number;
}
```

**Component map:**
- `pipeline-tracker.tsx`: Main component, renders stage list
- Each stage row is a sub-component with status icon logic
- Intervention banners: shadcn `Card` with `variant="outline"` + amber border

---

### Page 3: Reference Review & Matching (MVP)

**Route:** `/verify/[sessionId]/review`
**Purpose:** Review extracted references, confirm PDF matches, upload missing papers.

**Layout:**
```
┌──────────────────────────────────────────────────────────────┐
│  Tabs: [All References] [Needs Confirmation] [Unmatched]     │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Search: [________________]    Filter: [Status ▾] [Source ▾] │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ # │ Reference              │ PDF Status  │ Source │ Act. ││
│  ├───┼────────────────────────┼─────────────┼────────┼──────┤│
│  │ 1 │ Smith et al. (2020)    │ ✅ Matched  │ Upload │      ││
│  │   │ "Drug X reduces..."    │ DOI match   │        │      ││
│  ├───┼────────────────────────┼─────────────┼────────┼──────┤│
│  │ 2 │ Jones et al. (2019)    │ ⚠ Confirm?  │ Upload │[Y][N]││
│  │   │ "CRISPR protocol..."   │ 82% title   │        │      ││
│  │   │ → Matched: Jones2019_preprint.pdf                    ││
│  │   │   (possible version mismatch: preprint vs published) ││
│  ├───┼────────────────────────┼─────────────┼────────┼──────┤│
│  │ 3 │ Wang et al. (2021)     │ 📥 OA Found │ PMC    │      ││
│  │   │ "Biomarker panel..."   │ Downloading │        │      ││
│  ├───┼────────────────────────┼─────────────┼────────┼──────┤│
│  │ 4 │ Brown & Lee (2018)     │ 🔒 Paywalled│ CrossRef│[📎] ││
│  │   │ "Long-term outcomes.." │ doi.org link │        │      ││
│  ├───┼────────────────────────┼─────────────┼────────┼──────┤│
│  │ 5 │ ???                    │ ❌ Not Found │ —      │[✏️]  ││
│  │   │ "Unclear reference..." │ No DB match │        │      ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  Summary: 142 refs │ 47 matched │ 3 confirm │ 34 OA │       │
│           12 paywalled │ 5 not found │ 41 resolving         │
│                                                              │
│         [ Continue → ]                                       │
└──────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Table sortable by any column
- Tab filters: All (default), Needs Confirmation, Unmatched
- Confirm/reject buttons for uncertain matches
- Upload button for paywalled papers (opens file picker)
- Edit button for not-found references (correct metadata, trigger re-search)
- Summary bar updates in real-time as user resolves items
- "Continue" proceeds to report (MVP) or verification (V1+)

---

### Page 4: Results Dashboard (V1)

**Route:** `/verify/[sessionId]/results`
**Purpose:** Show verification results with filtering, sorting, and evidence drill-down.

**Layout:**
```
┌──────────────────────────────────────────────────────────┐
│  Verification Results — manuscript.docx                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │  112   │ │   18   │ │    5   │ │    2   │ │    5   ││
│  │Verified│ │Partial │ │Not Sup.│ │Contrad.│ │Can't   ││
│  │  🟢    │ │  🟡    │ │  🔴    │ │  🔴    │ │  ⚪    ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  [Recharts stacked bar: verdict distribution]    │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  Filter: [Verdict ▾] [Priority ▾] [Confidence ▾]        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │ [7] Smith 2020 │ Contradicted │ 🔴 0.91 │ High  │    │
│  │ ▼ Expand                                         │    │
│  │ ┌──────────────────────────────────────────────┐ │    │
│  │ │ Manuscript says: "Drug X reduced mortality    │ │    │
│  │ │ by 30% (Smith et al., 2020)"                 │ │    │
│  │ │                                               │ │    │
│  │ │ Source says: "Drug X was associated with a    │ │    │
│  │ │ non-significant 12% reduction (p=0.08)"      │ │    │
│  │ │                                               │ │    │
│  │ │ Verdict: CONTRADICTED                         │ │    │
│  │ │ The manuscript claims a 30% reduction but     │ │    │
│  │ │ the source reports 12% and non-significant.   │ │    │
│  │ │                                               │ │    │
│  │ │ Confidence: 0.91 │ Tier: 1 │ Full text       │ │    │
│  │ └──────────────────────────────────────────────┘ │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│         [ Download Report ]                              │
└──────────────────────────────────────────────────────────┘
```

---

### Page 5: Report Preview & Download (MVP basic, V2 interactive)

**Route:** `/verify/[sessionId]/report`
**Purpose:** Preview the generated report and download as DOCX.

**MVP:** Simple download button + basic summary stats.
**V2:** Full interactive preview with accept/override per finding.

---

## SSE Implementation

### Frontend hook: `use-pipeline-sse.ts`

```typescript
export function usePipelineSSE(sessionId: string) {
  const [stages, setStages] = useState<StageStatus[]>(initialStages);
  const [interventions, setInterventions] = useState<Intervention[]>([]);

  useEffect(() => {
    const eventSource = new EventSource(
      `${API_BASE}/api/sessions/${sessionId}/events`
    );

    eventSource.onmessage = (event) => {
      const data: PipelineEvent = JSON.parse(event.data);
      // Update stage status
      setStages(prev => updateStage(prev, data));
      // Surface intervention requests
      if (data.status === "needs_input") {
        setInterventions(prev => [...prev, data.intervention!]);
      }
    };

    eventSource.onerror = () => {
      // Reconnect logic with backoff
    };

    return () => eventSource.close();
  }, [sessionId]);

  return { stages, interventions };
}
```

### Backend endpoint: `api/routes/events.py`

```python
@router.get("/api/sessions/{session_id}/events")
async def stream_events(session_id: str):
    async def event_generator():
        async for event in pipeline_events(session_id):
            yield f"data: {event.model_dump_json()}\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

---

## API Client Pattern

```typescript
// lib/api.ts — thin wrapper, no abstraction layers
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export async function createSession(manuscript: File, pdfs: File[]): Promise<Session> {
  const formData = new FormData();
  formData.append("manuscript", manuscript);
  pdfs.forEach(pdf => formData.append("pdfs", pdf));

  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function getSession(id: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

// Pattern: one function per endpoint, typed inputs and outputs, no class wrappers
```

---

## State Management

**No Redux. No Zustand. No global state library.**

State lives in three places:
1. **Server state:** TanStack Query (`useQuery`, `useMutation`) — handles caching, refetching, optimistic updates
2. **URL state:** Next.js route params and search params — session ID, active tab, filters
3. **Local component state:** React `useState` — form inputs, expanded rows, modal open/close

**Why this works for RefCheck:** The app is fundamentally a read-heavy pipeline viewer. Almost all state comes from the server. The only write operations are: upload files, confirm matches, override verdicts. TanStack Query handles all of these.

---

## Responsive Design

MVP targets desktop (1024px+). V3 adds mobile.

```
Breakpoints (Tailwind defaults):
  sm:  640px   (not used in MVP)
  md:  768px   (tablet — stack cards vertically)
  lg:  1024px  (desktop — default layout)
  xl:  1280px  (wide desktop — wider tables)
```

---

## Dark Mode

Uses shadcn's `next-themes` integration:

```typescript
// layout.tsx
import { ThemeProvider } from "next-themes";

export default function RootLayout({ children }) {
  return (
    <html suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

Toggle in header uses shadcn's `Toggle` or `DropdownMenu` with sun/moon icons.

---

## Performance Targets

| Metric | Target |
|--------|--------|
| First Contentful Paint | < 1.5s |
| Time to Interactive | < 3s |
| Reference table render (200 rows) | < 500ms |
| SSE reconnection | < 2s after disconnect |
| Bundle size (initial) | < 200KB gzipped |
