from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from graph.claim_graph import ClaimGraph
from scigraph.models import Paper
from scigraph.security import AuthGate, TokenPolicy, hash_bearer_token
from scigraph.server import SciGraphApp, create_http_server, load_token_policies
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


def test_app_init_rejects_both_graph_and_workspace_manager(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-dup", "ws-dup", "Dup Workspace")
    graph = ClaimGraph()
    with pytest.raises(
        ValueError,
        match="Cannot configure both an explicit graph and a workspace_manager",
    ):
        SciGraphApp(graph, workspace_manager=wm, org_id="org-dup", workspace_id="ws-dup")


def test_audit_endpoint_returns_events_with_filters_and_auth(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-audit", "ws-audit", "Audit Workspace")
    paper_one = _make_paper(
        paper_id="paper-audit-1",
        doi="10.4000/audit.1",
        title="Audit Study One",
        claim_sentence=(
            "Treatment with Metformin under normoxia increased AMPK phosphorylation "
            "compared with vehicle (d=0.80; n=40, p<0.001)."
        ),
    )
    paper_two = _make_paper(
        paper_id="paper-audit-2",
        doi="10.4000/audit.2",
        title="Audit Study Two",
        claim_sentence=(
            "Treatment with Rapamycin under standard diet increased median lifespan "
            "compared with control (d=0.65; n=90, p<0.001)."
        ),
    )
    wm.ingest_papers("org-audit", "ws-audit", [paper_one])
    wm.ingest_papers("org-audit", "ws-audit", [paper_two])
    wm.record_event(
        "org-audit",
        "ws-audit",
        action="verify",
        paper_count=1,
        claim_count=1,
        status="ok",
        detail="manual verify event",
    )

    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token("audit-reader"),
                org_id="org-audit",
                role="reader",
                label="audit-reader",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token("other-org-reader"),
                org_id="org-other",
                role="reader",
                label="other-org-reader",
            ),
        ]
    )
    app = SciGraphApp(
        auth_gate=gate,
        workspace_manager=wm,
        org_id="org-audit",
        workspace_id="ws-audit",
    )

    # 200 all events
    status_all, ctype_all, body_all = app.handle_request(
        "GET",
        "/api/v1/audit",
        incoming_header="Bearer audit-reader",
    )
    assert status_all == 200
    assert ctype_all == "application/json"
    all_events = json.loads(body_all)["events"]
    assert len(all_events) == 4

    # 200 ?action=ingest
    status_ingest, _, body_ingest = app.handle_request(
        "GET",
        "/api/v1/audit?action=ingest",
        incoming_header="Bearer audit-reader",
    )
    assert status_ingest == 200
    ingest_events = json.loads(body_ingest)["events"]
    assert len(ingest_events) == 2
    assert all(evt["action"] == "ingest" for evt in ingest_events)

    # 200 ?limit=1 returns most recent event
    status_limit, _, body_limit = app.handle_request(
        "GET",
        "/api/v1/audit?limit=1",
        incoming_header="Bearer audit-reader",
    )
    assert status_limit == 200
    limit_events = json.loads(body_limit)["events"]
    assert len(limit_events) == 1
    assert limit_events[0]["action"] == "verify"

    # 403 cross-org token rejection
    status_cross, _, body_cross = app.handle_request(
        "GET",
        "/api/v1/audit",
        incoming_header="Bearer other-org-reader",
    )
    assert status_cross == 403
    assert "org_id" in json.loads(body_cross)["error"]

    # 400 invalid action and invalid limit
    for bad_target in (
        "/api/v1/audit?action=delete",
        "/api/v1/audit?limit=abc",
        "/api/v1/audit?limit=0",
        "/api/v1/audit?limit=-3",
    ):
        bad_status, _, bad_body = app.handle_request(
            "GET",
            bad_target,
            incoming_header="Bearer audit-reader",
        )
        assert bad_status == 400
        assert "error" in json.loads(bad_body)

    # OpenAPI spec advertises /api/v1/audit
    spec_status, _, spec_body = app.handle_request("GET", "/openapi.json")
    assert spec_status == 200
    assert "/api/v1/audit" in json.loads(spec_body)["paths"]


def test_audit_endpoint_unbound_workspace_returns_400(tmp_path: Path) -> None:
    unbound_app = SciGraphApp()
    status, ctype, body = unbound_app.handle_request("GET", "/api/v1/audit")
    assert status == 400
    assert ctype == "application/json"
    assert "error" in json.loads(body)

    wm = WorkspaceManager(tmp_path)
    partial_app = SciGraphApp(workspace_manager=wm, org_id="org-only")
    p_status, _, p_body = partial_app.handle_request("GET", "/api/v1/audit")
    assert p_status == 400
    assert "error" in json.loads(p_body)


