"""Laravel's current schema, conservative findings, and dump replay contracts."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
    dump_structure,
)
from chunkhound.domain_model.structure.extract import build_structure

FIXTURES = Path(__file__).parent / "fixtures"
COMMIT = "1111111111111111111111111111111111111111"


def replay_php(
    tmp_path: Path, body: str, *, dump: str | None = None
) -> StructureExtraction:
    migrations = tmp_path / "database" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "V1.php").write_text(
        "<?php return new class extends Migration { public function up(): void {"
        + body
        + "} public function down(): void { Schema::drop('notes'); } };"
    )
    if dump is not None:
        schema = tmp_path / "database" / "schema"
        schema.mkdir()
        (schema / "pgsql-schema.sql").write_text(dump)
    return build_structure(
        tmp_path, (RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False),)
    )


def test_worked_example_matches_expected_json(tmp_path: Path) -> None:
    project = tmp_path / "example"
    shutil.copytree(FIXTURES / "example", project)
    result = build_structure(
        project,
        (RepositoryRef(key="backend", path="backend", commit=COMMIT, dirty=False),),
    )
    assert dump_structure(result) == (project / "expected.json").read_text()


def test_added_then_renamed_column_has_current_name(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_migrations")
    roles = {
        r.name: r
        for r in result.model.roles
        if r.fact_type == "fact_type:root/team-user"
    }
    assert "label" not in roles
    assert roles["title"].datatype == "string(100)"
    assert roles["title"].mandatory is False
    assert [c.path for c in roles["title"].citations] == [
        "database/migrations/V2_add.php",
        "database/migrations/V10_rename.php",
    ]
    assert roles["title"].bindings[0].target == "team_user.title"
    assert roles["title"].bindings[0].citation.path.endswith("V10_rename.php")


def test_raw_sql_marks_table_uncertain(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_migrations")
    assert any(
        f.reason == "raw_sql" and f.subject == "fact_type:root/team-user"
        for f in result.findings
    )


def test_conditional_schema_call_marks_table_uncertain(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_migrations")
    assert any(
        f.reason == "conditional_schema" and f.subject == "fact_type:root/users"
        for f in result.findings
    )


def test_unknown_blueprint_method_is_not_read_as_column(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_migrations")
    assert not any(r.name == "not_a_column" for r in result.model.roles)
    assert any(
        f.reason == "unknown_schema_call" and f.subject == "fact_type:root/team-user"
        for f in result.findings
    )
    assert any(
        f.reason == "non_literal_argument" and f.kind == "unresolved"
        for f in result.findings
    )


@pytest.mark.parametrize("target_exists", [False, True])
def test_constrained_without_argument_links_only_to_existing_table(
    tmp_path: Path, target_exists: bool
) -> None:
    result = replay_php(
        tmp_path,
        (
            "Schema::create('users', function ($t) { $t->id(); });"
            if target_exists
            else ""
        )
        + "Schema::create('notes', function ($t) { $t->id(); "
        "$t->foreignId('user_id')->constrained(); });",
    )
    subsets = [r for r in result.model.validation_rules if r.rule_kind == "subset"]
    if target_exists:
        assert subsets[0].superset_fact_type == "fact_type:root/users"
        assert not result.findings
    else:
        assert not subsets
        assert any(
            f.reason == "table_not_found" and f.subject == "fact_type:root/notes"
            for f in result.findings
        )


def test_framework_tables_are_technical(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_migrations")
    for name in ("jobs", "sessions"):
        assert any(f.id == f"fact_type:root/{name}" for f in result.model.fact_types)
        assert any(
            f.kind == "technical"
            and f.subject == f"fact_type:root/{name}"
            and f.detail == "laravel"
            for f in result.findings
        )


def test_only_migrations_after_the_dump_are_replayed(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_dump")
    assert {
        r.name for r in result.model.roles if r.fact_type == "fact_type:root/notes"
    } == {"id", "user_id", "title"}
    assert any(
        r.rule_kind == "subset" and r.superset_fact_type == "fact_type:root/users"
        for r in result.model.validation_rules
    )
    assert not any(f.kind in {"uncertain", "unresolved"} for f in result.findings)
    assert any(
        f.reason == "framework_table" and f.subject == "fact_type:root/migrations"
        for f in result.findings
    )
    assert (
        next(r for r in result.model.roles if r.name == "title").datatype
        == "string(100)"
    )


def test_pgsql_copy_ledger_skips_listed_migrations_and_preserves_later_ddl(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("laravel_pg_dump")
    roles = {
        r.name: r for r in result.model.roles if r.fact_type == "fact_type:root/users"
    }
    assert set(roles) == {"id", "name", "code", "title"}
    assert roles["name"].datatype == "character varying(255)"
    assert roles["code"].datatype == "character(10)"
    assert roles["code"].citations[0].start_line == 12
    assert roles["title"].datatype == "string(50)"
    assert not any(f.kind in {"uncertain", "unresolved"} for f in result.findings)


def test_schema_settings_and_connected_arrow_callbacks_replay_tables(
    tmp_path: Path,
) -> None:
    result = replay_php(
        tmp_path,
        """
        Schema::disableForeignKeyConstraints();
        Schema::enableForeignKeyConstraints();
        Schema::withoutForeignKeyConstraints(fn () => null);
        Schema::defaultStringLength(191); Schema::defaultMorphKeyType('uuid');
        Schema::unknownGlobal(); Schema::unknownGlobal(191);
        Schema::connection('other')->create('users', fn ($t) => $t->id());
        Schema::connection('other')->table('users',
            fn (Blueprint $table) => $table->string('x'));
        Schema::connection('other')->create('gone', fn ($t) => $t->id());
        Schema::connection('other')->drop('gone');
        Schema::connection('other')->dropIfExists('absent');
        Schema::unknownTableOperation('users');
    """,
    )
    assert {f.name for f in result.model.fact_types} == {"users"}
    assert {r.name for r in result.model.roles} == {"id", "x"}
    assert [(f.reason, f.subject) for f in result.findings] == [
        ("unknown_schema_call", "fact_type:root/users"),
    ]


@pytest.mark.parametrize("method", ["foreignId", "foreign"])
@pytest.mark.parametrize("reference", ["->references('code')", ""])
def test_foreign_modifiers_create_subset_using_explicit_or_primary_columns(
    tmp_path: Path,
    method: str,
    reference: str,
) -> None:
    column = "$t->integer('user_id');" if method == "foreign" else ""
    result = replay_php(
        tmp_path,
        "Schema::create('users', fn ($t) => $t->string('code')->primary());"
        "Schema::create('notes', function ($t) { $t->id(); "
        + column
        + f"$t->{method}('user_id'){reference}->on('users'); }});",
    )
    rule = next(r for r in result.model.validation_rules if r.rule_kind == "subset")
    assert rule.roles == ("role:root/notes/user-id",)
    assert rule.superset_roles == ("role:root/users/code",)
    assert not result.findings


def test_reference_without_target_is_marked_instead_of_silently_ignored(
    tmp_path: Path,
) -> None:
    result = replay_php(
        tmp_path,
        "Schema::create('notes', function ($t) { $t->id(); "
        "$t->foreignId('user_id')->references('id'); });",
    )
    assert any(
        f.reason == "unknown_schema_call" and f.subject == "fact_type:root/notes"
        for f in result.findings
    )


@pytest.mark.parametrize("argument", ["['code']", "", "'notes_code_primary'"])
def test_drop_primary_accepts_columns_no_argument_or_index_name(
    tmp_path: Path, argument: str
) -> None:
    result = replay_php(
        tmp_path,
        "Schema::create('notes', function ($t) { $t->string('code'); "
        "$t->primary(['code']); });"
        f"Schema::table('notes', fn ($t) => $t->dropPrimary({argument}));",
    )
    assert (
        next(f for f in result.model.fact_types if f.name == "notes").identifies is None
    )
    assert not result.model.validation_rules
    assert not result.findings


def test_dump_without_ledger_replays_all_migrations_and_postgres_ddl(
    tmp_path: Path,
) -> None:
    result = replay_php(
        tmp_path,
        "Schema::table('notes', function ($t) { $t->string('title'); });",
        dump="CREATE TABLE public.notes (id bigint NOT NULL); "
        "ALTER TABLE ONLY public.notes ADD CONSTRAINT notes_pkey PRIMARY KEY (id);",
    )
    assert (
        next(f for f in result.model.fact_types if f.name == "notes").identifies
        == "concept:root/notes"
    )
    assert {r.name for r in result.model.roles} == {"id", "title"}
    assert not result.findings


def test_blueprint_types_expansions_and_constraints_keep_source_semantics(
    tmp_path: Path,
) -> None:
    result = replay_php(
        tmp_path,
        """
        Schema::create('notes', function ($t) {
            $t->id(); $t->string('title', length: 100)->nullable()->unique();
            $t->decimal('amount', total: 8, places: 2)->unsigned();
            $t->string('unknown_length', length: $length);
            $t->decimal('partial', total: 8, places: $scale);
            $t->enum('state', ['open', 'closed']); $t->set('tags', ['a', 'b']);
            $t->timestamps(); $t->softDeletes(); $t->rememberToken();
            $t->morphs('owner'); $t->index(['state']);
            $t->integer('rank')->default(0)->index()->after('id')
                ->comment('Rank')->useCurrent();
        });
    """,
    )
    roles = {r.name: r for r in result.model.roles}
    assert (
        roles["title"].datatype == "string(100)" and roles["title"].mandatory is False
    )
    assert roles["amount"].datatype == "decimal(8,2) unsigned"
    assert roles["unknown_length"].datatype == "string"
    assert roles["partial"].datatype == "decimal(8)"
    assert {
        "owner_type",
        "owner_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "remember_token",
    } <= roles.keys()
    assert all(
        roles[n].mandatory is False
        for n in ["created_at", "updated_at", "deleted_at", "remember_token"]
    )
    assert roles["owner_type"].mandatory is True
    rules = {r.id: r for r in result.model.validation_rules}
    assert rules["validation_rule:root/notes/value/state"].allowed_values == (
        "open",
        "closed",
    )
    assert rules["validation_rule:root/notes/value/tags"].allowed_values == ("a", "b")
    assert "validation_rule:root/notes/uniqueness/title" in rules
    assert not result.findings


def test_blueprint_replay_changes_drops_and_follows_renames(tmp_path: Path) -> None:
    result = replay_php(
        tmp_path,
        """
        Schema::create('users', function ($t) { $t->id(); });
        Schema::create('notes', function ($t) {
            $t->id(); $t->integer('user_id'); $t->string('title', 20)->unique();
            $t->foreign('user_id')->references('id')->on('users');
            $t->string('gone'); $t->unique(['user_id', 'title']);
        });
        Schema::table('notes', function ($t) {
            $t->dropUnique(['user_id', 'title']); $t->dropUnique('notes_title_unique');
            $t->dropForeign(['user_id']); $t->dropColumn(['gone']);
            $t->string('title', 80)->nullable()->change();
            $t->renameColumn('title', 'heading');
            $t->dropPrimary(); $t->primary(['id']);
        });
        Schema::rename('users', 'members'); Schema::rename('notes', 'entries');
        Schema::table('entries', function ($t) {
            $t->foreign('user_id', 'owner_fk')->references('id')->on('members');
        });
        Schema::create('gone', function ($t) { $t->id(); });
        Schema::drop('gone'); Schema::dropIfExists('absent');
    """,
    )
    assert {f.name for f in result.model.fact_types} == {"members", "entries"}
    roles = {
        r.name: r for r in result.model.roles if r.fact_type == "fact_type:root/entries"
    }
    assert set(roles) == {"id", "user_id", "heading"}
    assert (
        roles["heading"].datatype == "string(80)"
        and roles["heading"].mandatory is False
    )
    assert len(roles["heading"].citations) == 3
    rules = [
        r
        for r in result.model.validation_rules
        if r.fact_type == "fact_type:root/entries"
    ]
    assert len(rules) == 2
    assert any(
        r.rule_kind == "subset" and r.superset_fact_type == "fact_type:root/members"
        for r in rules
    )
    assert not result.findings


@pytest.mark.parametrize("method", ["statement", "unprepared", "raw"])
def test_raw_sql_without_schema_call_has_no_subject(
    tmp_path: Path, method: str
) -> None:
    result = replay_php(tmp_path, f"DB::{method}('ALTER TABLE notes ADD title text');")
    assert not result.model.fact_types
    assert any(
        f.reason == "raw_sql" and f.subject is None and f.citations
        for f in result.findings
    )


@pytest.mark.parametrize("guard", ["if (true)", "foreach ([1] as $x)", "while (true)"])
def test_conditional_replay_does_not_invent_columns(tmp_path: Path, guard: str) -> None:
    result = replay_php(
        tmp_path,
        "Schema::create('notes', function ($t) { $t->id(); });"
        + guard
        + " { Schema::table('notes', function ($t) { $t->string('maybe'); }); }",
    )
    assert {r.name for r in result.model.roles} == {"id"}
    assert any(
        f.reason == "conditional_schema" and f.subject == "fact_type:root/notes"
        for f in result.findings
    )


def test_dynamic_names_and_unknown_tables_are_not_invented(tmp_path: Path) -> None:
    result = replay_php(
        tmp_path,
        """
        Schema::create($tableName, function ($t) { $t->id(); });
        Schema::table('missing', function ($t) { $t->string('title'); });
        Schema::create('notes', function ($t) {
            $t->id(); $t->string("name_$suffix");
        });
    """,
    )
    assert {f.name for f in result.model.fact_types} == {"notes"}
    assert {r.name for r in result.model.roles} == {"id"}
    assert sum(f.reason == "non_literal_argument" for f in result.findings) == 2
    assert any(
        f.kind == "uncertain" and f.subject is None and f.detail == "missing"
        for f in result.findings
    )


@pytest.mark.parametrize(
    "singular,plural",
    [("category", "categories"), ("box", "boxes"), ("key", "keys"), ("dish", "dishes")],
)
def test_constrained_uses_only_regular_plural_convention(
    tmp_path: Path, singular: str, plural: str
) -> None:
    result = replay_php(
        tmp_path,
        f"Schema::create('{plural}', function ($t) {{ $t->id(); }});"
        "Schema::create('notes', function ($t) { $t->id(); "
        f"$t->foreignId('{singular}_id')->constrained(); }});",
    )
    assert (
        next(
            r for r in result.model.validation_rules if r.rule_kind == "subset"
        ).superset_fact_type
        == f"fact_type:root/{plural}"
    )
    assert not result.findings
