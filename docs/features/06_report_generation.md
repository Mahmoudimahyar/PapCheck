# Feature: Verification Report Generation

**Module:** `src/refcheck/stages/generate_report/`
**Version:** MVP (existence report), V1 (full verification report), V2 (interactive)
**Dependencies:** All previous stages
**User Intervention:** IP-7 (accept/override/re-verify, V2)

---

## Purpose

Generate a structured DOCX verification report that is actionable, layered by severity, and includes evidence trails for every judgment. Researchers should be able to submit this alongside their manuscript.

## Output Format

A DOCX file downloaded from the web UI.

### MVP Report (Existence Report)
1. **Summary** — Total references, found count, not-found count, metadata issues
2. **Reference Status Table** — Each reference with: found/not found, source (PubMed/CrossRef/etc), PDF status (uploaded/OA/paywalled/missing), metadata issues
3. **Not Found References** — Detail on what was searched and what failed
4. **Metadata Issues** — DOI mismatches, year discrepancies, potential duplicates

### V1 Report (Full Verification Report)
1. **Executive Summary** — Total checked, verified (green), minor issues (yellow), major issues (red), cannot verify (gray), retracted (if any)
2. **Critical Findings** — References with "not_supported" or "contradicted" verdicts. Each entry: manuscript text, claim, verdict, evidence from source, LLM reasoning, confidence score
3. **Minor Issues** — "Partially_supported" verdicts, version mismatches, weak citations
4. **Verified References** — All "supported" verdicts with brief confirmation
5. **Unverifiable References** — Papers not obtained, insufficient source text
6. **Methodology Note** — LLMs used, verification tier per result, confidence calibration, full text vs abstract coverage

### V2 Additions
- User override logging (what was changed and why)
- Interactive preview in web UI with accept/override per finding
- Report regeneration after corrections
- Report diff between versions (V3)

## Report Design (Biomedical Audience)

- Clean, professional formatting suitable for submission to journal editors
- Color coding: green (supported), red (contradicted/not supported), amber (partial/uncertain), gray (unverifiable)
- Tables for structured data, prose for explanations
- Methodology section for transparency (which AI models, what confidence means)
- Page numbers, table of contents for reports with 100+ references

## Tests & Acceptance Criteria

| Test ID | Test | Pass Criteria |
|---------|------|---------------|
| RG-01 | MVP report from sample data | Valid DOCX produced, opens in Word/LibreOffice |
| RG-02 | Summary counts correct | Numbers in summary match underlying data |
| RG-03 | Color coding present (V1) | Red/yellow/green styling in document |
| RG-04 | Empty results handled | Report generated even if 0 issues found |
| RG-05 | Large report (150+ refs) | Generates in <60 seconds, file < 10MB |
| RG-06 | Report download via API | GET endpoint returns valid DOCX with correct headers |
| RG-07 | Methodology note accurate | Models listed match what was actually used |

### Quality Metrics

| Metric | Target |
|--------|--------|
| Report generation success rate | 100% (never crash) |
| User comprehension | Action items identifiable within 2 minutes |
| Summary statistics accuracy | 100% match with underlying data |
| Download reliability | 100% of generated reports downloadable |
