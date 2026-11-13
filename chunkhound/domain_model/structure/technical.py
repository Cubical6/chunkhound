"""Reader-scoped technical table lists; only '*' is a wildcard."""

import re

from chunkhound.core.config.domain_config import TechnicalTablesConfig

LISTS: dict[str, tuple[str, ...]] = {
    "laravel": (
        "migrations",
        "jobs",
        "failed_jobs",
        "job_batches",
        "cache",
        "cache_locks",
        "sessions",
        "password_reset_tokens",
        "password_resets",
        "telescope_entries",
        "telescope_entries_tags",
        "telescope_monitoring",
        "pulse_aggregates",
        "pulse_entries",
        "pulse_values",
    ),
    "magento": (
        "*_idx",
        "*_tmp",
        "*_replica",
        "*_cl",
        "*_entity_int",
        "*_entity_decimal",
        "*_entity_varchar",
        "*_entity_text",
        "*_entity_datetime",
        "cron_schedule",
        "setup_module",
        "patch_list",
        "cache",
        "cache_tag",
        "session",
        "indexer_state",
        "mview_state",
    ),
    "migration_tools": (
        "_prisma_migrations",
        "typeorm_metadata",
        "flyway_schema_history",
        "knex_migrations",
        "knex_migrations_lock",
        "databasechangelog",
        "databasechangeloglock",
    ),
    "typeorm": ("migrations",),
    "graphql": (
        "*Connection",
        "*Edge",
        "PageInfo",
        "PaginatorInfo",
        "SimplePaginatorInfo",
    ),
}


def _matches(name: str, pattern: str) -> bool:
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), name) is not None


def technical_matches(
    name: str, reader: str, path: str, config: TechnicalTablesConfig
) -> tuple[tuple[str, str], ...]:
    """Return (reason, list name) pairs without removing the extracted fact type."""
    if any(_matches(name, pattern) for pattern in config.add):
        return (("configured", "configured"),)
    active = {"migration_tools"}
    if reader == "sql":
        active.add("typeorm")
        if path.startswith("database/schema/") or "/database/schema/" in path:
            active.add("laravel")
    elif reader in {"laravel", "laravel_migrations"}:
        active.add("laravel")
    elif reader in {"magento", "magento_schema"}:
        active.add("magento")
    elif reader in {"typeorm", "graphql"}:
        active.add(reader)
    return tuple(
        ("framework_table", list_name)
        for list_name, patterns in LISTS.items()
        if list_name in active
        and any(
            pattern not in config.remove and _matches(name, pattern)
            for pattern in patterns
        )
        and not any(_matches(name, pattern) for pattern in config.remove)
    )
