"""Synonym lexicon of the claim-slot classes (V5.7 #2 slot audit, #3 diff-based disqualifier).

Two strengths of "the text states this slot phrase" (a time frame, mechanism / cause,
recommendation / need or population / model: clear_rules):

* ``stated_in`` (the #2 slot-audit TRIGGER only): the phrase's own words
  (``own_words_in``) or any synonym of the lexicon group the phrase belongs to. Groups
  were fitted on the gold DEV false-trigger cases only ("annually" ~ "per year", "cause" ~
  "lead to" / "induce", "necessary" ~ "require" / "essential"); quantifier words are never
  slot phrases (they fired 7 false triggers for 1 true one). A trigger only asks the
  adjudicator, so a loose match costs a missed question, never a cleared problem;
* ``stated_strictly`` (the #3 disqualifier: may a wording / framing clearance pass?): the
  phrase's OWN words, a frequency only by a frequency of the same unit ("every year" is
  stated by "per year" / "annually", never by "5 years"), and a population only by a form
  of the same population ("mice" ~ "murine", never "rats", "rodents" or "transplant").

Species / population groups never bridge two species and hold no catch-all words
("transplant", "rodents", "recipients"); a frequency group never holds a bare duration
("years"). No imports from the layers.
"""

import re

_FREQ = r"(?:every|each|per|a|an|/)\s*"
# Frequency of one unit: "every year" ~ "per year" ~ "annually" (never "years").
FREQUENCY_GROUPS: tuple[tuple[str, ...], ...] = (
    (r"annual\w*", r"yearly", rf"{_FREQ}(?:year|yr)", r"per annum"),
    (r"monthly", rf"{_FREQ}month"),
    (r"weekly", rf"{_FREQ}week"),
    (r"daily", rf"{_FREQ}day"),
)
# One population or model each (forms of the same one, never two species).
POPULATION_GROUPS: tuple[tuple[str, ...], ...] = (
    (r"humans?", r"patients?", r"clinical\w*", r"people", r"participants?", r"volunteers?"),
    (r"children", r"child", r"p(?:a)?ediatric\w*", r"infants?", r"adolescen\w*"),
    (r"adults?",),
    (r"mice", r"mouse", r"murine"),
    (r"rats?",),
    (r"(?:non-?human\s+)?primates?", r"monkeys?", r"macaques?", r"baboons?", r"nhps?"),
    (r"pigs?", r"porcine", r"swine", r"minipigs?"),
    (r"dogs?", r"canine"),
    (r"sheep", r"ovine", r"lambs?"),
    (r"in\s+vivo", r"animals?"),
    (r"in\s+vitro", r"cultur\w*", r"cell\s+lines?"),
)
# Trigger-only groups (#2): meanings a paraphrase may carry.
_TRIGGER_GROUPS: tuple[tuple[str, ...], ...] = (
    (r"long[- ]term", r"chronic\w*", r"prolonged", r"extended period", r"durable",
     r"months", r"years"),
    (r"decades?", r"years"),
    (r"caus\w*", r"lead(?:s|ing)?\s+to", r"led\s+to", r"result\w*\s+in", r"induc\w*",
     r"trigger\w*", r"due\s+to", r"because", r"attribut\w*", r"driv\w*", r"mediat\w*",
     r"responsible\s+for", r"give\s+rise", r"gives\s+rise", r"contribut\w*",
     r"produc\w*", r"provok\w*", r"elicit\w*"),
    (r"reject\w*", r"allorejection"),
    (r"toleran\w*", r"tolerogen\w*", r"unresponsive\w*", r"anergy"),
    (r"mechanis\w*", r"pathway\w*", r"mode of action"),
    (r"should", r"must", r"need\w*", r"requir\w*", r"essential", r"necessar\w*",
     r"necessit\w*", r"ought", r"indispensable", r"prerequisite", r"crucial", r"critical",
     r"vital", r"important\s+to"),
    (r"recommend\w*", r"advis\w*", r"guideline\w*", r"suggest\w*", r"propos\w*"),
    (r"future", r"forward[- ]looking", r"further\s+(?:stud|research|work|investigation)\w*",
     r"remains?\s+to\s+be", r"warrant\w*"),
)
SYNONYM_GROUPS = (*FREQUENCY_GROUPS, *POPULATION_GROUPS, *_TRIGGER_GROUPS)


def _compile(groups: tuple[tuple[str, ...], ...]) -> tuple[tuple[re.Pattern[str], ...], ...]:
    return tuple(tuple(re.compile(rf"(?<![\w-])(?:{alt})(?![\w-])", re.IGNORECASE)
                       for alt in group) for group in groups)


_ALL = _compile(SYNONYM_GROUPS)
_FREQUENCY = _compile(FREQUENCY_GROUPS)
_POPULATION = _compile(POPULATION_GROUPS)
_FUNCTION_WORDS = frozenset({"a", "an", "the", "per", "each", "every", "in", "of", "to",
                             "by", "s"})
_SUFFIX = re.compile(r"(?:ing|ed|es|s|ly)$")
_PREFIX_MIN = 4  # a shorter word must match whole ("all" never matches "allograft")


def _stem(word: str) -> str:
    return _SUFFIX.sub("", word.lower()) or word.lower()


def _word_in(word: str, lowered: str) -> bool:
    tail = "" if len(word) >= _PREFIX_MIN else r"\b"
    return re.search(r"\b" + re.escape(word) + tail, lowered) is not None


def own_words_in(phrase: str, text: str) -> bool:
    """Every content word of ``phrase`` starts a word of ``text`` (light stemming)."""
    words = [_stem(w) for w in re.findall(r"[A-Za-z]+", phrase)
             if w.lower() not in _FUNCTION_WORDS]
    lowered = text.lower()
    return bool(words) and all(_word_in(w, lowered) for w in words)


phrase_in = own_words_in  # the name the callers know


def _group_in(groups: tuple[tuple[re.Pattern[str], ...], ...], phrase: str,
              text: str) -> bool | None:
    """None when ``phrase`` is in none of ``groups``; else whether ``text`` has an entry of
    a group ``phrase`` belongs to."""
    member = [g for g in groups if any(p.search(phrase) for p in g)]
    if not member:
        return None
    return any(p.search(text) for g in member for p in g)


def synonyms_in(phrase: str, text: str) -> bool:
    """A lexicon group ``phrase`` belongs to has an entry in ``text``."""
    return bool(_group_in(_ALL, phrase, text))


def stated_in(phrase: str, text: str) -> bool:
    """#2 trigger (module doc): ``phrase`` or a lexicon synonym of it is in ``text``."""
    frequency = _group_in(_FREQUENCY, phrase, text)
    if frequency is not None:  # "every year" is never stated by a bare "years"
        return frequency
    return own_words_in(phrase, text) or synonyms_in(phrase, text)


def stated_strictly(phrase: str, text: str) -> bool:
    """#3 (module doc): the phrase's own words; a frequency or population only by a form
    of the same one."""
    for groups in (_FREQUENCY, _POPULATION):
        found = _group_in(groups, phrase, text)
        if found is not None:
            return found
    return own_words_in(phrase, text)
