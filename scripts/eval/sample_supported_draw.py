"""Deterministic stratified sample of tool-"supported" pairs + review batches.

Strata are manuscript section x "the sentence cites 2+ references". Every
abstract-only pair is forced in (up to MAX_ABSTRACT_ONLY), each section gets at
least MIN_PER_SECTION pairs, about half of the sample comes from multi-citation
sentences, and inside a stratum pairs are drawn systematically along manuscript
order (one per equal-width slice) so the sample spreads through each section.
No reference contributes more than MAX_PER_REF pairs.
"""

import math
import random
from collections import Counter, defaultdict

from pydantic import BaseModel, Field

MAX_PER_REF = 2
MIN_PER_SECTION = 2
MAX_ABSTRACT_ONLY = 6


class Candidate(BaseModel):
    """One tool-"supported" (sentence, reference) pair eligible for the sample."""

    pair_id: str
    claim_number: int
    ref: int
    sentence_key: str  # normalised sentence
    section: str
    multi: bool  # the sentence cites 2+ references
    abstract_only: bool = False


class DrawState(BaseModel):
    """Pairs chosen so far plus the counters the caps are checked against."""

    chosen: list[Candidate] = Field(default_factory=list)
    ids: set[str] = Field(default_factory=set)
    per_ref: dict[int, int] = Field(default_factory=dict)
    sentences: set[str] = Field(default_factory=set)

    def allows(self, cand: Candidate) -> bool:
        return cand.pair_id not in self.ids and self.per_ref.get(cand.ref, 0) < MAX_PER_REF

    def add(self, cand: Candidate) -> None:
        self.chosen.append(cand)
        self.ids.add(cand.pair_id)
        self.per_ref[cand.ref] = self.per_ref.get(cand.ref, 0) + 1
        self.sentences.add(cand.sentence_key)


class SamplePlan(BaseModel):
    """How the sample was drawn (written to the manifest)."""

    n: int
    seed: int
    pool: int
    section_quota: dict[str, int]
    multi_quota: dict[str, int]
    forced: list[str]  # pair ids of the forced abstract-only pairs
    topped_up: int = 0  # pairs drawn outside their stratum because a stratum ran dry


class CaseLoad(BaseModel):
    """Review effort of one case, for batching (paper text is shared per reference)."""

    case: int
    ref: int
    chars: int


def manuscript_order(cand: Candidate) -> tuple[int, int]:
    return cand.claim_number, cand.ref


def allocate(weights: dict[str, float], total: int, floors: dict[str, int],
             caps: dict[str, int]) -> dict[str, int]:
    """Split `total` over groups ~proportionally to weight, each within [floor, cap]."""
    quota = {k: min(floors.get(k, 0), caps[k]) for k in weights}
    weight_sum = sum(weights.values()) or 1.0
    while sum(quota.values()) < total:
        room = [k for k in weights if quota[k] < caps[k]]
        if not room:
            break
        best = max(room, key=lambda k: (weights[k] * total / weight_sum - quota[k], weights[k], k))
        quota[best] += 1
    return quota


def _pick_one(state: DrawState, options: list[Candidate], rng: random.Random) -> bool:
    """Add one random allowed option, preferring sentences not sampled yet."""
    shuffled = list(options)
    rng.shuffle(shuffled)
    for cand in sorted(shuffled, key=lambda c: c.sentence_key in state.sentences):
        if state.allows(cand):
            state.add(cand)
            return True
    return False


