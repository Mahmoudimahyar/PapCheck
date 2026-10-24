"""Name the cascade layer behind each ``model_reasoning`` entry of a stored result.

``model_reasoning`` holds one entry per layer in ``layer_path`` order (screen
first when it ran). Results stored before V5 have no ``layer_path``; their
layer is recovered from the display prefix ("Verifier · …", "Confirm · …").
Shared by the report and the results API (which imports it from here, since
stages may not import from the API).
"""

from refcheck.models.verification import ModelReasoning, VerificationResult

SCREEN_VERDICTS = frozenset({"likely_supported", "possible_problem", "screen_inconclusive"})
# Every verifier pass (standard, expanded evidence, V5.4 evidence re-check): the last one ran
# is the verifier's final view.
VERIFIER_LAYERS: tuple[str, ...] = ("verifier", "verifier_expanded", "verifier_recheck")

_DISPLAY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("verifier (expanded)", "verifier_expanded"),
    ("verifier (evidence re-check)", "verifier_recheck"),
    ("verifier", "verifier"),
    ("judge", "judge"),
    ("confirm", "confirm"),
    ("element check (co-cited)", "adjudicate_cocited"),  # before its shorter prefix
    ("element check (claim slots)", "adjudicate_slots"),  # V5.7 #2, same reason
    ("slot probe", "slot_probe"),  # V5.7 #15 (experimental)
    ("element check", "adjudicate"),
    ("rule check", "post_rules"),  # V5.6 deterministic outcome rules
    ("decisions api", "screen"),
)


def _layer_from_display(entry: ModelReasoning) -> str:
    display = entry.model_display.strip().lower()
    for prefix, layer in _DISPLAY_PREFIXES:
        if display.startswith(prefix):
            return layer
    return "screen" if entry.verdict in SCREEN_VERDICTS else ""


def layer_names(v: VerificationResult) -> list[str]:
    """Layer name for each ``model_reasoning`` entry ("" for legacy entries)."""
    if v.layer_path and len(v.layer_path) == len(v.model_reasoning):
        return list(v.layer_path)
    return [_layer_from_display(entry) for entry in v.model_reasoning]


def last_entry(v: VerificationResult, *layers: str) -> ModelReasoning | None:
    """The last trace entry produced by one of ``layers`` (None if none ran)."""
    found = [entry for name, entry in zip(layer_names(v), v.model_reasoning, strict=True)
             if name in layers]
    return found[-1] if found else None
