import importlib
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from scigraph.alerts import AlertPayload, build_alert_payload, dispatch_webhook_alert
    from scigraph.config import SciGraphConfig, load_scigraph_config
    from scigraph.diagrams import export_graphviz_dot, export_mermaid_flowchart
    from scigraph.diff import diff_claim_graphs, export_bibtex, export_ris
    from scigraph.doctor import DoctorReport, run_doctor
    from scigraph.pipeline import PipelineConfig, PipelineSummary, run_pipeline
    from scigraph.provenance import (
        ProvenanceManifest,
        build_provenance_manifest,
        verify_provenance_manifest,
    )
    from scigraph.security import AuthGate, SlidingWindowRateLimiter
    from scigraph.server import SciGraphApp
    from scigraph.workspace import WorkspaceManager

# Lazy-loaded to avoid circular imports when `graph`/`ingest` import `scigraph.models`.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AlertPayload": ("scigraph.alerts", "AlertPayload"),
    "AuthGate": ("scigraph.security", "AuthGate"),
    "DoctorReport": ("scigraph.doctor", "DoctorReport"),
    "PipelineConfig": ("scigraph.pipeline", "PipelineConfig"),
    "PipelineSummary": ("scigraph.pipeline", "PipelineSummary"),
    "ProvenanceManifest": ("scigraph.provenance", "ProvenanceManifest"),
    "SciGraphApp": ("scigraph.server", "SciGraphApp"),
    "SciGraphConfig": ("scigraph.config", "SciGraphConfig"),
    "SlidingWindowRateLimiter": ("scigraph.security", "SlidingWindowRateLimiter"),
    "WorkspaceManager": ("scigraph.workspace", "WorkspaceManager"),
    "build_alert_payload": ("scigraph.alerts", "build_alert_payload"),
    "build_provenance_manifest": ("scigraph.provenance", "build_provenance_manifest"),
    "diff_claim_graphs": ("scigraph.diff", "diff_claim_graphs"),
    "dispatch_webhook_alert": ("scigraph.alerts", "dispatch_webhook_alert"),
    "export_bibtex": ("scigraph.diff", "export_bibtex"),
    "export_graphviz_dot": ("scigraph.diagrams", "export_graphviz_dot"),
    "export_mermaid_flowchart": ("scigraph.diagrams", "export_mermaid_flowchart"),
    "export_ris": ("scigraph.diff", "export_ris"),
    "load_scigraph_config": ("scigraph.config", "load_scigraph_config"),
    "run_doctor": ("scigraph.doctor", "run_doctor"),
    "run_pipeline": ("scigraph.pipeline", "run_pipeline"),
    "verify_provenance_manifest": ("scigraph.provenance", "verify_provenance_manifest"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def healthcheck() -> str:
    return "ok"


__all__ = [
    "AlertPayload",
    "AuthGate",
    "BenchmarkMetrics",
    "ClaimTuple",
    "ClaimVerificationResult",
    "ComparisonOperator",
    "ContradictionKind",
    "ContradictionPair",
    "DoctorReport",
    "EdgeRelation",
    "EffectDirection",
    "EvidenceEdge",
    "EvidenceSpan",
    "FalsifiableExperiment",
    "LayoutBlock",
    "Paper",
    "PaperSection",
    "PaperVerificationReport",
    "PipelineConfig",
    "PipelineSummary",
    "ProvenanceManifest",
    "SciGraphApp",
    "SciGraphConfig",
    "ScientificClaim",
    "SectionKind",
    "SlidingWindowRateLimiter",
    "StatisticalEvidence",
    "VerificationFailureReason",
    "WorkspaceManager",
    "build_alert_payload",
    "build_provenance_manifest",
    "diff_claim_graphs",
    "dispatch_webhook_alert",
    "export_bibtex",
    "export_graphviz_dot",
    "export_mermaid_flowchart",
    "export_ris",
    "healthcheck",
    "load_scigraph_config",
    "run_doctor",
    "run_pipeline",
    "verify_provenance_manifest",
]
