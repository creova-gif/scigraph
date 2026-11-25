import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")


class SectionKind(StrEnum):
    TITLE = "title"
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"


class EffectDirection(StrEnum):
    INCREASES = "increases"
    DECREASES = "decreases"
    NO_EFFECT = "no_effect"


class ComparisonOperator(StrEnum):
    EQ = "="
    LT = "<"
    LE = "<="


class EdgeRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REPLICATES = "replicates"
    QUALIFIES = "qualifies"


class VerificationFailureReason(StrEnum):
    INVALID_DOI_FORMAT = "invalid_doi_format"
    DOI_NOT_VERBATIM_IN_SOURCE = "doi_not_verbatim_in_source"
    SPAN_OUT_OF_BOUNDS = "span_out_of_bounds"
    SPAN_TEXT_MISMATCH = "span_text_mismatch"
    P_VALUE_NOT_VERBATIM = "p_value_not_verbatim"
    P_VALUE_NUMERIC_MISMATCH = "p_value_numeric_mismatch"
    SAMPLE_SIZE_NOT_VERBATIM = "sample_size_not_verbatim"
    SAMPLE_SIZE_NUMERIC_MISMATCH = "sample_size_numeric_mismatch"


class ContradictionKind(StrEnum):
    DIRECT_DIRECTION_CONFLICT = "direct_direction_conflict"
    NULL_VS_SIGNIFICANT_CONFLICT = "null_vs_significant_conflict"
    CONDITION_DEPENDENT_DIVERGENCE = "condition_dependent_divergence"


class LayoutBlock(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    page_number: int = Field(ge=1)
    x0: float = Field(ge=0.0)
    y0: float = Field(ge=0.0)
    x1: float = Field(gt=0.0)
    y1: float = Field(gt=0.0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_coordinates(self) -> Self:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("Block bounding box requires x1 > x0 and y1 > y0")
        return self


class PaperSection(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    kind: SectionKind
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_offsets(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("Section end_char must be greater than start_char")
        return self


class Paper(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    paper_id: str = Field(min_length=1)
    doi: str = Field(min_length=5)
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = Field(min_length=1)
    publication_year: int = Field(ge=1900, le=2100)
    venue: str = Field(min_length=1)
    full_text: str = Field(min_length=1)
    sections: tuple[PaperSection, ...] = Field(default=())

    @field_validator("doi")
    @classmethod
    def _validate_doi(cls, value: str) -> str:
        if not DOI_PATTERN.match(value):
            raise ValueError(f"Invalid DOI format: {value}")
        return value


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    section: SectionKind
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    verbatim_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_span_length(self) -> Self:
        if self.end_char - self.start_char != len(self.verbatim_text):
            raise ValueError("EvidenceSpan character offsets must match verbatim_text length")
        return self


class ClaimTuple(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    intervention: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    direction: EffectDirection
    comparator: str = Field(default="control", min_length=1)

    def normalized_key(self) -> tuple[str, str, str]:
        return (
            _normalize_entity(self.intervention),
            _normalize_entity(self.condition),
            _normalize_entity(self.outcome),
        )

    def intervention_outcome_key(self) -> tuple[str, str]:
        return (
            _normalize_entity(self.intervention),
            _normalize_entity(self.outcome),
        )


class StatisticalEvidence(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    p_operator: ComparisonOperator
    p_value: float = Field(gt=0.0, le=1.0)
    p_value_raw: str = Field(min_length=3)
    sample_size: int = Field(ge=1)
    sample_size_raw: str = Field(min_length=3)
    effect_size_raw: str | None = None


class ScientificClaim(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    claim_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    doi: str = Field(min_length=5)
    claim_tuple: ClaimTuple
    statistics: StatisticalEvidence
    evidence_span: EvidenceSpan

    @field_validator("doi")
    @classmethod
    def _validate_claim_doi(cls, value: str) -> str:
        if not DOI_PATTERN.match(value):
            raise ValueError(f"Invalid DOI format: {value}")
        return value


class EvidenceEdge(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    edge_id: str = Field(min_length=1)
    source_claim_id: str = Field(min_length=1)
    target_claim_id: str = Field(min_length=1)
    relation: EdgeRelation
    rationale: str = Field(min_length=1)
    shared_intervention: str = Field(min_length=1)
    shared_outcome: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_distinct_claims(self) -> Self:
        if self.source_claim_id == self.target_claim_id:
            raise ValueError("EvidenceEdge cannot connect a claim to itself")
        return self


class ClaimVerificationResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    claim_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    verified: bool
    failures: tuple[VerificationFailureReason, ...] = Field(default=())


class PaperVerificationReport(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    paper_id: str = Field(min_length=1)
    doi: str = Field(min_length=1)
    doi_verified: bool
    claim_results: tuple[ClaimVerificationResult, ...]
    verified_claims: tuple[ScientificClaim, ...]
    rejected_claim_ids: tuple[str, ...]
    elapsed_ms: float = Field(ge=0.0)


class ContradictionPair(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    contradiction_id: str = Field(min_length=1)
    claim_a: ScientificClaim
    claim_b: ScientificClaim
    kind: ContradictionKind
    unsat_constraints: tuple[str, ...] = Field(min_length=1)
    discriminating_factor: str = Field(min_length=1)


class FalsifiableExperiment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    experiment_id: str = Field(min_length=1)
    contradiction_id: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    intervention: str = Field(min_length=1)
    stratified_conditions: tuple[str, ...] = Field(min_length=1)
    primary_outcome: str = Field(min_length=1)
    recommended_sample_size: int = Field(ge=10)
    alpha_threshold: float = Field(gt=0.0, lt=1.0)
    falsification_criterion: str = Field(min_length=1)


class BenchmarkMetrics(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    total_papers: int = Field(ge=1)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1_score: float = Field(ge=0.0, le=1.0)
    fabricated_dois_accepted: int = Field(ge=0)
    fabricated_p_values_accepted: int = Field(ge=0)
    adversarial_decoys_rejected: int = Field(ge=0)
    contradictions_detected: int = Field(ge=0)
    experiments_proposed: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0.0)


def _normalize_entity(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)
