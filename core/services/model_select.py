"""Pick Cerebras model tier from message complexity.

Current public Cerebras models (2026): gpt-oss-120b, zai-glm-4.7.
Llama/Qwen IDs were deprecated — see https://inference-docs.cerebras.ai/support/deprecation
"""

from django.conf import settings

from core.services.config import cfg

DEFAULT_FAST = "gpt-oss-120b"
DEFAULT_STANDARD = "gpt-oss-120b"
DEFAULT_ADVANCED = "zai-glm-4.7"
DEFAULT_FALLBACK = "gpt-oss-120b"


def _resolved(name, default):
    return cfg(name, getattr(settings, name, default)) or default


def model_fast():
    return _resolved("CEREBRAS_MODEL_FAST", DEFAULT_FAST)


def model_standard():
    return _resolved("CEREBRAS_MODEL_STANDARD", DEFAULT_STANDARD)


def model_advanced():
    return _resolved("CEREBRAS_MODEL_ADVANCED", DEFAULT_ADVANCED)


def model_fallback():
    return _resolved("CEREBRAS_MODEL_FALLBACK", DEFAULT_FALLBACK)


# Back-compat aliases (defaults only — use functions for runtime cfg overrides)
MODEL_FAST = DEFAULT_FAST
MODEL_STANDARD = DEFAULT_STANDARD
MODEL_ADVANCED = DEFAULT_ADVANCED
MODEL_FALLBACK = DEFAULT_FALLBACK

OPUS_TRIGGERS = (
    "perelman", "poincare", "poincaré", "poincare conjecture", "millennium prize",
    "riemann hypothesis", "yang-mills", "navier-stokes", "hodge conjecture",
    "birch and swinnerton", "bsd conjecture", "topology proof", "differential geometry proof",
    "category theory", "algebraic geometry", "phd level", "doctoral", "research-level",
    "formal proof", "exceptionally challenging", "extremely difficult", "graduate-level proof",
)

SONNET_TRIGGERS = (
    "prove", "proof", "derive", "theorem", "lemma", "explain in detail", "step by step",
    "analyze", "essay", "write a", "study plan", "compare and contrast", "evaluate",
    "synthesize", "research paper", "literature review", "code review", "debug",
    "integral", "derivative", "differential equation", "linear algebra", "probability",
)

MATH_WORDS = (
    "solve", "calculate", "derivative", "integral", "equation", "matrix", "vector",
    "limit", "series", "proof",
)


def needs_web_search(message: str, *, has_attachment: bool = False) -> bool:
    msg = (message or "").lower().strip()
    if not msg and not has_attachment:
        return False
    triggers = (
        "latest", "current", "today", "recent", "2024", "2025", "2026",
        "who is", "who was", "what is", "what was", "when did", "when was",
        "according to", "cite", "citation", "source", "sources", "research",
        "paper", "study", "statistics", "data shows", "news", "wikipedia",
        "compare", "contrast", "analyze", "analyse", "evaluate", "debate",
        "history of", "explain why", "how does", "is it true", "fact check",
        "verify", "perelman", "conjecture", "theorem", "hypothesis",
    )
    if any(t in msg for t in triggers):
        return True
    if len(msg.split()) > 90:
        return True
    if has_attachment and len(msg.split()) > 25:
        return True
    return False


TIER_QUICK = "quick"
TIER_DEEP = "deep"
TIER_ADVANCED = "advanced"

TIER_LABELS = {
    TIER_QUICK: "GPT-OSS (quick)",
    TIER_DEEP: "GPT-OSS (deep)",
    TIER_ADVANCED: "GLM-4.7 (advanced)",
}


def pick_model(message: str, *, has_attachment: bool = False, force_math: bool = False) -> tuple[str, str]:
    msg = (message or "").lower().strip()
    words = len(msg.split())
    advanced = model_advanced()
    standard = model_standard()
    fast = model_fast()

    if any(t in msg for t in OPUS_TRIGGERS):
        return advanced, TIER_ADVANCED
    if force_math and any(t in msg for t in ("proof", "theorem", "conjecture", "topology", "manifold")):
        return advanced, TIER_ADVANCED
    if has_attachment and words > 15:
        return standard, TIER_DEEP
    if any(t in msg for t in SONNET_TRIGGERS) or force_math:
        return standard, TIER_DEEP
    if words > 120 or (words > 40 and "?" in msg):
        return standard, TIER_DEEP
    if words <= 18 and not has_attachment:
        return fast, TIER_QUICK
    return standard, TIER_DEEP


def tier_label(model: str, tier_key: str | None = None) -> str:
    if tier_key:
        return TIER_LABELS.get(tier_key, tier_key)
    m = (model or "").lower()
    adv = model_advanced().lower()
    if m == adv or "glm" in m or "opus" in m:
        return TIER_LABELS[TIER_ADVANCED]
    if "haiku" in m or "sonnet" in m:
        return TIER_LABELS[TIER_DEEP] if "sonnet" in m else TIER_LABELS[TIER_QUICK]
    if "gpt-oss" in m:
        return TIER_LABELS[TIER_DEEP]
    return model or "unknown"
