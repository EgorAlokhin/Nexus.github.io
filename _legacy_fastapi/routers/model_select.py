"""Pick Claude model tier from message complexity."""

MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS = "claude-opus-4-8"

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
    """Complex, factual, or research-heavy prompts should use web search."""
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


def pick_model(message: str, *, has_attachment: bool = False, force_math: bool = False) -> str:
    msg = (message or "").lower().strip()
    words = len(msg.split())

    if any(t in msg for t in OPUS_TRIGGERS):
        return MODEL_OPUS
    if force_math and any(t in msg for t in ("proof", "theorem", "conjecture", "topology", "manifold")):
        return MODEL_OPUS
    if has_attachment and words > 15:
        return MODEL_SONNET
    if any(t in msg for t in SONNET_TRIGGERS) or force_math:
        return MODEL_SONNET
    if words > 120 or (words > 40 and "?" in msg):
        return MODEL_SONNET
    if words <= 18 and not has_attachment:
        return MODEL_HAIKU
    return MODEL_SONNET


def tier_label(model: str) -> str:
    if "opus" in model:
        return "opus"
    if "sonnet" in model:
        return "sonnet"
    if "haiku" in model:
        return "haiku"
    return model