def draw_systematic(state: DrawState, pool: list[Candidate], k: int,
                    rng: random.Random) -> int:
    """Draw k pairs, one per equal slice of the pool in manuscript order; returns # drawn."""
    ordered = sorted((c for c in pool if c.pair_id not in state.ids), key=manuscript_order)
    k = min(k, len(ordered))
    if k <= 0:
        return 0
    drawn = sum(_pick_one(state, ordered[i * len(ordered) // k:(i + 1) * len(ordered) // k],
                          rng) for i in range(k))
    while drawn < k and _pick_one(state, [c for c in ordered if c.pair_id not in state.ids],
                                  rng):
        drawn += 1
    return drawn


def _force_abstract_only(state: DrawState, cands: list[Candidate],
                         rng: random.Random) -> list[Candidate]:
    pool = sorted((c for c in cands if c.abstract_only), key=manuscript_order)
    if len(pool) > MAX_ABSTRACT_ONLY:
        rng.shuffle(pool)
    forced: list[Candidate] = []
    for cand in pool:
        if len(forced) < MAX_ABSTRACT_ONLY and state.allows(cand):
            state.add(cand)
            forced.append(cand)
    return forced


def _multi_quota(cands: list[Candidate], forced: list[Candidate],
                 section_quota: dict[str, int], target: int) -> dict[str, int]:
    avail = Counter((c.section, c.multi) for c in cands)
    fixed = Counter((c.section, c.multi) for c in forced)
    floors = {s: max(fixed[(s, True)], q - avail[(s, False)]) for s, q in section_quota.items()}
    caps = {s: min(avail[(s, True)], q - fixed[(s, False)]) for s, q in section_quota.items()}
    weights = {s: float(q) for s, q in section_quota.items()}
    return allocate(weights, target, floors, caps)


def draw_sample(cands: list[Candidate], n: int, seed: int,
                ) -> tuple[list[Candidate], SamplePlan]:
    """The sample (sorted by reference, then claim) and the plan that produced it."""
    rng = random.Random(seed)
    state = DrawState()
    forced = _force_abstract_only(state, cands, rng)
    sizes = Counter(c.section for c in cands)
    forced_sec = Counter(c.section for c in forced)
    floors = {s: max(forced_sec[s], min(MIN_PER_SECTION, v)) for s, v in sizes.items()}
    quota = allocate({s: float(v) for s, v in sizes.items()}, n, floors, dict(sizes))
    multi = _multi_quota(cands, forced, quota, n // 2)
    for section in sorted(quota):
        for is_multi in (True, False):
            want = multi[section] if is_multi else quota[section] - multi[section]
            have = sum(1 for c in forced if (c.section, c.multi) == (section, is_multi))
            pool = [c for c in cands if (c.section, c.multi) == (section, is_multi)]
            draw_systematic(state, pool, want - have, rng)
    before = len(state.chosen)
    draw_systematic(state, cands, n - before, rng)
    plan = SamplePlan(n=n, seed=seed, pool=len(cands), section_quota=quota, multi_quota=multi,
                      forced=[c.pair_id for c in forced], topped_up=len(state.chosen) - before)
    return sorted(state.chosen, key=lambda c: (c.ref, c.claim_number)), plan


def _place(batches: list[list[int]], loads: list[int], members: list[int], weight: int,
           size: int) -> bool:
    room = [i for i in range(len(batches)) if len(batches[i]) + len(members) <= size]
    if not room:
        return False
    best = min(room, key=lambda i: (loads[i], i))
    batches[best].extend(members)
    loads[best] += weight
    return True


def make_batches(cases: list[CaseLoad], paper_chars: dict[int, int],
                 n_batches: int) -> list[list[int]]:
    """Equal-size batches balanced by reading load; cases of one reference stay together."""
    size = math.ceil(len(cases) / n_batches)
    groups: dict[int, list[CaseLoad]] = defaultdict(list)
    for case in cases:
        groups[case.ref].append(case)
    units = sorted(((paper_chars.get(ref, 0) + sum(c.chars for c in group),
                     [c.case for c in group]) for ref, group in groups.items()),
                   key=lambda u: (-u[0], u[1]))
    batches: list[list[int]] = [[] for _ in range(n_batches)]
    loads = [0] * n_batches
    for weight, members in units:
        if not _place(batches, loads, members, weight, size):
            for member in members:  # no batch has room for the whole group: split it
                _place(batches, loads, [member], weight // len(members), size)
    return [sorted(b) for b in batches]
