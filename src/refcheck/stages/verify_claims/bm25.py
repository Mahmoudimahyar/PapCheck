"""Small pure-Python Okapi BM25 with light stemming, for passage retrieval."""

import math
import re
import unicodedata
from collections import Counter

_TOKEN_RE = re.compile(r"[^\W_]+")
STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "also", "although", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "during",
    "each", "et", "al", "etc", "few", "for", "from", "further", "had", "has", "have", "having",
    "he", "her", "here", "hers", "him", "his", "how", "however", "i", "if", "in", "into", "is",
    "it", "its", "itself", "may", "might", "more", "most", "must", "my", "of", "on", "once",
    "only", "or", "other", "our", "ours", "out", "over", "own", "same", "shall", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "then",
    "there", "these", "they", "this", "those", "through", "thus", "to", "too", "under",
    "until", "up", "upon", "us", "very", "via", "was", "we", "were", "what", "when", "where",
    "whether", "which", "while", "who", "whom", "why", "will", "with", "within", "would",
    "yet", "you", "your", "fig", "figure", "table", "shown", "show", "shows", "showed",
})


def stem(token: str) -> str:
    """Strip common English inflections so 'reduces/reduced/reducing' meet."""
    if len(token) <= 3 or token.isdigit():
        return token
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("sses"):
        token = token[:-2]
    elif token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    if token.endswith("ing") and len(token) >= 7:
        token = token[:-3]
    elif token.endswith("ed") and len(token) >= 6:
        token = token[:-2]
    if token.endswith("e") and len(token) >= 5:
        token = token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords, stemmed (keeps numbers and Greek).

    NFKC first, so a query and a passage that differ only in compatibility
    characters (PDF ligature "ﬁbrosis", micro sign "µm", full-width digits)
    produce the same tokens.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return [
        stem(tok) for tok in _TOKEN_RE.findall(folded)
        if len(tok) > 1 and tok not in STOPWORDS
    ]


class BM25Index:
    """Okapi BM25 over a fixed list of documents (here: retrieval windows)."""

    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n_docs = len(docs)
        self._doc_len: list[int] = []
        self._postings: dict[str, list[tuple[int, int]]] = {}
        for i, text in enumerate(docs):
            counts = Counter(tokenize(text))
            self._doc_len.append(sum(counts.values()))
            for term, tf in counts.items():
                self._postings.setdefault(term, []).append((i, tf))
        total = sum(self._doc_len)
        self._avg_len = total / self.n_docs if self.n_docs and total else 1.0

    def idf(self, term: str) -> float:
        """Non-negative BM25 idf (Lucene variant)."""
        df = len(self._postings.get(term, ()))
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> dict[int, float]:
        """Score every document sharing at least one query term."""
        out: dict[int, float] = {}
        for term in set(tokenize(query)):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for doc_i, tf in postings:
                norm = self.k1 * (1 - self.b + self.b * self._doc_len[doc_i] / self._avg_len)
                out[doc_i] = out.get(doc_i, 0.0) + idf * tf * (self.k1 + 1) / (tf + norm)
        return out

    def top_n(self, query: str, n: int) -> list[tuple[int, float]]:
        """Best n (doc index, score) pairs with score > 0, best first (ties: doc order)."""
        ranked = sorted(self.scores(query).items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:n]

    def rank_all(self, query: str) -> list[tuple[int, float]]:
        """All scoring documents, best first."""
        return self.top_n(query, self.n_docs)
