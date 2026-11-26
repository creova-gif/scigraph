from __future__ import annotations

import fcntl
import os
import re
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from graph.claim_graph import ClaimGraph
from graph.store import GraphSQLiteStore, save_graph_json
from ingest.extractor import extract_claims_from_paper
from ingest.verifier import verify_paper_claims
from scigraph.io_utils import atomic_write_text
from scigraph.models import Paper, PaperVerificationReport

if TYPE_CHECKING:
    from scigraph.provenance import ProvenanceManifest

WorkspaceAction = Literal["ingest", "verify", "query", "export", "remove", "contradiction_scan"]
AuditStatus = Literal["ok", "rejected", "error"]

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$")


def _validate_slug(value: str, field_name: str) -> str:
    """Validate an org_id or workspace_id slug against traversal and invalid characters."""
    if (
        ".." in value
        or "/" in value
        or "\\" in value
        or any(ch.isspace() for ch in value)
        or not _SLUG_PATTERN.match(value)
    ):
        raise ValueError(
            f"Invalid {field_name} '{value}': must match ^[a-zA-Z0-9][a-zA-Z0-9._-]{{1,63}}$ "
            "and must not contain '..', '/', '\\\\', or whitespace"
        )
    return value


@contextmanager
def _workspace_lock(ws_dir: Path) -> Iterator[None]:
    """Acquire an exclusive advisory file lock for a workspace directory."""
    lock_path = ws_dir / ".workspace.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class WorkspaceConfig(BaseModel):
    """Configuration metadata for an isolated tenant workspace."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    org_id: str
    workspace_id: str
    name: str = Field(min_length=1)
    created_at_utc: str = Field(min_length=1)

    @field_validator("org_id")
    @classmethod
    def _validate_org_id(cls, value: str) -> str:
        return _validate_slug(value, "org_id")

    @field_validator("workspace_id")
    @classmethod
    def _validate_workspace_id(cls, value: str) -> str:
        return _validate_slug(value, "workspace_id")


class AuditEvent(BaseModel):
    """Immutable audit log entry persisted to a workspace's audit.jsonl."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    timestamp_utc: str = Field(min_length=1)
    org_id: str
    workspace_id: str
    action: WorkspaceAction
    paper_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    status: AuditStatus
    detail: str

    @field_validator("org_id")
    @classmethod
    def _validate_org_id(cls, value: str) -> str:
        return _validate_slug(value, "org_id")

    @field_validator("workspace_id")
    @classmethod
    def _validate_workspace_id(cls, value: str) -> str:
        return _validate_slug(value, "workspace_id")


