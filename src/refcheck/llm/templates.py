"""Load and render Jinja2 prompt templates from src/refcheck/prompts/."""

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _get_env() -> Environment:
    """Create Jinja2 environment for prompt templates."""
    return Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )


def load_template(name: str) -> str:
    """Load a raw prompt template by name (without .md extension)."""
    env = _get_env()
    try:
        template = env.get_template(f"{name}.md")
        return template.render()
    except TemplateNotFound:
        logger.error("Prompt template not found: %s", name)
        raise


def render_template(name: str, variables: dict[str, str]) -> str:
    """Load and render a prompt template with variables."""
    env = _get_env()
    try:
        template = env.get_template(f"{name}.md")
        return template.render(**variables)
    except TemplateNotFound:
        logger.error("Prompt template not found: %s", name)
        raise
