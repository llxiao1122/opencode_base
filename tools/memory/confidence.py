"""
memory/confidence.py — Rule-based confidence scoring.

No LLM. Sample size + success rate - conflicts.
Range: 0.0 ~ 0.95 (deliberately capped — system should never be fully certain).
"""


def calculate(samples: int, success_rate: float, conflicts: int = 0) -> float:
    """Return confidence score based on evidence quantity and quality.

    Args:
        samples:      number of observed instances
        success_rate: proportion of positive outcomes (0.0 ~ 1.0)
        conflicts:    number of counter-examples

    Returns:
        confidence (0.0 ~ 0.95)
    """
    score = 0.0

    # Sample size contribution (max 0.30)
    if samples >= 30:
        score += 0.30
    elif samples >= 10:
        score += 0.25
    elif samples >= 5:
        score += 0.15

    # Success rate contribution (max 0.55)
    score += success_rate * 0.55

    # Counter-example penalty (0.05 each)
    score -= conflicts * 0.05

    return round(max(0.0, min(0.95, score)), 2)
