"""V5.7 #14 (experimental): give a subjectless cited_for its sentence subject.

In "In short, tents act as shelters (R1), tackling heavy rainfall (R2), ..." R2 is
cited for "tackling heavy rainfall"; the agent, "tents", sits in R1's clause, so a
verifier can re-read the claim as "heavy rainfall is a problem" and accept quotes
about something else entirely.
When a narrowed clause opens with a verb (a participle such as "tackling", or the
finite verb of a coordinated predicate: "... and increases infection risk"), the
sentence subject (the words before the first tensed verb, after a leading frame that
ends in a comma) is prepended: "tents ... tackling heavy rainfall".
No subject, a pronoun subject or a clause with a subject of its own -> unchanged.

Off by default (it changes the verifier input): REFCHECK_SUBJECT_PREPEND=on turns it
on, REFCHECK_V57_DISABLE=14 keeps it off.
"""

import os
import re
from typing import NamedTuple

from refcheck.stages.detect_citations.verb_heuristics import (
    AUXILIARIES,
    IRREGULAR_PAST,
    NOUN_TOO,
    VERB_ONLY,
    has_verb,
    words,
)

ENV = "REFCHECK_SUBJECT_PREPEND"
PROPOSAL = 14
JOINER = " ... "
_ON = frozenset({"on", "1", "true", "yes"})
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_FRAME_END = re.compile(r"[,;:]")
_MAX_SUBJECT_WORDS = 8
_LEADING_ADVERBS = frozenset({
    "also", "then", "thus", "thereby", "further", "subsequently", "therefore", "hence",
    "additionally", "often", "still", "even", "and", "but", "so", "however", "moreover",
    "indeed", "furthermore", "consequently", "finally", "first", "second",
})
_PRONOUNS = frozenset({
    "it", "they", "this", "these", "those", "that", "which", "we", "i", "he", "she",
    "there", "here", "such", "its", "their",
})
# -ing words that are prepositions or (biomedical) nouns, not participles
_ING_NOT_VERB = frozenset({
    "during", "including", "according", "regarding", "concerning", "following",
    "excluding", "considering", "notwithstanding", "pending", "nothing", "something",
    "anything", "everything", "signaling", "signalling", "binding", "bleeding", "coating",
    "loading", "folding", "processing", "sequencing", "screening", "imaging", "staining",
    "training", "setting", "funding", "finding", "findings", "meeting", "building",
    "understanding", "healing", "swelling", "scarring", "remodeling", "remodelling",
    "spring", "string", "ceiling", "morning", "evening",
})
_PREPOSITIONS = frozenset({"in", "of", "on", "at", "to", "for", "with", "by", "from"})


def subject_prepend_on() -> bool:
    """REFCHECK_SUBJECT_PREPEND=on and #14 not disabled (read on every call)."""
    from refcheck.stages.verify_claims.v57 import enabled  # lazy: no stage import cycle

    return os.getenv(ENV, "").strip().lower() in _ON and enabled(PROPOSAL)


class Subject(NamedTuple):
    text: str  # "hydrogels"
    verb: str  # its tensed verb, lower case ("act")


def with_subject(clause: str, sentence: str) -> str:
    """``clause`` with the sentence subject prepended when it has none of its own.

    ``sentence``: the citing sentence without citation markers.
    """
    first = _first_word(clause)
    if not verb_initial(clause):
        return clause
    subject = sentence_subject(sentence)
    if subject is None or clause.lower().startswith(subject.text.lower()):
        return clause
    if first in VERB_ONLY and _singular(subject.verb):
        return clause  # "X allows gels to build ... or promote Y": not X's predicate
    at = sentence.lower().find(clause[:40].lower())
    if at != -1 and sentence.lower().find(subject.text.lower()) >= at:
        return clause  # the "subject" is inside or after the clause itself
    return f"{subject.text}{JOINER}{clause}"


def verb_initial(clause: str) -> bool:
    """The clause opens with a verb: a participle or a subjectless finite predicate."""
    tokens = _content(words(clause))
    if not tokens:
        return False
    first, after = tokens[0], tokens[1] if len(tokens) > 1 else ""
    if first.endswith("ing") and len(first) > 4 and first not in _ING_NOT_VERB:
        return not has_verb(" ".join(tokens[1:]))  # else a gerund subject with a verb
    if first in VERB_ONLY or first in AUXILIARIES or first in IRREGULAR_PAST:
        return True
    return _third_person(first) and after not in _PREPOSITIONS


def sentence_subject(sentence: str) -> Subject | None:
    """The words before the sentence's first tensed verb (None: none, or anaphoric)."""
    found = list(_WORD.finditer(sentence))
    tokens = [m.group().lower() for m in found]
    verb = next((i for i in range(len(tokens)) if has_verb(" ".join(tokens[:i + 1]))), None)
    if not verb:  # no verb, or the sentence opens with one ("Combining these ...")
        return None
    head = _FRAME_END.split(sentence[:found[verb].start()])[-1].split()
    while head and head[0].lower() in _LEADING_ADVERBS:
        head = head[1:]
    while head and head[-1].lower() in _LEADING_ADVERBS:
        head = head[:-1]
    text = " ".join(head).strip(" ,;:")
    names = words(text)
    if not names or len(names) > _MAX_SUBJECT_WORDS or names[0] in _PRONOUNS:
        return None  # "These properties allow ...": the referent is elsewhere
    return Subject(text=text, verb=tokens[verb])


def _content(tokens: list[str]) -> list[str]:
    while tokens and tokens[0] in _LEADING_ADVERBS:
        tokens = tokens[1:]
    return tokens


def _first_word(clause: str) -> str:
    tokens = _content(words(clause))
    return tokens[0] if tokens else ""


def _singular(verb: str) -> bool:
    """A 3rd-person singular or past verb ("allows", "is", "has", "showed")."""
    return verb in ("is", "was", "has", "does") or _third_person(verb)


def _third_person(token: str) -> bool:
    """"reduces", "varies", "increases": the 3rd-person form of a known verb."""
    stems = VERB_ONLY | NOUN_TOO
    if token.endswith("ies") and token[:-3] + "y" in stems:
        return True
    if token.endswith("es") and token[:-2] in stems:
        return True
    return token.endswith("s") and token[:-1] in stems
