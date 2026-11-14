"""Reader orchestration with a Git-free core and a thin Git boundary."""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from chunkhound.core.config.config import Config
from chunkhound.domain_model.identity import repository_key
from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import citation_key, finalize_anchors
from chunkhound.domain_model.structure.contract import (
    Anchor,
    Finding,
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.files import (
    read_file,
    repository_paths,
    select_files,
)
from chunkhound.domain_model.structure.readers.eloquent import EloquentReader
from chunkhound.domain_model.structure.readers.laravel_migrations import (
    LaravelMigrationsReader,
)
from chunkhound.domain_model.structure.readers.laravel_routes import LaravelRoutesReader
from chunkhound.domain_model.structure.readers.magento_anchors import (
    MagentoAnchorsReader,
)
from chunkhound.domain_model.structure.readers.magento_schema import (
    MagentoSchemaReader,
    third_party_findings,
)
from chunkhound.domain_model.structure.readers.prisma import PrismaReader
from chunkhound.domain_model.structure.readers.sql import SQLReader
from chunkhound.domain_model.structure.readers.typeorm import TypeORMReader
from chunkhound.domain_model.structure.schema import Schema
from chunkhound.domain_model.structure.translate import translate
from chunkhound.services.extraction.sources import SourceVersion
from chunkhound.utils.git_safe import GitCommandError, run_git


class StructureExtractionError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        self.code = code
        super().__init__(f"{code}: {path}")


@dataclass
class ReadContext:
    project_root: Path
    repositories: tuple[RepositoryRef, ...]
    config: Config | None
    paths: tuple[str, ...] = ()
    findings: list[Finding] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    read_paths: set[str] = field(default_factory=set)
    schemas: list[Schema] = field(default_factory=list)

    _repository_prefixes: tuple[tuple[PurePosixPath, RepositoryRef], ...] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._repository_prefixes = tuple(
            sorted(
                ((PurePosixPath(repo.path), repo) for repo in self.repositories),
                key=lambda item: (-len(item[0].parts), item[0].as_posix()),
            )
        )

    def repository_of(self, path: str) -> RepositoryRef:
        directory = PurePosixPath(path).parent
        for prefix, repository in self._repository_prefixes:
            if directory.is_relative_to(prefix):
                return repository
        raise ValueError(f"No declared repository for source: {path}")

    def read(self, path: str) -> SourceVersion | None:
        self.read_paths.add(path)
        return read_file(
            self.project_root, path, self.repository_of(path), self.findings
        )


class Reader(Protocol):
    name: str
    patterns: tuple[str, ...]

    def read(self, ctx: ReadContext) -> None: ...


READERS: list[Reader] = [
    SQLReader(),
    PrismaReader(),
    MagentoSchemaReader(),
    LaravelMigrationsReader(),
    TypeORMReader(),
    EloquentReader(),
    LaravelRoutesReader(),
    MagentoAnchorsReader(),
]


def _build(ctx: ReadContext) -> StructureExtraction:
    for reader in READERS:
        ctx.paths = select_files(ctx.project_root, reader.patterns)
        if not ctx.paths:
            continue
        try:
            reader.read(ctx)
        except Exception:
            # No guessed output or exception text (which may contain absolute paths).
            # Attribute the failed reader to its first selected source.
            if ctx.paths:
                path = ctx.paths[0]
                repo = ctx.repository_of(path)
                ctx.findings.append(
                    Finding(
                        kind="unresolved",
                        subject=None,
                        reason="unreadable_source",
                        detail=reader.name,
                        citations=(
                            Citation(
                                repository=repo.key,
                                path=path,
                                start_line=1,
                                end_line=1,
                                commit=repo.commit,
                            ),
                        ),
                    )
                )
    model, findings, claims = translate(
        ctx.schemas, ctx.repository_of, ctx.config.domain if ctx.config else None
    )
    ctx.findings.extend(findings)
    ctx.findings.extend(third_party_findings(ctx, model))
    return StructureExtraction(
        schema_version=1,
        repositories=ctx.repositories,
        model=model,
        anchors=finalize_anchors(ctx.anchors, ctx.schemas, model),
        findings=tuple(
            sorted(
                set(ctx.findings),
                key=lambda finding: (
                    finding.kind,
                    finding.subject or "",
                    finding.reason,
                    finding.detail or "",
                    tuple(citation_key(c) for c in finding.citations),
                    finding.model_dump_json(),
                ),
            )
        ),
        divergent_claims=tuple(claims),
    )


def build_structure(
    project_root: Path,
    repositories: tuple[RepositoryRef, ...],
    config: Config | None = None,
) -> StructureExtraction:
    """Run readers on local files without invoking Git, providers, or a database."""
    return _build(ReadContext(project_root, repositories, config))


def extract_structure(
    project_root: Path, config: Config | None = None
) -> StructureExtraction:
    project_root = project_root.resolve()
    repositories = []
    keys: set[str] = set()
    for path in repository_paths(project_root):
        key = repository_key(path)
        if key in keys:
            raise StructureExtractionError("repository_key_collision", path)
        keys.add(key)
        repositories.append(
            RepositoryRef(
                key=key,
                path=path,
                commit="1" * 40,
                dirty=False,
            )
        )
    for index, repo in enumerate(repositories):
        try:
            result = run_git(
                ["rev-parse", "--verify", "HEAD"], project_root / repo.path
            )
        except GitCommandError as exc:
            raise StructureExtractionError(
                "repository_without_commit", repo.path
            ) from exc
        if result.returncode or len(result.stdout.strip()) != 40:
            raise StructureExtractionError("repository_without_commit", repo.path)
        repositories[index] = repo.model_copy(update={"commit": result.stdout.strip()})
    ctx = ReadContext(project_root, tuple(repositories), config)
    extraction = _build(ctx)
    for index, repo in enumerate(repositories):
        paths = sorted(
            Path(path).relative_to(repo.path).as_posix()
            for path in ctx.read_paths
            if ctx.repository_of(path).key == repo.key
        )
        if paths:
            try:
                status = run_git(
                    [
                        "status",
                        "--porcelain",
                        "--untracked-files=all",
                        "--",
                        *paths,
                    ],
                    project_root / repo.path,
                )
                dirty = bool(status.returncode or status.stdout)
            except GitCommandError:
                # If status is unavailable, we cannot establish a clean source state.
                dirty = True
            repositories[index] = repo.model_copy(update={"dirty": dirty})
    return extraction.model_copy(update={"repositories": tuple(repositories)})
