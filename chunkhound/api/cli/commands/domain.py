"""CLI entrance for append-only human domain input."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from chunkhound.core.config.config import Config
from chunkhound.database_factory import create_services
from chunkhound.domain_model.human_input import (
    DomainInputProvider,
    DomainInputRejected,
    DomainInputUnavailable,
    HumanInputView,
    WriteRequest,
    domain_error_json,
    human_input_view_json,
    load_human_input,
    write_human_input,
    write_result_json,
)
from chunkhound.domain_model.issues import Issue
from chunkhound.domain_model.model import DomainModel

from .run import _is_db_lock_error


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


async def domain_command(args: argparse.Namespace, config: Config) -> None:
    if args.dry_run and not args.write:
        sys.stderr.write("chunkhound domain: error: --dry-run requires --write\n")
        raise SystemExit(2)
    if args.schema:
        _emit(WriteRequest.model_json_schema())
        return
    if not args.write and not args.list_input:
        sys.stderr.write("extraction is not available yet (§2)\n")
        raise SystemExit(2)
    provider = None
    try:
        if config.database.provider != "duckdb":
            raise DomainInputUnavailable(
                [
                    Issue(
                        "",
                        "backend_not_supported",
                        "Backend does not support human input; nothing was written",
                    )
                ]
            )
        # Path resolution normally creates directories; listing must not do so.
        db_path = config.database.model_copy(update={"read_only": True}).get_db_path()
        if args.list_input and not db_path.exists():
            _emit(
                human_input_view_json(
                    HumanInputView(
                        model=DomainModel(
                            schema_version=1,
                            concepts=(),
                            fact_types=(),
                            roles=(),
                            validation_rules=(),
                            derivation_rules=(),
                            exchange_rules=(),
                            event_rules=(),
                            ground_facts=(),
                        ),
                        judgements=(),
                    )
                )
            )
            return
        request: Any = None
        if args.write:
            try:
                text = (
                    sys.stdin.read()
                    if args.write == "-"
                    else Path(args.write).read_text(encoding="utf-8")
                )
                request = json.loads(text)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DomainInputRejected(
                    [Issue("", "invalid_json", str(exc))]
                ) from exc
        services = create_services(db_path=db_path, config=config)
        provider = services.provider
        provider.connect()
        domain_provider = cast(DomainInputProvider, provider)
        if args.list_input:
            _emit(human_input_view_json(load_human_input(domain_provider)))
        else:
            _emit(
                write_result_json(
                    write_human_input(
                        request,
                        provider=domain_provider,
                        project_root=config.target_dir or Path(args.path).resolve(),
                        entry_point="cli",
                        dry_run=args.dry_run,
                    )
                )
            )
    except DomainInputRejected as exc:
        _emit(domain_error_json(exc))
        raise SystemExit(1) from exc
    except DomainInputUnavailable as exc:
        _emit(domain_error_json(exc))
        raise SystemExit(2) from exc
    except Exception as exc:
        if not _is_db_lock_error(exc):
            raise
        sys.stderr.write(
            "Database is locked by a running daemon; use MCP tools "
            "domain_write and domain_read while it runs.\n"
        )
        raise SystemExit(2) from exc
    finally:
        if provider is not None:
            provider.disconnect()
