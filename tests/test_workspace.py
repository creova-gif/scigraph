from __future__ import annotations

import json
from pathlib import Path

import pytest

import scigraph.workspace as workspace_module
from ingest.extractor import extract_claims_from_paper
from scigraph.cli import main
from scigraph.models import EdgeRelation, Paper, ScientificClaim
from scigraph.workspace import AuditEvent, WorkspaceConfig, WorkspaceManager


def _make_paper(
    *,
    paper_id: str,
    doi: str,
    sentence: str,
    include_doi_in_text: bool = True,
) -> Paper:
    header = f"DOI: {doi}\n" if include_doi_in_text else "DOI: redacted\n"
    full_text = f"{header}Results\n{sentence}"
    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=f"Study {paper_id}",
        authors=("Ada Lovelace",),
        publication_year=2025,
        venue="Journal of Deterministic Tests",
        full_text=full_text,
    )


def test_init_get_and_list_workspaces(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    assert manager.list_workspaces() == []

    cfg_a1 = manager.init_workspace("org-alpha", "ws-one", "Alpha One")
    cfg_a2 = manager.init_workspace("org-alpha", "ws-two", "Alpha Two")
    cfg_b1 = manager.init_workspace("org-beta", "ws-one", "Beta One")

    assert cfg_a1.org_id == "org-alpha"
    assert cfg_a1.workspace_id == "ws-one"
    assert cfg_a1.name == "Alpha One"
    assert (tmp_path / "org-alpha" / "ws-one" / "workspace.json").is_file()
    assert (tmp_path / "org-alpha" / "ws-one" / "graph.db").is_file()
    assert (tmp_path / "org-alpha" / "ws-one" / "audit.jsonl").is_file()

    loaded = manager.get_workspace("org-alpha", "ws-one")
    assert loaded == cfg_a1

    alpha_list = manager.list_workspaces(org_id="org-alpha")
    assert [c.workspace_id for c in alpha_list] == ["ws-one", "ws-two"]
    assert all(c.org_id == "org-alpha" for c in alpha_list)

    all_list = manager.list_workspaces()
    assert [(c.org_id, c.workspace_id) for c in all_list] == [
        ("org-alpha", "ws-one"),
        ("org-alpha", "ws-two"),
        ("org-beta", "ws-one"),
    ]
    assert cfg_a2 in all_list
    assert cfg_b1 in all_list

    with pytest.raises(FileExistsError):
        manager.init_workspace("org-alpha", "ws-one", "Duplicate")

    with pytest.raises(FileNotFoundError):
        manager.get_workspace("org-alpha", "ws-missing")


def test_tenant_isolation_across_orgs(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-alpha", "shared-name", "Alpha Shared")
    manager.init_workspace("org-beta", "shared-name", "Beta Shared")

    paper_alpha = _make_paper(
        paper_id="p-alpha-1",
        doi="10.1234/alpha.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.4 mmol/L; n = 120, p < 0.001)."
        ),
    )
    paper_beta = _make_paper(
        paper_id="p-beta-1",
        doi="10.1234/beta.001",
        sentence=(
            "Treatment with Rapamycin under hypoxia increased autophagy flux "
            "compared with vehicle (1.8-fold; n = 45, p = 0.004)."
        ),
    )

    manager.ingest_papers("org-alpha", "shared-name", [paper_alpha])
    manager.ingest_papers("org-beta", "shared-name", [paper_beta])

    graph_alpha = manager.load_graph("org-alpha", "shared-name")
    graph_beta = manager.load_graph("org-beta", "shared-name")

    assert [p.paper_id for p in graph_alpha.papers] == ["p-alpha-1"]
    assert [c.claim_tuple.intervention for c in graph_alpha.claims] == ["Metformin"]

    assert [p.paper_id for p in graph_beta.papers] == ["p-beta-1"]
    assert [c.claim_tuple.intervention for c in graph_beta.claims] == ["Rapamycin"]

    alpha_events = manager.read_audit_log("org-alpha", "shared-name")
    beta_events = manager.read_audit_log("org-beta", "shared-name")
    assert all(e.org_id == "org-alpha" for e in alpha_events)
    assert all(e.org_id == "org-beta" for e in beta_events)


@pytest.mark.parametrize(
    "bad_slug",
    [
        "",
        "a",
        "-leading-dash",
        ".leading-dot",
        "../escape",
        "org..sub",
        "org/sub",
        "org\\sub",
        "org with space",
        "org\ttab",
        "a" * 65,
    ],
)
def test_invalid_slugs_and_path_traversal_raise_value_error(
    tmp_path: Path,
    bad_slug: str,
) -> None:
    manager = WorkspaceManager(tmp_path)

    with pytest.raises(ValueError):
        WorkspaceConfig(
            org_id=bad_slug,
            workspace_id="valid-ws",
            name="Bad",
            created_at_utc="2026-01-01T00:00:00+00:00",
        )

    with pytest.raises(ValueError):
        AuditEvent(
            event_id="evt-1",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            org_id="valid-org",
            workspace_id=bad_slug,
            action="query",
            paper_count=0,
            claim_count=0,
            status="ok",
            detail="test",
        )

    with pytest.raises(ValueError):
        manager._resolve_workspace_dir(bad_slug, "valid-ws")

    with pytest.raises(ValueError):
        manager._resolve_workspace_dir("valid-org", bad_slug)

    with pytest.raises(ValueError):
        manager.init_workspace(bad_slug, "valid-ws", "Bad")

    with pytest.raises(ValueError):
        manager.list_workspaces(org_id=bad_slug)


def test_ingest_papers_and_load_graph_incremental(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-lab", "metformin-study", "Metformin Study")

    p1 = _make_paper(
        paper_id="p-001",
        doi="10.5555/study.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.2 mmol/L; n = 80, p < 0.01)."
        ),
    )
    p2 = _make_paper(
        paper_id="p-002",
        doi="10.5555/study.002",
        sentence=(
            "Treatment with Metformin under normoxia increased blood glucose "
            "compared with placebo (mean diff +0.9 mmol/L; n = 64, p = 0.02)."
        ),
    )

    graph_after_first, reports_first = manager.ingest_papers("org-lab", "metformin-study", [p1])
    assert len(reports_first) == 1
    assert reports_first[0].doi_verified is True
    assert len(reports_first[0].verified_claims) == 1
    assert len(graph_after_first.papers) == 1
    assert len(graph_after_first.claims) == 1
    assert len(graph_after_first.edges) == 0

    graph_after_second, reports_second = manager.ingest_papers("org-lab", "metformin-study", [p2])
    assert len(reports_second) == 1
    assert len(reports_second[0].verified_claims) == 1
    assert len(graph_after_second.papers) == 2
    assert len(graph_after_second.claims) == 2
    assert len(graph_after_second.edges) == 1
    assert graph_after_second.edges[0].relation == EdgeRelation.CONTRADICTS

    reloaded = manager.load_graph("org-lab", "metformin-study")
    assert len(reloaded.papers) == 2
    assert len(reloaded.claims) == 2
    assert len(reloaded.edges) == 1
    assert reloaded.edges[0].relation == EdgeRelation.CONTRADICTS


def test_audit_jsonl_logging_and_rejected_ingest(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-audit", "ws-audit", "Audit Workspace")

    rejected_paper = _make_paper(
        paper_id="p-bad-doi",
        doi="10.9999/missing.doi",
        sentence=(
            "Treatment with Aspirin under baseline decreased platelet aggregation "
            "compared with control (n = 50, p < 0.05)."
        ),
        include_doi_in_text=False,
    )
    graph, reports = manager.ingest_papers("org-audit", "ws-audit", [rejected_paper])
    assert len(reports) == 1
    assert reports[0].doi_verified is False
    assert len(reports[0].verified_claims) == 0
    assert len(reports[0].rejected_claim_ids) == 1
    assert len(graph.claims) == 0

    custom_event = manager.record_event(
        org_id="org-audit",
        workspace_id="ws-audit",
        action="contradiction_scan",
        paper_count=1,
        claim_count=0,
        status="ok",
        detail="Scanned workspace for contradictions",
    )
    assert custom_event.action == "contradiction_scan"

    events = manager.read_audit_log("org-audit", "ws-audit")
    assert [e.action for e in events] == ["verify", "ingest", "contradiction_scan"]
    assert events[0].status == "ok"
    assert events[1].status == "rejected"
    assert events[1].paper_count == 1
    assert events[1].claim_count == 0
    assert events[2] == custom_event

    audit_lines = (
        (tmp_path / "org-audit" / "ws-audit" / "audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(audit_lines) == 3
    for line in audit_lines:
        parsed = AuditEvent.model_validate_json(line)
        assert parsed.org_id == "org-audit"
        assert parsed.workspace_id == "ws-audit"


def test_unverified_doi_paper_gated_out_of_graph_papers(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-gate", "ws-gate", "DOI Gate Workspace")

    unverified_paper = _make_paper(
        paper_id="p-unverified",
        doi="10.9999/unverified.001",
        sentence=(
            "Treatment with Aspirin under baseline decreased platelet aggregation "
            "compared with control (n = 50, p < 0.05)."
        ),
        include_doi_in_text=False,
    )
    verified_paper = _make_paper(
        paper_id="p-verified",
        doi="10.9999/verified.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.4 mmol/L; n = 120, p < 0.001)."
        ),
        include_doi_in_text=True,
    )

    graph, reports = manager.ingest_papers(
        "org-gate",
        "ws-gate",
        [unverified_paper, verified_paper],
    )
    assert [r.doi_verified for r in reports] == [False, True]
    assert [p.paper_id for p in graph.papers] == ["p-verified"]
    assert len(graph.claims) == 1

    reloaded = manager.load_graph("org-gate", "ws-gate")
    assert [p.paper_id for p in reloaded.papers] == ["p-verified"]
    assert (tmp_path / "org-gate" / "ws-gate" / ".workspace.lock").is_file()


def test_read_audit_log_filtering_and_limit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-filter", "ws-filter", "Filter Workspace")

    e1 = manager.record_event(
        org_id="org-filter",
        workspace_id="ws-filter",
        action="query",
        paper_count=0,
        claim_count=1,
        status="ok",
        detail="query-1",
    )
    e2 = manager.record_event(
        org_id="org-filter",
        workspace_id="ws-filter",
        action="export",
        paper_count=1,
        claim_count=2,
        status="ok",
        detail="export-1",
    )
    e3 = manager.record_event(
        org_id="org-filter",
        workspace_id="ws-filter",
        action="query",
        paper_count=0,
        claim_count=3,
        status="ok",
        detail="query-2",
    )
    e4 = manager.record_event(
        org_id="org-filter",
        workspace_id="ws-filter",
        action="query",
        paper_count=0,
        claim_count=4,
        status="ok",
        detail="query-3",
    )

    all_events = manager.read_audit_log("org-filter", "ws-filter")
    assert len(all_events) == 5
    assert all_events[0].action == "verify"
    assert all_events[1:] == [e1, e2, e3, e4]
    assert manager.read_audit_log("org-filter", "ws-filter", action="query") == [e1, e3, e4]
    assert manager.read_audit_log("org-filter", "ws-filter", action="export") == [e2]
    assert manager.read_audit_log("org-filter", "ws-filter", limit=2) == [e3, e4]
    assert manager.read_audit_log("org-filter", "ws-filter", action="query", limit=2) == [e3, e4]

    for bad_limit in (0, -1):
        with pytest.raises(ValueError, match="limit must be >= 1"):
            manager.read_audit_log("org-filter", "ws-filter", limit=bad_limit)

    rc = main(
        [
            "workspace",
            "audit",
            "--root",
            str(tmp_path),
            "--org",
            "org-filter",
            "--workspace",
            "ws-filter",
            "--action",
            "query",
            "--limit",
            "2",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert [item["detail"] for item in payload] == ["query-2", "query-3"]

    rc_bad = main(
        [
            "workspace",
            "audit",
            "--root",
            str(tmp_path),
            "--org",
            "org-filter",
            "--workspace",
            "ws-filter",
            "--limit",
            "0",
        ]
    )
    bad_captured = capsys.readouterr()
    assert rc_bad == 2
    assert "limit must be >= 1" in bad_captured.err


def test_reimport_revised_paper_removes_obsolete_claims(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-rev", "ws-rev", "Revision Workspace")

    paper_v1 = _make_paper(
        paper_id="p-rev-001",
        doi="10.5555/rev.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.4 mmol/L; n = 120, p < 0.001).\n"
            "Treatment with Metformin under hypoxia increased lactate "
            "compared with placebo (mean diff +0.6 mmol/L; n = 120, p = 0.01)."
        ),
    )
    graph_v1, reports_v1 = manager.ingest_papers("org-rev", "ws-rev", [paper_v1])
    assert len(reports_v1[0].verified_claims) == 2
    assert len(graph_v1.claims) == 2

    paper_v2 = _make_paper(
        paper_id="p-rev-001",
        doi="10.5555/rev.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.4 mmol/L; n = 120, p < 0.001)."
        ),
    )
    graph_v2, reports_v2 = manager.ingest_papers("org-rev", "ws-rev", [paper_v2])
    assert len(reports_v2[0].verified_claims) == 1
    assert len(graph_v2.papers) == 1
    assert [c.claim_tuple.outcome for c in graph_v2.claims] == ["blood glucose"]

    reloaded_v2 = manager.load_graph("org-rev", "ws-rev")
    assert [c.claim_tuple.outcome for c in reloaded_v2.claims] == ["blood glucose"]

    paper_v3_zero_claims = _make_paper(
        paper_id="p-rev-001",
        doi="10.5555/rev.001",
        sentence="No quantitative treatment effects were observed in this revision.",
    )
    graph_v3, reports_v3 = manager.ingest_papers(
        "org-rev", "ws-rev", [paper_v3_zero_claims]
    )
    assert reports_v3[0].doi_verified is True
    assert len(reports_v3[0].verified_claims) == 0
    assert len(graph_v3.papers) == 1
    assert len(graph_v3.claims) == 0

    reloaded_v3 = manager.load_graph("org-rev", "ws-rev")
    assert len(reloaded_v3.papers) == 1
    assert len(reloaded_v3.claims) == 0


def test_interleaved_ingest_papers_do_not_overwrite_each_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path)
    manager.init_workspace("org-interleave", "ws-interleave", "Interleave Workspace")

    paper_first = _make_paper(
        paper_id="p-first",
        doi="10.5555/interleave.001",
        sentence=(
            "Treatment with Metformin under normoxia decreased blood glucose "
            "compared with placebo (mean diff -1.2 mmol/L; n = 80, p < 0.01)."
        ),
    )
    paper_second = _make_paper(
        paper_id="p-second",
        doi="10.5555/interleave.002",
        sentence=(
            "Treatment with Metformin under normoxia increased blood glucose "
            "compared with placebo (mean diff +0.9 mmol/L; n = 64, p = 0.02)."
        ),
    )

    interleaved_once = False

    def interleaved_extract(paper: Paper) -> tuple[ScientificClaim, ...]:
        nonlocal interleaved_once
        if paper.paper_id == "p-first" and not interleaved_once:
            interleaved_once = True
            manager.ingest_papers("org-interleave", "ws-interleave", [paper_second])
        return extract_claims_from_paper(paper)

    monkeypatch.setattr(workspace_module, "extract_claims_from_paper", interleaved_extract)

    graph_after_first, _ = manager.ingest_papers(
        "org-interleave", "ws-interleave", [paper_first]
    )
    assert interleaved_once is True
    assert sorted(p.paper_id for p in graph_after_first.papers) == ["p-first", "p-second"]
    assert sorted(c.paper_id for c in graph_after_first.claims) == ["p-first", "p-second"]
    assert len(graph_after_first.edges) == 1
    assert graph_after_first.edges[0].relation == EdgeRelation.CONTRADICTS

    reloaded = manager.load_graph("org-interleave", "ws-interleave")
    assert sorted(p.paper_id for p in reloaded.papers) == ["p-first", "p-second"]
    assert sorted(c.paper_id for c in reloaded.claims) == ["p-first", "p-second"]
    assert len(reloaded.edges) == 1
