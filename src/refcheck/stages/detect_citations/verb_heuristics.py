"""Deterministic "does this text contain a tensed verb?" heuristics (no NLP).

Used to flag sentence fragments cited as claims ("Combining these
functionalities (X et al., 2023).") and to decide whether a clause closed by
an inline citation is a real clause or just a noun phrase ("Drug X (Ref1)
and Drug Y (Ref2) reduce rejection"). Errs towards "has a verb": a missed
fragment costs less than flagging a complete claim.
"""

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

AUXILIARIES = frozenset({
    "is", "are", "was", "were", "am", "has", "have", "had", "do", "does", "did",
    "can", "could", "may", "might", "must", "shall", "should", "will", "would",
    "cannot", "isn't", "aren't", "wasn't", "weren't", "doesn't", "don't", "didn't",
})
IRREGULAR_PAST = frozenset({
    "showed", "found", "led", "made", "took", "became", "gave", "began", "saw",
    "held", "kept", "left", "met", "ran", "grew", "drew", "brought", "thought",
    "sought", "understood", "went", "came", "won", "lost", "fell", "rose", "chose",
    "wrote", "built", "spent", "sent", "felt", "told", "paid", "bound", "spread",
})
# Base forms that are (almost) never nouns: finite whenever not after "to"/a determiner
VERB_ONLY = frozenset({
    "accelerate", "accumulate", "achieve", "activate", "affect", "aggravate", "allow", "alter",
    "appear", "apply", "arise", "attenuate", "augment", "avoid", "become", "begin", "behave",
    "bind", "combine", "come", "comprise", "confer", "confirm", "constitute", "contain",
    "continue", "contribute", "correlate", "create", "define", "degrade", "deliver",
    "demonstrate", "depend", "describe", "determine", "develop", "differ", "diminish", "elicit",
    "eliminate", "enable", "encapsulate", "enhance", "ensure", "evade", "evoke", "exceed",
    "exert", "exhibit", "exist", "expand", "explain", "express", "extend", "facilitate", "fail",
    "generate", "give", "govern", "hamper", "harbor", "hinder", "impair", "improve", "include",
    "indicate", "induce", "inhibit", "initiate", "integrate", "involve", "leave", "maintain",
    "make", "manifest", "mediate", "minimize", "mitigate", "modulate", "occur", "outperform",
    "permit", "persist", "pose", "possess", "predict", "prevent", "produce", "prolong",
    "promote", "protect", "provide", "recruit", "reduce", "refer", "reflect", "regulate",
    "reject", "rely", "remain", "remove", "render", "represent", "require", "restore",
    "restrict", "reveal", "seem", "serve", "stimulate", "suggest", "suppress", "sustain",
    "tend", "undergo", "underlie", "vary",
})
# Base forms that are often nouns ("drug release", "glycemic control")
NOUN_TOO = frozenset({
    "act", "address", "block", "cause", "challenge", "change", "control", "cover", "damage",
    "decrease", "display", "drive", "experience", "form", "function", "help", "increase",
    "influence", "lack", "lead", "limit", "lower", "need", "offer", "play", "point", "present",
    "raise", "range", "release", "report", "result", "show", "support", "target", "trigger",
    "use", "work", "yield",
})
_DETERMINERS = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "its", "their", "our",
    "his", "her", "no", "each", "every", "any", "some", "such", "of", "to",
})
_SUBJECT_WORDS = frozenset({
    "they", "we", "i", "you", "it", "he", "she", "which", "that", "who", "these",
    "those", "both", "all",
})
# Adverbs that sit between subject and verb ("also neutralize", "then binds")
_PREVERBAL = frozenset({
    "also", "often", "still", "never", "not", "then", "thus", "therefore", "further",
    "usually", "generally", "typically", "probably", "frequently", "commonly",
})
# Verb-forming suffixes ("neutralize", "quantifies"); never noun endings
_VERB_SUFFIXES = ("ize", "izes", "ify", "ifies")
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "as", "into", "onto", "than", "that", "this", "these",
    "those", "it", "its", "their", "they", "them", "we", "our", "such", "which",
    "who", "whom", "whose", "be", "been", "being", "also", "both", "either",
    "via", "per", "not", "only", "more", "most", "very", "well", "then", "et", "al",
    "within", "without", "across", "between", "among", "through", "throughout",
    "under", "over", "after", "before", "during", "against", "toward", "towards",
    "upon", "about", "above", "below", "beyond", "near", "along", "around",
    "inside", "outside", "despite", "versus", "like", "unlike", "including",
})
# Suffixes of nouns/adjectives that may follow a plural noun ("cells positive for")
_NOT_VERB_SUFFIXES = (
    "s", "ly", "al", "ic", "ous", "ive", "ion", "ity", "ment", "ness", "ence",
    "ance", "able", "ible", "ary", "ory", "ing", "ful", "less", "er", "ant",
    "ent", "ism", "ist", "ure", "age", "ty", "cy",
)


