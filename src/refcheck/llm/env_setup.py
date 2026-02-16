"""Map user env vars to litellm env vars. Call at app startup."""

import logging
import os

logger = logging.getLogger(__name__)


def setup_llm_env_vars() -> dict[str, bool]:
    """Map user env vars to what litellm expects. Returns provider availability."""
    providers: dict[str, bool] = {}

    # NVIDIA: user sets NVIDIA_API_KEY, litellm needs NVIDIA_NIM_API_KEY
    nvidia_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get(
        "NVIDIA_NIM_API_KEY",
    )
    if nvidia_key:
        os.environ["NVIDIA_NIM_API_KEY"] = nvidia_key
        providers["nvidia"] = True
        logger.info("NVIDIA NIM API key configured")
    else:
        providers["nvidia"] = False

    # Grok: user sets GROK_API_KEY, litellm needs XAI_API_KEY
    grok_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
    if grok_key:
        os.environ["XAI_API_KEY"] = grok_key
        providers["xai"] = True
        logger.info("xAI/Grok API key configured")
    else:
        providers["xai"] = False

    # Gemini: litellm uses GEMINI_API_KEY directly
    providers["gemini"] = bool(os.environ.get("GEMINI_API_KEY"))
    if providers["gemini"]:
        logger.info("Gemini API key configured")

    # Anthropic: litellm uses ANTHROPIC_API_KEY directly
    providers["anthropic"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if providers["anthropic"]:
        logger.info("Anthropic API key configured")

    available = [p for p, v in providers.items() if v]
    logger.info("Available LLM providers: %s", available)
    if not available:
        logger.error("No LLM API keys found!")
    return providers
