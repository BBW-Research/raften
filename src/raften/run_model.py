"""Immutable command results shared by orchestration and presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import TypeAlias

from raften.model import (
    Diagnostic,
    DocumentationEvaluation,
    FileExplanation,
    FileRatchetAssessment,
    FileRatchetEvaluation,
    InventoryEntry,
    MigrationDebtManifest,
    Policy,
    RepositoryPath,
    SizeEvaluation,
)


class RunStatus(StrEnum):
    COMPLETE = "complete"
    CONFIGURATION_ERROR = "configuration_error"
    OPERATIONAL_ERROR = "operational_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class CommandFailure:
    status: RunStatus
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class RepositoryRun:
    status: RunStatus
    repository_root: Path
    config_path: RepositoryPath
    policy: Policy
    inventory: tuple[InventoryEntry, ...]
    sizes: SizeEvaluation
    documentation: DocumentationEvaluation
    ratchet: FileRatchetEvaluation
    diagnostics: tuple[Diagnostic, ...]
    base_commit_id: str | None
    evaluation_date: date


@dataclass(frozen=True, slots=True)
class DocumentationExplanation:
    governed: bool
    document: bool
    root: bool
    unreachable: bool
    inbound_paths: tuple[RepositoryPath, ...]
    outbound_paths: tuple[RepositoryPath, ...]


@dataclass(frozen=True, slots=True)
class PathExplanation:
    run: RepositoryRun
    file: FileExplanation
    documentation: DocumentationExplanation
    migration: FileRatchetAssessment | None


@dataclass(frozen=True, slots=True)
class InitResult:
    repository_root: Path
    config_path: RepositoryPath
    debt_manifest_path: RepositoryPath | None
    manifest: MigrationDebtManifest | None
    written_paths: tuple[RepositoryPath, ...]


RunOutcome: TypeAlias = RepositoryRun | CommandFailure
ExplainOutcome: TypeAlias = PathExplanation | CommandFailure
InitOutcome: TypeAlias = InitResult | CommandFailure
