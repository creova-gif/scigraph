import re
import time
from collections.abc import Sequence

from scigraph.models import (
    DOI_PATTERN,
    ClaimVerificationResult,
    ComparisonOperator,
    Paper,
    PaperVerificationReport,
    ScientificClaim,
    VerificationFailureReason,
)

_P_TOKEN_PATTERN = re.compile(r"^p\s*(<=|<|=)\s*(0?\.\d+)$")
_N_TOKEN_PATTERN = re.compile(r"^[nN]\s*=\s*(\d+)$")


def verify_claim_verbatim(paper: Paper, claim: ScientificClaim) -> ClaimVerificationResult:
    failures: list[VerificationFailureReason] = []

    if not DOI_PATTERN.match(claim.doi) or not DOI_PATTERN.match(paper.doi):
        failures.append(VerificationFailureReason.INVALID_DOI_FORMAT)

    if claim.doi != paper.doi or claim.doi not in paper.full_text:
        failures.append(VerificationFailureReason.DOI_NOT_VERBATIM_IN_SOURCE)

    span = claim.evidence_span
    if span.start_char < 0 or span.end_char > len(paper.full_text):
        failures.append(VerificationFailureReason.SPAN_OUT_OF_BOUNDS)
    else:
        actual_slice = paper.full_text[span.start_char : span.end_char]
        if actual_slice != span.verbatim_text:
            failures.append(VerificationFailureReason.SPAN_TEXT_MISMATCH)

    stats = claim.statistics
    if stats.p_value_raw not in span.verbatim_text:
        failures.append(VerificationFailureReason.P_VALUE_NOT_VERBATIM)
    else:
        p_match = _P_TOKEN_PATTERN.match(stats.p_value_raw.strip())
        if p_match is None:
            failures.append(VerificationFailureReason.P_VALUE_NUMERIC_MISMATCH)
        else:
            op_raw, val_raw = p_match.group(1), p_match.group(2)
            expected_op = _parse_operator(op_raw)
            parsed_val = float(val_raw)
            if expected_op != stats.p_operator or abs(parsed_val - stats.p_value) > 1e-9:
                failures.append(VerificationFailureReason.P_VALUE_NUMERIC_MISMATCH)

    if stats.sample_size_raw not in span.verbatim_text:
        failures.append(VerificationFailureReason.SAMPLE_SIZE_NOT_VERBATIM)
    else:
        n_match = _N_TOKEN_PATTERN.match(stats.sample_size_raw.strip())
        if n_match is None or int(n_match.group(1)) != stats.sample_size:
            failures.append(VerificationFailureReason.SAMPLE_SIZE_NUMERIC_MISMATCH)

    return ClaimVerificationResult(
        claim_id=claim.claim_id,
        paper_id=paper.paper_id,
        verified=len(failures) == 0,
        failures=tuple(failures),
    )


def verify_paper_claims(
    paper: Paper,
    claims: Sequence[ScientificClaim],
) -> PaperVerificationReport:
    started = time.perf_counter()
    doi_verified = bool(DOI_PATTERN.match(paper.doi)) and (paper.doi in paper.full_text)

    results: list[ClaimVerificationResult] = []
    verified_claims: list[ScientificClaim] = []
    rejected_ids: list[str] = []

    for claim in claims:
        res = verify_claim_verbatim(paper, claim)
        results.append(res)
        if res.verified and doi_verified:
            verified_claims.append(claim)
        else:
            rejected_ids.append(claim.claim_id)

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return PaperVerificationReport(
        paper_id=paper.paper_id,
        doi=paper.doi,
        doi_verified=doi_verified,
        claim_results=tuple(results),
        verified_claims=tuple(verified_claims),
        rejected_claim_ids=tuple(rejected_ids),
        elapsed_ms=elapsed_ms,
    )


def _parse_operator(op_raw: str) -> ComparisonOperator:
    if op_raw == "=":
        return ComparisonOperator.EQ
    if op_raw == "<":
        return ComparisonOperator.LT
    return ComparisonOperator.LE