def words(text: str) -> list[str]:
    """Lower-cased word tokens."""
    return [w.lower() for w in _WORD.findall(text)]


def has_verb(text: str) -> bool:
    """A tensed verb we recognise, or a probable one in subject-verb position."""
    tokens = words(text)
    return any(_is_finite(tokens, i) or _probable_verb(tokens, i) for i in range(len(tokens)))


def _is_finite(tokens: list[str], i: int) -> bool:
    tok, prev = tokens[i], tokens[i - 1] if i else ""
    if tok in AUXILIARIES or tok in IRREGULAR_PAST:
        return True
    # Demonstratives as subjects: "these include" / "this makes" are verbs,
    # "these results" / "this increase" are nouns.
    if prev in ("these", "those"):
        return tok in VERB_ONLY or tok in NOUN_TOO
    if prev in ("this", "that"):
        return _third_person(tok) or (prev == "that" and tok in VERB_ONLY)
    if prev in _DETERMINERS:
        return False
    if tok in VERB_ONLY:
        return True
    if tok in NOUN_TOO:
        return _plural_like(prev) or _adverb(prev) or prev in _SUBJECT_WORDS
    if i > 0 and tok.endswith("ed") and len(tok) >= 4:
        return True
    return tok.endswith(_VERB_SUFFIXES) or _third_person(tok)


def _probable_verb(tokens: list[str], i: int) -> bool:
    """Unknown word after a plural subject or a pre-verbal adverb:
    "hydrogels swell in water", "they probably invade", "cells actively secrete"."""
    if i == 0:
        return False
    tok, prev = tokens[i], tokens[i - 1]
    if tok in STOPWORDS or len(tok) <= 2:
        return False
    if prev in _PREVERBAL and tok.endswith("s"):  # "Parkin then ubiquitinates"
        return not tok.endswith(("ss", "ness", "ics"))
    after_subject = prev not in STOPWORDS and _plural_like(prev)
    if not (after_subject or _adverb(prev)):
        return False
    return not tok.endswith(_NOT_VERB_SUFFIXES)


def _adverb(word: str) -> bool:
    return word in _PREVERBAL or (word.endswith("ly") and len(word) > 4)


def _plural_like(word: str) -> bool:
    """A plural subject ("hydrogels"), not "tacrolimus"/"stress"/"analysis"."""
    return word.endswith("s") and not word.endswith(("ss", "us", "is"))


def _third_person(tok: str) -> bool:
    """3rd-person "-s"/"-es"/"-ies" form of a known verb ("reduces", "varies")."""
    stems = VERB_ONLY | NOUN_TOO
    if tok.endswith("ies") and tok[:-3] + "y" in stems:
        return True
    if tok.endswith("es") and tok[:-2] in stems:
        return True
    return tok.endswith("s") and tok[:-1] in stems


# Openers that may precede a subject-less verb ("Also showed ...")
_OPENER_ADVERBS = frozenset({
    "also", "then", "further", "later", "subsequently", "previously", "initially", "first",
})
# "Based on", "Compared with", "Embedded in": a participle opener, not the verb
_AFTER_PARTICIPLE = frozenset({
    "on", "with", "to", "by", "in", "upon", "from", "for", "at", "as", "together", "into",
    "under", "over", "after",
})


def opens_with_predicate(text: str) -> bool:
    """The sentence starts with its verb and so lacks a subject ("Used X in mice
    to ...", "Showed that ..."): its subject was cut off by a stray period, as in
    "Lee et al. (2002). Used X ...". Errs towards False."""
    tokens = words(text)
    if tokens[:1] and tokens[0] in _OPENER_ADVERBS:
        tokens = tokens[1:]
    if len(tokens) < 2 or tokens[1] in _AFTER_PARTICIPLE:
        return False
    first = tokens[0]
    if first in IRREGULAR_PAST:
        return True
    past = first.endswith("ed") and len(first) >= 4 and not first.endswith("eed")
    if not (past or _verb_only_third_person(first)):
        return False
    # "Limited data suggest ...", "Increased levels were ...": an adjective opener
    return not any(_is_finite(tokens, i) for i in range(1, min(3, len(tokens))))


def _verb_only_third_person(tok: str) -> bool:
    """3rd-person form of a verb that is never a noun ("demonstrates"), not "reports"."""
    if tok.endswith("ies"):
        return tok[:-3] + "y" in VERB_ONLY
    return tok.endswith("s") and (tok[:-1] in VERB_ONLY or tok[:-2] in VERB_ONLY)
