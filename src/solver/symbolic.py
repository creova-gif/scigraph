import math
import re
from collections.abc import Sequence
from itertools import combinations
from typing import assert_never

from graph.claim_graph import ClaimGraph
from scigraph.models import (
    ContradictionKind,
    ContradictionPair,
    EffectDirection,
    FalsifiableExperiment,
    ScientificClaim,
    _normalize_entity,
)
from solver.regime import compute_regime_delta

_D_EFFECT_PATTERN = re.compile(r"\b(?:d|diff)\s*=\s*(?P<val>[+-]?\d+(?:\.\d+)?)")
_FOLD_PATTERN = re.compile(r"\bfold\s*=\s*(?P<val>[+-]?\d+(?:\.\d+)?)x")
_RATIO_PATTERN = re.compile(r"\b(?:or|hr|ratio)\s*=\s*(?P<val>[+-]?\d+(?:\.\d+)?)")
_PCT_PATTERN = re.compile(r"\b(?:reduction|delta)\s*=\s*(?P<val>[+-]?\d+(?:\.\d+)?)%")

_Z_ALPHA_001 = 2.5758
_Z_POWER_090 = 1.2816


def parse_standardized_effect_size(effect_size_raw: str | None) -> float | None:
    if effect_size_raw is None:
        return None
    text = effect_size_raw.strip()

    d_match = _D_EFFECT_PATTERN.search(text)
    if d_match is not None:
        return max(0.10, min(3.0, abs(float(d_match.group("val")))))

    fold_match = _FOLD_PATTERN.search(text)
    if fold_match is not None:
        val = float(fold_match.group("val"))
        if val <= 0.0:
            return None
        return max(0.10, min(3.0, abs(math.log(val))))

    ratio_match = _RATIO_PATTERN.search(text)
    if ratio_match is not None:
        val = float(ratio_match.group("val"))
        if val <= 0.0:
            return None
        return max(0.10, min(3.0, abs(math.log(val)) * 0.55))

    pct_match = _PCT_PATTERN.search(text)
    if pct_match is not None:
        pct = float(pct_match.group("val"))
        return max(0.20, min(2.0, abs(pct) / 50.0))

    return None


def compute_powered_sample_size(
    claim_a: ScientificClaim,
    claim_b: ScientificClaim,
) -> int:
    base_n = max(40, max(claim_a.statistics.sample_size, claim_b.statistics.sample_size) * 2)
    d_a = parse_standardized_effect_size(claim_a.statistics.effect_size_raw)
    d_b = parse_standardized_effect_size(claim_b.statistics.effect_size_raw)

    present = [d for d in (d_a, d_b) if d is not None]
    if not present:
        return base_n

    d_eff = max(0.20, min(present))
    n_per_arm = math.ceil(2.0 * ((_Z_ALPHA_001 + _Z_POWER_090) / d_eff) ** 2)
    total_powered_n = min(2000, n_per_arm * 2)
    return max(base_n, total_powered_n)


def direction_to_symbolic_int(direction: EffectDirection) -> int:
    match direction:
        case EffectDirection.INCREASES:
            return 1
        case EffectDirection.DECREASES:
            return -1
        case EffectDirection.NO_EFFECT:
            return 0
        case _ as unreachable:
            assert_never(unreachable)


def check_claim_set_satisfiability(
    claims: Sequence[ScientificClaim],
) -> tuple[bool, tuple[str, ...]]:
    assignments: dict[tuple[str, str, str], tuple[int, ScientificClaim]] = {}
    unsat_core: list[str] = []

    for claim in claims:
        key = claim.claim_tuple.normalized_key()
        val = direction_to_symbolic_int(claim.claim_tuple.direction)
        if key not in assignments:
            assignments[key] = (val, claim)
        else:
            existing_val, existing_claim = assignments[key]
            if existing_val != val:
                constraint_str = (
                    f"UNSAT[Dir({key[0]!r}, {key[1]!r}, {key[2]!r}): "
                    f"{existing_claim.claim_id}=={existing_val} && "
                    f"{claim.claim_id}=={val}]"
                )
                unsat_core.append(constraint_str)

    return (len(unsat_core) == 0, tuple(unsat_core))


