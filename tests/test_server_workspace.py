from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scigraph.models import Paper
from scigraph.security import AuthGate, TokenPolicy, hash_bearer_token
from scigraph.server import SciGraphApp, load_token_policies
from scigraph.workspace import WorkspaceManager


def _make_paper(
    paper_id: str,
    doi: str,
    title: str,
    claim_sentence: str,
) -> Paper:
    full_text = f"Title: {title}\nDOI: {doi}\nResults: {claim_sentence}\n"
    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=("Alice Researcher", "Bob Scientist"),
        publication_year=2025,
        venue="Journal of Reproducibility",
        full_text=full_text,
    )


def test_load_token_policies_list_and_object_formats(tmp_path: Path) -> None:
    raw_token = "workspace-secret-token"
    digest = hash_bearer_token(raw_token)
    entry = {
        "token_sha256": digest,
        "org_id": "acme-org",
        "role": "ingestor",
        "label": "ci-ingestor",
    }

    list_path = tmp_path / "policies_list.json"
    list_path.write_text(json.dumps([entry]), encoding="utf-8")
    loaded_list = load_token_policies(list_path)
    assert len(loaded_list) == 1
    assert loaded_list[0].org_id == "acme-org"
    assert loaded_list[0].role == "ingestor"

    obj_path = tmp_path / "policies_obj.json"
    obj_path.write_text(json.dumps({"policies": [entry]}), encoding="utf-8")
    loaded_obj = load_token_policies(obj_path)
    assert loaded_obj == loaded_list

    gate = AuthGate(loaded_obj)
    decision = gate.authorize(f"Bearer {raw_token}", "ingestor")
    assert decision.allowed is True
    assert decision.org_id == "acme-org"


