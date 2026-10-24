"""A reference listed twice is verified with the source of its first entry.

Parsing flags the second entry of a duplicated reference (``duplicate_of``,
same DOI or near-identical title) and citation mapping keeps "Wang et al.,
2024b" on that entry so the report can show the duplicate. PDF matching gives
a file to only one of the two entries, so without this the duplicate's claims
would be checked against its abstract alone (or not at all) although the
paper's full text is attached.
"""

from refcheck.models.reference import Reference


def inherit_duplicate_sources(references: list[Reference]) -> list[Reference]:
    """Copy the original entry's PDF (with its identity verdict) and abstract to
    duplicate entries that have none of their own; other references are unchanged."""
    by_id = {r.id: r for r in references}
    result: list[Reference] = []
    for ref in references:
        original = by_id.get(ref.duplicate_of) if ref.duplicate_of is not None else None
        if original is None or original.id == ref.id:
            result.append(ref)
            continue
        update: dict[str, object] = {}
        if ref.pdf_path is None and original.pdf_path is not None:
            update.update(pdf_path=original.pdf_path, pdf_source=original.pdf_source,
                          identity_status=original.identity_status)
        if not ref.abstract_text and original.abstract_text:
            update.update(abstract_text=original.abstract_text,
                          abstract_source=original.abstract_source)
        result.append(ref.model_copy(update=update) if update else ref)
    return result
