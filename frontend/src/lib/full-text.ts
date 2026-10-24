/** Is a reference's full text usable, and where could a free legal copy come from? */

import type { Reference, SourceIssue, SourceIssueKind } from "./types";

/** Attached PDFs that cannot stand for the cited article (backend: source_issues.py). */
const UNUSABLE_PDF_KINDS: ReadonlySet<SourceIssueKind> = new Set([
  "wrong_pdf", "scanned_pdf", "supplement_pdf", "metadata_only_pdf",
]);

/** Cannot-verify reasons that a better full text could fix. */
export const FULL_TEXT_REASONS: ReadonlySet<string> = new Set([
  "no_pdf_paywalled", "no_pdf_not_found", "pdf_metadata_only", "pdf_supplement",
  "pdf_scanned", "reference_mismatch", "abstract_insufficient",
]);

/** The attached PDF is the wrong paper, a scan, a supplement or a metadata page. */
export function hasBadPdf(ref: Reference, issues: SourceIssue[] = []): boolean {
  if (!ref.pdf_path) return false;
  return ref.identity_status === "mismatch" || issues.some((i) => UNUSABLE_PDF_KINDS.has(i.kind));
}

export function hasUsableFullText(ref: Reference, issues: SourceIssue[] = []): boolean {
  return !!ref.pdf_path && !hasBadPdf(ref, issues);
}

export type FullTextHint =
  | { kind: "free"; url: string; pdfUrl: string | null; host: string; detail: string }
  | { kind: "paywalled"; doiUrl: string | null }
  | { kind: "unchecked"; doiUrl: string | null };

const LICENCE_SPECIAL: Record<string, string> = {
  "implied-oa": "free to read, no licence",
  "other-oa": "other open licence",
  publisher: "publisher licence",
};

/** "cc-by-nc-nd" -> "CC BY-NC-ND". */
export function formatLicence(licence: string | null | undefined): string {
  if (!licence) return "";
  const key = licence.trim().toLowerCase();
  if (LICENCE_SPECIAL[key]) return LICENCE_SPECIAL[key];
  if (key.startsWith("cc-")) {
    const parts = key.slice(3).split("-");
    if (parts[0] === "0") return "CC0";
    return `CC ${parts.join("-").toUpperCase()}`;
  }
  return licence;
}

const VERSION_LABELS: Record<string, string> = {
  publishedversion: "published version",
  acceptedversion: "accepted manuscript",
  submittedversion: "preprint",
};

export function formatVersion(version: string | null | undefined): string {
  if (!version) return "";
  return VERSION_LABELS[version.toLowerCase()] ?? version;
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

export function doiUrl(ref: Reference): string | null {
  return ref.doi ? `https://doi.org/${ref.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")}` : null;
}

/** Free copy, checked-and-paywalled, or not checked yet (never conflate the last two). */
export function fullTextHint(ref: Reference): FullTextHint {
  const url = ref.oa_url || ref.oa_pdf_url;
  if (url) {
    const detail = [formatLicence(ref.oa_license), formatVersion(ref.oa_version)].filter(Boolean).join(", ");
    const pdfUrl = ref.oa_pdf_url && ref.oa_pdf_url !== url ? ref.oa_pdf_url : null;
    return { kind: "free", url, pdfUrl, host: hostOf(url), detail };
  }
  if (ref.oa_status) return { kind: "paywalled", doiUrl: doiUrl(ref) };
  return { kind: "unchecked", doiUrl: doiUrl(ref) };
}
