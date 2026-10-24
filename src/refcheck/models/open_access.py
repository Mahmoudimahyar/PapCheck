"""Free-full-text hint of a reference (OpenAlex metadata; nothing is downloaded).

The resolve stage looks the hint up for references without a usable full text
(no PDF, another paper, supplement, scan) and the refresh endpoint for any one
reference. It tells the user where a legal free copy may be (``oa_url``, a
direct ``oa_pdf_url``), under which licence and which version, so they can
fetch and upload it themselves. ``Reference`` has no hint fields yet, so a
hinted reference travels as ``ReferenceWithAccess`` (a ``Reference`` subclass)
from the resolve stage to the database and from the database to the API.
"""

from pydantic import BaseModel

from refcheck.models.reference import Reference

OA_FIELDS: tuple[str, ...] = ("oa_status", "oa_url", "oa_pdf_url", "oa_license", "oa_version")


class OpenAccessHint(BaseModel):
    """Open-access status of a work (OpenAlex ``open_access`` + ``best_oa_location``)."""

    oa_status: str | None = None  # gold | green | hybrid | bronze | diamond | closed
    oa_url: str | None = None  # best free landing page (or PDF) URL
    oa_pdf_url: str | None = None  # direct PDF link of the best location, if any
    oa_license: str | None = None  # e.g. "cc-by", "cc-by-nc-nd"
    oa_version: str | None = None  # publishedVersion | acceptedVersion | submittedVersion
    pmc_id: str | None = None  # "PMC1234567" when OpenAlex knows a PMC copy

    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in OA_FIELDS)


class ReferenceWithAccess(Reference):
    """A reference plus its free-full-text hint (module doc)."""

    oa_status: str | None = None
    oa_url: str | None = None
    oa_pdf_url: str | None = None
    oa_license: str | None = None
    oa_version: str | None = None


def access_hint_of(ref: Reference) -> OpenAccessHint:
    """The hint a reference carries (empty for a plain ``Reference``)."""
    if not isinstance(ref, ReferenceWithAccess):
        return OpenAccessHint()
    return OpenAccessHint(**{name: getattr(ref, name) for name in OA_FIELDS})


def with_access_hint(ref: Reference, hint: OpenAccessHint) -> ReferenceWithAccess:
    """Copy of `ref` carrying `hint`; a PMC id fills an empty ``pmc_id``."""
    data = ref.model_dump()
    data.update({name: getattr(hint, name) for name in OA_FIELDS})
    if hint.pmc_id and not ref.pmc_id:
        data["pmc_id"] = hint.pmc_id
    return ReferenceWithAccess.model_validate(data)
