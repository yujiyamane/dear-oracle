"""core/brier.py — Brier score functions (pure, no I/O).

Lower is better: 0 = perfect, 1 = worst for binary.
"""


def multiclass_brier(predicted: list[float], outcomes: list[int]) -> float:
    """Multi-class Brier score: (1/N) · Σ(p_i − o_i)²

    predicted: probabilities for each outcome (need not sum to 1 internally,
               but a well-formed distribution should)
    outcomes:  binary indicators — exactly one element must equal 1, rest 0
    """
    if len(predicted) != len(outcomes):
        raise ValueError(
            f"Length mismatch: predicted={len(predicted)}, outcomes={len(outcomes)}"
        )
    if sum(outcomes) != 1:
        raise ValueError(
            f"outcomes must sum to 1 (exactly one 1), got sum={sum(outcomes)}"
        )
    n = len(predicted)
    return sum((p - o) ** 2 for p, o in zip(predicted, outcomes)) / n


def binary_brier(p: float, occurred: bool) -> float:
    """Binary Brier score: (p − o)² where o = 1 if occurred else 0.

    Implemented as multiclass_brier([p, 1-p], [1,0] if occurred else [0,1]),
    which reduces to (p − o)².
    """
    return multiclass_brier([p, 1 - p], [1, 0] if occurred else [0, 1])