class WorkspaceManager:
    """Manages multi-tenant workspaces, per-workspace SQLite graphs, and JSONL audit logs."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def _resolve_workspace_dir(self, org_id: str, workspace_id: str) -> Path:
        _validate_slug(org_id, "org_id")
        _validate_slug(workspace_id, "workspace_id")
        base = self.root_dir.resolve()
        resolved = (base / org_id / workspace_id).resolve()
        if not resolved.is_relative_to(base):
            raise ValueError(
                f"Workspace path {resolved} escapes root directory {base}"
            )
        return resolved

    def init_workspace(
        self,
        org_id: str,
        workspace_id: str,
        name: str,
    ) -> WorkspaceConfig:
        """Initialize a new tenant workspace with config, SQLite store, and audit log."""
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        config_path = ws_dir / "workspace.json"
        if config_path.exists():
            raise FileExistsError(f"Workspace already exists: {org_id}/{workspace_id}")

        config = WorkspaceConfig(
            org_id=org_id,
            workspace_id=workspace_id,
            name=name,
            created_at_utc=datetime.now(UTC).isoformat(),
        )
        ws_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            config_path,
            config.model_dump_json(indent=2) + "\n",
            prefix=f".{config_path.name}.",
            create_parents=True,
        )
        GraphSQLiteStore(ws_dir / "graph.db")
        self.record_event(
            org_id=org_id,
            workspace_id=workspace_id,
            action="verify",
            paper_count=0,
            claim_count=0,
            status="ok",
            detail=f"Initialized workspace '{name}'",
        )
        return config

    def get_workspace(self, org_id: str, workspace_id: str) -> WorkspaceConfig:
        """Load and validate an existing workspace configuration."""
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        config_path = ws_dir / "workspace.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Workspace not found: {org_id}/{workspace_id}")
        return WorkspaceConfig.model_validate_json(
            config_path.read_text(encoding="utf-8")
        )

    def list_workspaces(self, org_id: str | None = None) -> list[WorkspaceConfig]:
        """List workspaces, optionally filtered to a single organization."""
        base = self.root_dir.resolve()
        if not base.exists():
            return []

        org_dirs: list[Path]
        if org_id is not None:
            _validate_slug(org_id, "org_id")
            candidate = (base / org_id).resolve()
            if not candidate.is_relative_to(base):
                raise ValueError(f"Organization path {candidate} escapes root directory {base}")
            if not candidate.is_dir():
                return []
            org_dirs = [candidate]
        else:
            org_dirs = sorted(p for p in base.iterdir() if p.is_dir())

        configs: list[WorkspaceConfig] = []
        for org_dir in org_dirs:
            for ws_dir in sorted(p for p in org_dir.iterdir() if p.is_dir()):
                config_path = ws_dir / "workspace.json"
                if config_path.is_file():
                    configs.append(
                        WorkspaceConfig.model_validate_json(
                            config_path.read_text(encoding="utf-8")
                        )
                    )
        return configs

    def ingest_papers(
        self,
        org_id: str,
        workspace_id: str,
        papers: Sequence[Paper],
    ) -> tuple[ClaimGraph, list[PaperVerificationReport]]:
        """Extract, verify, and persist papers and claims into the workspace graph."""
        self.get_workspace(org_id, workspace_id)
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)

        verified_entries: list[tuple[Paper, PaperVerificationReport]] = []
        reports: list[PaperVerificationReport] = []
        verified_count = 0
        rejected_count = 0

        for paper in papers:
            extracted = extract_claims_from_paper(paper)
            report = verify_paper_claims(paper, extracted)
            reports.append(report)
            verified_entries.append((paper, report))
            verified_count += len(report.verified_claims)
            rejected_count += len(report.rejected_claim_ids)

        with _workspace_lock(ws_dir):
            store = GraphSQLiteStore(ws_dir / "graph.db")
            graph = store.load_graph()

            for paper, report in verified_entries:
                if report.doi_verified:
                    graph.replace_paper_claims(paper, report.verified_claims)

            graph.build_edges()
            store.save_graph(graph)

            status: AuditStatus = (
                "rejected" if (rejected_count > 0 and verified_count == 0) else "ok"
            )
            self.record_event(
                org_id=org_id,
                workspace_id=workspace_id,
                action="ingest",
                paper_count=len(papers),
                claim_count=verified_count,
                status=status,
                detail=(
                    f"Ingested {len(papers)} paper(s): "
                    f"{verified_count} verified claim(s), {rejected_count} rejected claim(s)"
                ),
            )
        return graph, reports

    def load_graph(self, org_id: str, workspace_id: str) -> ClaimGraph:
        """Load the ClaimGraph persisted in the workspace's SQLite store."""
        self.get_workspace(org_id, workspace_id)
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        store = GraphSQLiteStore(ws_dir / "graph.db")
        return store.load_graph()

    def remove_paper(self, org_id: str, workspace_id: str, paper_id: str) -> int:
        """Remove a paper and its claims from the workspace graph and record an audit event."""
        self.get_workspace(org_id, workspace_id)
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)

        with _workspace_lock(ws_dir):
            store = GraphSQLiteStore(ws_dir / "graph.db")
            graph = store.load_graph()
            removed_claims = graph.remove_paper(paper_id)
            store.save_graph(graph)
            self.record_event(
                org_id=org_id,
                workspace_id=workspace_id,
                action="remove",
                paper_count=1,
                claim_count=removed_claims,
                status="ok",
                detail=f"Removed paper '{paper_id}' ({removed_claims} claim(s))",
            )
        return removed_claims

    def record_event(
        self,
        org_id: str,
        workspace_id: str,
        action: WorkspaceAction,
        paper_count: int,
        claim_count: int,
        status: AuditStatus,
        detail: str,
    ) -> AuditEvent:
        """Append a validated AuditEvent to the workspace's audit.jsonl file."""
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        if not (ws_dir / "workspace.json").exists():
            raise FileNotFoundError(f"Workspace not found: {org_id}/{workspace_id}")

        event = AuditEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            timestamp_utc=datetime.now(UTC).isoformat(),
            org_id=org_id,
            workspace_id=workspace_id,
            action=action,
            paper_count=paper_count,
            claim_count=claim_count,
            status=status,
            detail=detail,
        )
        audit_path = ws_dir / "audit.jsonl"
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read_audit_log(
        self,
        org_id: str,
        workspace_id: str,
        *,
        action: WorkspaceAction | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Read AuditEvent entries from the workspace's audit.jsonl file."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        self.get_workspace(org_id, workspace_id)
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        audit_path = ws_dir / "audit.jsonl"
        if not audit_path.exists():
            return []

        events: list[AuditEvent] = []
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                events.append(AuditEvent.model_validate_json(stripped))
        if action is not None:
            events = [event for event in events if event.action == action]
        if limit is not None:
            events = events[-limit:]
        return events

    def export_workspace_bundle(
        self,
        org_id: str,
        workspace_id: str,
        output_dir: Path,
        *,
        hmac_key: bytes | None = None,
    ) -> ProvenanceManifest:
        """Export an atomic compliance bundle (graph, provenance, workspace config, audit log)."""
        # Inline import avoids circular dependency: scigraph.provenance imports AuditEvent here.
        from scigraph.provenance import build_provenance_manifest

        self.get_workspace(org_id, workspace_id)
        ws_dir = self._resolve_workspace_dir(org_id, workspace_id)
        resolved_out = output_dir.resolve()
        resolved_ws = ws_dir.resolve()
        if resolved_out.is_relative_to(resolved_ws):
            raise ValueError("Export output_dir must not be inside the source workspace directory")

        with _workspace_lock(ws_dir):
            config = self.get_workspace(org_id, workspace_id)
            graph = self.load_graph(org_id, workspace_id)
            events = self.read_audit_log(org_id, workspace_id)

            manifest = build_provenance_manifest(
                graph,
                audit_events=events,
                hmac_key=hmac_key,
            )

            output_dir.mkdir(parents=True, exist_ok=True)
            save_graph_json(graph, output_dir / "graph.json")
            atomic_write_text(
                output_dir / "provenance.json",
                manifest.model_dump_json(indent=2) + "\n",
                prefix=".provenance.json.",
                create_parents=True,
            )
            atomic_write_text(
                output_dir / "workspace.json",
                config.model_dump_json(indent=2) + "\n",
                prefix=".workspace.json.",
                create_parents=True,
            )
            audit_content = "".join(event.model_dump_json() + "\n" for event in events)
            atomic_write_text(
                output_dir / "audit.jsonl",
                audit_content,
                prefix=".audit.jsonl.",
                create_parents=True,
            )

            self.record_event(
                org_id=org_id,
                workspace_id=workspace_id,
                action="export",
                paper_count=len(graph.papers),
                claim_count=len(graph.claims),
                status="ok",
                detail=f"Exported compliance bundle to {output_dir}",
            )

        return manifest
