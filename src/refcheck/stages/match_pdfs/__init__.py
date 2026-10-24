"""Stage 3: PDF upload and smart matching (first pass + re-match before abstract fallback)."""

from refcheck.stages.match_pdfs.matcher import match_pdfs
from refcheck.stages.match_pdfs.rematch import rematch_or_keep, rematch_pdfs

__all__ = ["match_pdfs", "rematch_or_keep", "rematch_pdfs"]
