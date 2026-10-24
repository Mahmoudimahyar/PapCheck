"""Chat message construction with explicit prompt-cache breakpoints.

A caller supplies a stable prefix either as a system template (rendered into
a system block) or by placing ``CACHE_BREAKPOINT`` on its own line inside the
user template: everything before the marker is the cacheable prefix.

Anthropic needs an explicit ``cache_control`` on the stable block (litellm's
top-level cache_control lands on the last, per-call block and never hits).
OpenAI caches identical prefixes automatically, so markers are just removed.
"""

CACHE_BREAKPOINT = "<<<CACHE_BREAKPOINT>>>"
_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}
_MAX_ANTHROPIC_BREAKPOINTS = 4

Message = dict[str, object]


def _blocks(parts: list[str], budget: int) -> tuple[list[dict[str, object]], int]:
    """Text blocks; every block but the last gets a cache breakpoint."""
    blocks: list[dict[str, object]] = []
    for index, part in enumerate(parts):
        block: dict[str, object] = {"type": "text", "text": part}
        if index < len(parts) - 1 and budget > 0:
            block["cache_control"] = dict(_EPHEMERAL)
            budget -= 1
        blocks.append(block)
    return blocks, budget


def build_messages(user_text: str, system_text: str | None, provider: str) -> list[Message]:
    """Messages for litellm.completion with provider-appropriate caching."""
    user_parts = [p for p in user_text.split(CACHE_BREAKPOINT) if p.strip()] or [""]
    system = system_text.replace(CACHE_BREAKPOINT, "") if system_text else None
    if provider != "anthropic":
        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": "".join(user_parts)})
        return messages

    budget = _MAX_ANTHROPIC_BREAKPOINTS
    messages = []
    if system:
        messages.append({
            "role": "system",
            "content": [{"type": "text", "text": system, "cache_control": dict(_EPHEMERAL)}],
        })
        budget -= 1
    if len(user_parts) == 1:
        messages.append({"role": "user", "content": user_parts[0]})
    else:
        content, _ = _blocks(user_parts, budget)
        messages.append({"role": "user", "content": content})
    return messages


def add_correction(messages: list[Message], reply: str, correction: str) -> list[Message]:
    """Append the invalid reply and a correction request for a retry."""
    return [
        *messages,
        {"role": "assistant", "content": reply or "(empty reply)"},
        {"role": "user", "content": correction},
    ]
