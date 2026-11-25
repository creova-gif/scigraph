from scigraph.models import (
    BenchmarkMetrics,
    ClaimTuple,
    ClaimVerificationResult,
    ComparisonOperator,
    ContradictionKind,
    ContradictionPair,
    EdgeRelation,
    EffectDirection,
    EvidenceEdge,
    EvidenceSpan,
    FalsifiableExperiment,
    LayoutBlock,
    Paper,
    PaperSection,
    PaperVerificationReport,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
    VerificationFailureReason,
)


def healthcheck() -> str:
    return "ok"


__all__ = [
    "BenchmarkMetrics",
    "ClaimTuple",
    "ClaimVerificationResult",
    "ComparisonOperator",
    "ContradictionKind",
    "ContradictionPair",
    "EdgeRelation",
    "EffectDirection",
    "EvidenceEdge",
    "EvidenceSpan",
    "FalsifiableExperiment",
    "LayoutBlock",
    "Paper",
    "PaperSection",
    "PaperVerificationReport",
    "ScientificClaim",
    "SectionKind",
    "StatisticalEvidence",
    "VerificationFailureReason",
    "healthcheck",
]