@contextmanager
def _running_server(app: SciGraphApp) -> Iterator[str]:
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    host_str = host.decode("ascii") if isinstance(host, bytes) else host
    try:
        yield f"http://{host_str}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_delete_paper_endpoint_auth_routing_and_persistence(tmp_path: Path) -> None:
    wm = WorkspaceManager(tmp_path)
    wm.init_workspace("org-del", "ws-del", "Delete Workspace")
    paper_one = _make_paper(
        paper_id="paper-del-1",
        doi="10.5000/del.1",
        title="Metformin Study",
        claim_sentence=(
            "Treatment with Metformin under normoxia increased AMPK phosphorylation "
            "compared with vehicle (d=0.80; n=40, p<0.001)."
        ),
    )
    paper_two = _make_paper(
        paper_id="paper-del-2",
        doi="10.5000/del.2",
        title="Rapamycin Study",
        claim_sentence=(
            "Treatment with Rapamycin under standard diet increased median lifespan "
            "compared with control (d=0.65; n=90, p<0.001)."
        ),
    )
    wm.ingest_papers("org-del", "ws-del", [paper_one, paper_two])

    gate = AuthGate(
        [
            TokenPolicy(
                token_sha256=hash_bearer_token("del-ingestor"),
                org_id="org-del",
                role="ingestor",
                label="del-ingestor",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token("del-reader"),
                org_id="org-del",
                role="reader",
                label="del-reader",
            ),
            TokenPolicy(
                token_sha256=hash_bearer_token("other-ingestor"),
                org_id="org-other",
                role="ingestor",
                label="other-ingestor",
            ),
        ]
    )
    app = SciGraphApp(
        auth_gate=gate,
        workspace_manager=wm,
        org_id="org-del",
        workspace_id="ws-del",
    )

    # 403 for reader role
    reader_status, _, reader_body = app.handle_request(
        "DELETE",
        "/api/v1/papers/paper-del-1",
        incoming_header="Bearer del-reader",
    )
    assert reader_status == 403
    assert "error" in json.loads(reader_body)

    # 403 for cross-org token
    cross_status, _, cross_body = app.handle_request(
        "DELETE",
        "/api/v1/papers/paper-del-1",
        incoming_header="Bearer other-ingestor",
    )
    assert cross_status == 403
    assert "org_id" in json.loads(cross_body)["error"]

    # 405 with Allow: DELETE on GET
    get_resp = app._dispatch(
        "GET",
        "/api/v1/papers/paper-del-1",
        b"",
        "Bearer del-ingestor",
        "127.0.0.1",
    )
    assert get_resp.status == 405
    assert get_resp.allow == "DELETE"

    # 400 on invalid paper_id (empty or containing '/')
    for bad_path in (
        "/api/v1/papers/",
        "/api/v1/papers/%20",
        "/api/v1/papers/a/b",
        "/api/v1/papers/a%2Fb",
    ):
        bad_status, _, bad_body = app.handle_request(
            "DELETE",
            bad_path,
            incoming_header="Bearer del-ingestor",
        )
        assert bad_status == 400
        assert "error" in json.loads(bad_body)

    # 404 on unknown paper
    missing_status, _, missing_body = app.handle_request(
        "DELETE",
        "/api/v1/papers/does-not-exist",
        incoming_header="Bearer del-ingestor",
    )
    assert missing_status == 404
    assert "error" in json.loads(missing_body)

    # 200 removes paper and reloads in-memory graph + persists + records audit
    ok_status, ok_ctype, ok_body = app.handle_request(
        "DELETE",
        "/api/v1/papers/paper-del-1",
        incoming_header="Bearer del-ingestor",
    )
    assert ok_status == 200
    assert ok_ctype == "application/json"
    assert json.loads(ok_body) == {
        "removed_paper_id": "paper-del-1",
        "removed_claims": 1,
    }

    health_status, _, health_body = app.handle_request(
        "GET",
        "/health",
        incoming_header="Bearer del-reader",
    )
    assert health_status == 200
    assert json.loads(health_body)["papers"] == 1
    assert json.loads(health_body)["claims"] == 1

    reloaded = wm.load_graph("org-del", "ws-del")
    assert [p.paper_id for p in reloaded.papers] == ["paper-del-2"]

    audit_status, _, audit_body = app.handle_request(
        "GET",
        "/api/v1/audit?action=remove",
        incoming_header="Bearer del-reader",
    )
    assert audit_status == 200
    remove_events = json.loads(audit_body)["events"]
    assert len(remove_events) == 1
    assert remove_events[0]["action"] == "remove"

    # OpenAPI spec advertises /api/v1/papers/{paper_id}
    spec_status, _, spec_body = app.handle_request(
        "GET",
        "/openapi.json",
        incoming_header="Bearer del-reader",
    )
    assert spec_status == 200
    assert "/api/v1/papers/{paper_id}" in json.loads(spec_body)["paths"]

    # Live HTTP DELETE request removes remaining paper
    with _running_server(app) as base_url:
        req = urllib.request.Request(
            f"{base_url}/api/v1/papers/paper-del-2",
            method="DELETE",
            headers={"Authorization": "Bearer del-ingestor"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            live_payload = json.loads(resp.read().decode("utf-8"))
            assert live_payload == {
                "removed_paper_id": "paper-del-2",
                "removed_claims": 1,
            }

        # Live HTTP GET on /api/v1/papers/<id> returns 405 with Allow: DELETE
        get_req = urllib.request.Request(
            f"{base_url}/api/v1/papers/paper-del-2",
            method="GET",
            headers={"Authorization": "Bearer del-reader"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(get_req, timeout=5)
        assert exc_info.value.code == 405
        assert exc_info.value.headers.get("Allow") == "DELETE"

    assert len(wm.load_graph("org-del", "ws-del").papers) == 0


def test_delete_paper_unbound_workspace_returns_400() -> None:
    unbound_app = SciGraphApp()
    status, ctype, body = unbound_app.handle_request("DELETE", "/api/v1/papers/paper-1")
    assert status == 400
    assert ctype == "application/json"
    assert "error" in json.loads(body)
