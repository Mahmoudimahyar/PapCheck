"""Test connectivity to all configured LLM providers.

Run: python scripts/test_llm_connectivity.py
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from refcheck.llm.env_setup import setup_llm_env_vars  # noqa: E402

providers = setup_llm_env_vars()

import litellm  # noqa: E402

MODELS = [
    {"alias": "gemini_flash", "id": "gemini/gemini-2.0-flash", "provider": "gemini", "tier": 0},
    {"alias": "llama_8b", "id": "nvidia_nim/meta/llama-3.1-8b-instruct", "provider": "nvidia", "tier": 0},
    {"alias": "qwq_32b", "id": "nvidia_nim/qwen/qwq-32b", "provider": "nvidia", "tier": 0},
    {"alias": "llama_70b", "id": "nvidia_nim/meta/llama-3.3-70b-instruct", "provider": "nvidia", "tier": 1},
    {"alias": "grok_mini", "id": "xai/grok-3-mini-fast-beta", "provider": "xai", "tier": 1},
    {"alias": "deepseek_v3", "id": "nvidia_nim/deepseek-ai/deepseek-v3.1", "provider": "nvidia", "tier": 2},
    {"alias": "sonnet", "id": "anthropic/claude-sonnet-4-5-20250929", "provider": "anthropic", "tier": 3},
]

VERIFY_PROMPT = (
    'You are verifying a scientific claim against source text.\n'
    'Claim: "Hydrogels can reduce transplant rejection."\n'
    'Source: "Recent studies show that hydrogel-based materials construct an '
    'immunosuppressive microenvironment, effectively reducing transplant '
    'rejection rates in animal models."\n'
    'Respond ONLY with JSON (no markdown fences, no explanation):\n'
    '{"verdict":"supported","confidence":0.9,"reasoning":"The source directly '
    'states hydrogels reduce rejection.","evidence_quotes":["hydrogel-based '
    'materials construct an immunosuppressive microenvironment"]}'
)


def parse_json(text: str) -> dict[str, object] | None:
    """Try multiple strategies to extract JSON from LLM text."""
    for attempt in [text, re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")]:
        try:
            return json.loads(attempt)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def test_model(m: dict[str, object]) -> dict[str, object]:
    """Test a single model for basic completion and JSON output."""
    alias = str(m["alias"])
    model_id = str(m["id"])
    provider = str(m["provider"])

    if not providers.get(provider):
        sys.stdout.write(f"  SKIP {alias}: no {provider} key\n")
        return {"alias": alias, "status": "SKIPPED"}

    sys.stdout.write(f"\n  Testing {alias} ({model_id})...\n")
    result: dict[str, object] = {"alias": alias, "model_id": model_id, "tier": m["tier"]}

    # Basic test
    try:
        t = time.time()
        r = litellm.completion(
            model=model_id,
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=50, temperature=0, timeout=60,
        )
        dt = time.time() - t
        result["basic"] = "PASS"
        result["basic_time"] = round(dt, 1)
        content = str(r.choices[0].message.content)[:80]
        sys.stdout.write(f"    Basic: PASS ({dt:.1f}s) -> {content}\n")
    except Exception as e:
        result["basic"] = "FAIL"
        result["error"] = str(e)[:200]
        sys.stdout.write(f"    Basic: FAIL -> {str(e)[:150]}\n")
        result["status"] = "FAIL"
        return result

    # JSON test
    try:
        t = time.time()
        r = litellm.completion(
            model=model_id,
            messages=[{"role": "user", "content": VERIFY_PROMPT}],
            max_tokens=500, temperature=0, timeout=90,
        )
        dt = time.time() - t
        content = str(r.choices[0].message.content)
        parsed = parse_json(content)
        if parsed and "verdict" in parsed:
            result["json"] = "PASS"
            result["json_verdict"] = parsed.get("verdict")
            sys.stdout.write(f"    JSON:  PASS ({dt:.1f}s) verdict={parsed.get('verdict')}\n")
        else:
            result["json"] = "PARTIAL"
            sys.stdout.write(f"    JSON:  PARTIAL ({dt:.1f}s) -> {content[:100]}\n")
    except Exception as e:
        result["json"] = "FAIL"
        sys.stdout.write(f"    JSON:  FAIL -> {str(e)[:150]}\n")

    result["status"] = "PASS"
    return result


def main() -> None:
    """Run connectivity tests against all configured models."""
    sys.stdout.write("=" * 50 + "\n")
    sys.stdout.write("RefCheck AI - LLM Connectivity Test\n")
    sys.stdout.write("=" * 50 + "\n")
    sys.stdout.write(f"Providers: {providers}\n")

    results = [test_model(m) for m in MODELS]

    sys.stdout.write("\n" + "=" * 50 + "\n")
    sys.stdout.write("SUMMARY\n")
    sys.stdout.write("=" * 50 + "\n")
    for r in results:
        status = str(r.get("status", "??"))
        icon = {"PASS": "OK", "SKIPPED": "--", "FAIL": "XX"}.get(status, "??")
        j = str(r.get("json", "N/A"))
        alias = str(r["alias"])
        basic = str(r.get("basic", "N/A"))
        sys.stdout.write(f"  [{icon}] {alias:18s} basic={basic:7s} json={j:7s}\n")

    passed = sum(1 for r in results if r.get("status") == "PASS")
    skipped = sum(1 for r in results if r.get("status") == "SKIPPED")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    sys.stdout.write(f"\n  {passed} passed, {skipped} skipped, {failed} failed\n")

    with open("test_llm_results.json", "w") as f:
        json.dump(results, f, indent=2)
    sys.stdout.write("  Results: test_llm_results.json\n")

    if passed == 0:
        sys.stdout.write("\n  CRITICAL: No models available!\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