def test_load_token_policies_invalid_inputs_raise_value_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.json"
    with pytest.raises(ValueError):
        load_token_policies(missing_path)

    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_token_policies(bad_json_path)

    wrong_top_level = tmp_path / "wrong_top.json"
    wrong_top_level.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_token_policies(wrong_top_level)

    bad_schema_path = tmp_path / "bad_schema.json"
    bad_schema_path.write_text(
        json.dumps(
            [
                {
                    "token_sha256": "not-a-sha256",
                    "org_id": "org-1",
                    "role": "reader",
                    "label": "x",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_token_policies(bad_schema_path)


def test_workspace_bound_app_loads_existing_graph_db(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-alpha", "ws-main", "Main Workspace")
    seed_paper = _make_paper(
        paper_id="paper-seed",
        doi="10.1000/seed.1",
        title="Metformin increases AMPK phosphorylation",
        claim_sentence=(
            "Treatment with Metformin under normoxia increased AMPK phosphorylation "
            "compared with vehicle (d=0.85; n=48, p<0.001)."
        ),
    )
    wm.ingest_papers("org-alpha", "ws-main", [seed_paper])

    app = SciGraphApp(
        workspace_manager=wm,
        org_id="org-alpha",
        workspace_id="ws-main",
    )

    health_status, _, health_body = app.handle_request("GET", "/health")
    assert health_status == 200
    assert json.loads(health_body) == {
        "status": "ok",
        "version": "0.1.0",
        "papers": 1,
        "claims": 1,
    }

    claims_status, _, claims_body = app.handle_request("GET", "/api/v1/claims?paper_id=paper-seed")
    assert claims_status == 200
    claims_payload = json.loads(claims_body)
    assert claims_payload["count"] == 1
    assert claims_payload["claims"][0]["paper_id"] == "paper-seed"


def test_verify_persist_true_updates_graph_db_and_audit_log(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-beta", "ws-persist", "Persist Workspace")
    app = SciGraphApp(
        workspace_manager=wm,
        org_id="org-beta",
        workspace_id="ws-persist",
    )

    paper_ephemeral = _make_paper(
        paper_id="paper-ephemeral",
        doi="10.2000/ephem.1",
        title="Ephemeral study",
        claim_sentence=(
            "Treatment with Caffeine under normoxia increased alertness "
            "compared with placebo (d=0.50; n=40, p=0.01)."
        ),
    )
    ephem_body = json.dumps({"papers": [paper_ephemeral.model_dump(mode="json")]}).encode("utf-8")
    ephem_status, _, _ = app.handle_request("POST", "/api/v1/verify", ephem_body)
    assert ephem_status == 200
    assert len(wm.load_graph("org-beta", "ws-persist").papers) == 0

    paper_persisted = _make_paper(
        paper_id="paper-persisted",
        doi="10.2000/persist.2",
        title="Rapamycin extends lifespan",
        claim_sentence=(
            "Treatment with Rapamycin under standard diet increased median lifespan "
            "compared with control (d=0.70; n=120, p<0.001)."
        ),
    )
    persist_body = json.dumps({"papers": [paper_persisted.model_dump(mode="json")]}).encode("utf-8")
    status, ctype, body = app.handle_request(
        "POST",
        "/api/v1/verify?persist=true",
        persist_body,
    )
    assert status == 200
    assert ctype == "application/json"
    parsed = json.loads(body)
    assert len(parsed["reports"]) == 1
    assert len(parsed["reports"][0]["verified_claims"]) == 1

    # In-memory app.graph is updated immediately.
    health_status, _, health_body = app.handle_request("GET", "/health")
    assert health_status == 200
    assert json.loads(health_body)["papers"] == 1
    assert json.loads(health_body)["claims"] == 1

    # Persisted graph.db reflects the new paper and claim.
    reloaded = wm.load_graph("org-beta", "ws-persist")
    assert any(p.paper_id == "paper-persisted" for p in reloaded.papers)
    assert len(reloaded.claims) == 1

    # Audit log records the ingest event.
    events = wm.read_audit_log("org-beta", "ws-persist")
    ingest_events = [evt for evt in events if evt.action == "ingest"]
    assert len(ingest_events) == 1
    assert ingest_events[0].paper_count == 1
    assert ingest_events[0].claim_count == 1
    assert ingest_events[0].status == "ok"


def test_verify_persist_true_without_bound_workspace_returns_400(tmp_path: Path) -> None:
    paper = _make_paper(
        paper_id="paper-unbound",
        doi="10.3000/unbound.1",
        title="Unbound verify test",
        claim_sentence=(
            "Treatment with Aspirin under normoxia decreased platelet aggregation "
            "compared with placebo (d=0.90; n=64, p<0.001)."
        ),
    )
    payload = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")

    unbound_app = SciGraphApp()
    status, ctype, body = unbound_app.handle_request(
        "POST",
        "/api/v1/verify?persist=true",
        payload,
    )
    assert status == 400
    assert ctype == "application/json"
    assert "error" in json.loads(body)

    wm = WorkspaceManager(tmp_path)
    partial_app = SciGraphApp(workspace_manager=wm, org_id="org-only")
    p_status, _, p_body = partial_app.handle_request(
        "POST",
        "/api/v1/verify?persist=true",
        payload,
    )
    assert p_status == 400
    assert "error" in json.loads(p_body)

    bad_param_status, _, bad_param_body = unbound_app.handle_request(
        "POST",
        "/api/v1/verify?persist=maybe",
        payload,
    )
    assert bad_param_status == 400
    assert "error" in json.loads(bad_param_body)


def test_workspace_org_isolation_and_deleted_workspace_errors(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-alpha", "ws-1", "Alpha Workspace")
    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token("alpha-reader"),
                org_id="org-alpha",
                role="ingestor",
                label="alpha",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token("beta-ingestor"),
                org_id="org-beta",
                role="ingestor",
                label="beta",
            ),
        ]
    )
    app = SciGraphApp(
        auth_gate=gate,
        workspace_manager=wm,
        org_id="org-alpha",
        workspace_id="ws-1",
    )

    cross_status, _, cross_body = app.handle_request(
        "GET",
        "/api/v1/claims",
        incoming_header="Bearer beta-ingestor",
    )
    assert cross_status == 403
    assert "org_id" in json.loads(cross_body)["error"]

    ok_status, _, _ = app.handle_request(
        "GET",
        "/api/v1/claims",
        incoming_header="Bearer alpha-reader",
    )
    assert ok_status == 200

    shutil.rmtree(tmp_path / "org-alpha" / "ws-1")
    paper = _make_paper(
        paper_id="paper-missing",
        doi="10.3000/missing.1",
        title="Deleted workspace test",
        claim_sentence=(
            "Treatment with Aspirin under normoxia decreased platelet aggregation "
            "compared with placebo (d=0.90; n=64, p<0.001)."
        ),
    )
    payload = json.dumps({"papers": [paper.model_dump(mode="json")]}).encode("utf-8")
    missing_status, _, missing_body = app.handle_request(
        "POST",
        "/api/v1/verify?persist=true",
        payload,
        incoming_header="Bearer alpha-reader",
    )
    assert missing_status == 404
    assert "error" in json.loads(missing_body)