def detect_contradictions(graph: ClaimGraph) -> tuple[ContradictionPair, ...]:
    by_io: dict[tuple[str, str], list[ScientificClaim]] = {}
    for claim in graph.claims:
        by_io.setdefault(claim.claim_tuple.intervention_outcome_key(), []).append(claim)

    contradictions: list[ContradictionPair] = []
    counter = 1

    for (norm_i, norm_o), group in sorted(by_io.items()):
        for claim_a, claim_b in combinations(group, 2):
            val_a = direction_to_symbolic_int(claim_a.claim_tuple.direction)
            val_b = direction_to_symbolic_int(claim_b.claim_tuple.direction)
            if val_a == val_b:
                continue

            cond_a = _normalize_entity(claim_a.claim_tuple.condition)
            cond_b = _normalize_entity(claim_b.claim_tuple.condition)

            unsat: tuple[str, ...]
            if cond_a == cond_b:
                if val_a != 0 and val_b != 0:
                    kind = ContradictionKind.DIRECT_DIRECTION_CONFLICT
                    discriminating = (
                        f"Identical condition '{claim_a.claim_tuple.condition}' "
                        f"with sample sizes n={claim_a.statistics.sample_size} vs "
                        f"n={claim_b.statistics.sample_size} and comparators "
                        f"'{claim_a.claim_tuple.comparator}' vs '{claim_b.claim_tuple.comparator}'"
                    )
                else:
                    kind = ContradictionKind.NULL_VS_SIGNIFICANT_CONFLICT
                    discriminating = (
                        f"Statistical power divergence under '{claim_a.claim_tuple.condition}' "
                        f"(n={claim_a.statistics.sample_size}, {claim_a.statistics.p_value_raw} vs "
                        f"n={claim_b.statistics.sample_size}, {claim_b.statistics.p_value_raw})"
                    )
                unsat = (
                    f"Dir({norm_i}, {cond_a}, {norm_o}) == {val_a} [{claim_a.claim_id}]",
                    f"Dir({norm_i}, {cond_b}, {norm_o}) == {val_b} [{claim_b.claim_id}]",
                )
            else:
                kind = ContradictionKind.CONDITION_DEPENDENT_DIVERGENCE
                discriminating = (
                    f"Regime shift between '{claim_a.claim_tuple.condition}' "
                    f"and '{claim_b.claim_tuple.condition}'"
                )
                delta = compute_regime_delta(
                    claim_a.claim_tuple.condition,
                    claim_b.claim_tuple.condition,
                )
                if delta is not None:
                    discriminating = f"{discriminating} | {delta}"
                unsat = (
                    f"Dir({norm_i}, {cond_a}, {norm_o}) == {val_a} [{claim_a.claim_id}]",
                    f"Dir({norm_i}, {cond_b}, {norm_o}) == {val_b} [{claim_b.claim_id}]",
                    f"ConditionMod({cond_a} != {cond_b})",
                )

            contradictions.append(
                ContradictionPair(
                    contradiction_id=f"contra-{counter:04d}",
                    claim_a=claim_a,
                    claim_b=claim_b,
                    kind=kind,
                    unsat_constraints=unsat,
                    discriminating_factor=discriminating,
                )
            )
            counter += 1

    return tuple(contradictions)


def propose_falsifiable_experiments(
    contradictions: Sequence[ContradictionPair],
) -> tuple[FalsifiableExperiment, ...]:
    experiments: list[FalsifiableExperiment] = []
    for idx, pair in enumerate(contradictions, start=1):
        ca = pair.claim_a
        cb = pair.claim_b
        recommended_n = compute_powered_sample_size(ca, cb)

        cond_a = ca.claim_tuple.condition
        cond_b = cb.claim_tuple.condition
        if _normalize_entity(cond_a) == _normalize_entity(cond_b):
            arms = (
                f"{cond_a} vs {ca.claim_tuple.comparator}",
                f"{cond_b} vs {cb.claim_tuple.comparator} (powered replication)",
            )
            hypothesis = (
                f"Under {cond_a}, {ca.claim_tuple.intervention} produces a net "
                f"{ca.claim_tuple.direction.value} in {ca.claim_tuple.outcome} at n={recommended_n}"
            )
            falsification = (
                f"Falsified if {ca.claim_tuple.outcome} exhibits "
                f"{cb.claim_tuple.direction.value} with p < 0.01 across n >= {recommended_n}"
            )
        else:
            arms = (cond_a, cond_b)
            hypothesis = (
                f"Condition modifier ({cond_a} vs {cond_b}) reverses the effect of "
                f"{ca.claim_tuple.intervention} on {ca.claim_tuple.outcome}"
            )
            falsification = (
                f"Falsified if the interaction term ({ca.claim_tuple.intervention} x condition) "
                f"yields p >= 0.01 or identical direction in both {cond_a} and {cond_b} arms"
            )

        experiments.append(
            FalsifiableExperiment(
                experiment_id=f"exp-{idx:04d}",
                contradiction_id=pair.contradiction_id,
                hypothesis=hypothesis,
                intervention=ca.claim_tuple.intervention,
                stratified_conditions=arms,
                primary_outcome=ca.claim_tuple.outcome,
                recommended_sample_size=recommended_n,
                alpha_threshold=0.01,
                falsification_criterion=falsification,
            )
        )

    return tuple(experiments)
