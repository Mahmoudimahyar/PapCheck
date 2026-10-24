"""Sample tool-"supported" pairs of the fixed V4.9 run for manual review (Package G).

  python scripts/eval/sample_supported.py --session sess_xxxxxxxxxxxx
  python scripts/eval/sample_supported.py --session sess_xxxxxxxxxxxx --n 45 --batches 5

The gold set only holds pairs the tool flagged, so it cannot measure missed
problems. This draws a deterministic, stratified sample of the session's
"supported" pairs that are not in the gold set yet (pair ids as in
build_refcheck_gold.py; also matched on normalised sentence + reference),
extracts each cited paper's text locally and writes
~/.refcheck/e2e/v4.9/review_supported/{cases.json, batches.json, batchNN.json,
manifest.json, ref<N>.txt}. The DB is opened read-only; no API is called.
Output holds unpublished manuscript text: never write it into the repo.
"""

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from eval_models import EVAL_DIR
from gold_db import DEFAULT_DB, SessionData, load_session, production_pdf
from gold_models import normalize_sentence, pair_id
from pydantic import BaseModel
from sample_supported_case import SupportedCase, build_case, load_quotes
from sample_supported_draw import Candidate, CaseLoad, SamplePlan, draw_sample, make_batches
from sample_supported_text import PaperText, paper_text

logger = logging.getLogger("sample_supported")
V49 = Path.home() / ".refcheck" / "e2e" / "v4.9"
GOLD_FILE = EVAL_DIR / "refcheck_v49_gold.jsonl"
SUPPORTED = "supported"
GoldKeys = tuple[set[str], set[tuple[str, int]]]  # pair ids, (normalised sentence, ref)


class SampleManifest(BaseModel):
    session_id: str
    gold_file: str
    supported_total: int
    excluded_in_gold: int
    plan: SamplePlan
    by_section: dict[str, int]
    by_stratum: dict[str, int]
    by_coverage: dict[str, int]
    n_refs: int
    text_origin: dict[str, int]
    text_notes: dict[int, list[str]]
    batches: list[list[int]]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--session", required=True, help="app session id (sess_…) in the database")
    p.add_argument("--gold", type=Path, default=GOLD_FILE)
    p.add_argument("--out-dir", type=Path, default=V49 / "review_supported")
    p.add_argument("--reuse-dirs", type=Path, nargs="*",
                   default=[V49 / "review_partial", V49 / "review"])
    p.add_argument("--n", type=int, default=45)
    p.add_argument("--seed", type=int, default=20261021)
    p.add_argument("--batches", type=int, default=5)
    p.add_argument("--paragraph-chars", type=int, default=1500)
    return p.parse_args(argv)


def gold_keys(path: Path) -> GoldKeys:
    """Pair ids and (normalised sentence, ref) keys already in the gold set."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return ({r["id"] for r in rows},
            {(normalize_sentence(r["sentence"]), int(r["ref"])) for r in rows})


def candidates(session: SessionData, gold: GoldKeys) -> tuple[list[Candidate], int]:
    """Supported pairs not in the gold set (one per pair id); plus # excluded as gold."""
    by_number = {c.number: c for c in session.claims}
    found: dict[str, Candidate] = {}
    in_gold = 0
    for (number, ref), ver in sorted(session.verifications.items()):
        claim = by_number.get(number)
        if ver.verdict != SUPPORTED or claim is None:
            continue
        pid, key = pair_id(claim.sentence, ref), (normalize_sentence(claim.sentence), ref)
        if pid in gold[0] or key in gold[1]:
            in_gold += 1
            continue
        multi = claim.co_cited_count >= 2 or bool(session.co_cited(claim.sentence, ref))
        found.setdefault(pid, Candidate(
            pair_id=pid, claim_number=number, ref=ref, sentence_key=key[0],
            section=claim.section, multi=multi, abstract_only=ver.coverage == "abstract_only"))
    return list(found.values()), in_gold


def paper_texts(session: SessionData, refs: set[int], args: argparse.Namespace,
                ) -> dict[int, PaperText]:
    texts: dict[int, PaperText] = {}
    for number in sorted(refs):
        ref = production_pdf(session.references, session.references[number])
        texts[number] = paper_text(number, ref.pdf_path, ref.title, args.out_dir,
                                   args.reuse_dirs)
    return texts


def _dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def write_outputs(out_dir: Path, cases: list[SupportedCase], batches: list[list[int]]) -> None:
    _dump(out_dir / "cases.json", [c.model_dump() for c in cases])
    _dump(out_dir / "batches.json", [{"batch": i, "cases": b} for i, b in enumerate(batches, 1)])
    for i, batch in enumerate(batches, 1):
        _dump(out_dir / f"batch{i:02d}.json", [c.model_dump() for c in cases if c.case in batch])


def run(args: argparse.Namespace) -> SampleManifest:
    session = load_session(args.session, args.db)
    pool, in_gold = candidates(session, gold_keys(args.gold))
    sample, plan = draw_sample(pool, args.n, args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    texts = paper_texts(session, {c.ref for c in sample}, args)
    quotes, forced = load_quotes(args.db, args.session), set(plan.forced)
    cases = [build_case(i, c, session, quotes, texts[c.ref], args.paragraph_chars, forced)
             for i, c in enumerate(sample, 1)]
    loads = [CaseLoad(case=c.case, ref=c.ref, chars=len(c.sentence) + len(c.paragraph)
                      + len(c.abstract)) for c in cases]
    batches = make_batches(loads, {n: t.chars for n, t in texts.items()}, args.batches)
    write_outputs(args.out_dir, cases, batches)
    info = SampleManifest(
        session_id=args.session, gold_file=str(args.gold),
        supported_total=sum(1 for v in session.verifications.values()
                            if v.verdict == SUPPORTED),
        excluded_in_gold=in_gold, plan=plan,
        by_section=dict(Counter(c.section[:40] for c in cases)),
        by_stratum=dict(Counter(c.stratum for c in cases)),
        by_coverage=dict(Counter(c.coverage for c in cases)), n_refs=len(texts),
        text_origin=dict(Counter(t.origin for t in texts.values())),
        text_notes={n: t.notes for n, t in texts.items() if t.notes}, batches=batches)
    (args.out_dir / "manifest.json").write_text(info.model_dump_json(indent=1),
                                                encoding="utf-8")
    logger.info("%d cases from %d refs (pool %d, %d already gold) -> %s", len(cases),
                len(texts), len(pool), in_gold, args.out_dir)
    logger.info("strata %s; coverage %s; texts %s", info.by_stratum, info.by_coverage,
                info.text_origin)
    return info


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(parse_args())
