"""Next.js entry points and Zod hints through the public build contract."""

import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.anchors import anchor_id
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure

FIXTURE = Path(__file__).parent / "fixtures" / "nextjs"
REPOSITORIES = (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root


def extract(project: Path) -> StructureExtraction:
    return build_structure(project, REPOSITORIES)


def put(root: Path, path: str, source: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)


def test_route_handler_exports_are_anchors(project: Path) -> None:
    result = extract(project)
    for method in ("GET", "POST"):
        anchor = next(
            a
            for a in result.anchors
            if a.id == anchor_id("root", "http", method, "/api/teams/[id]")
        )
        assert anchor.source == "nextjs"
        assert anchor.handler is not None
        assert anchor.handler.symbol == f"app/api/teams/[id]/route.ts#{method}"
        assert anchor.handler.citation is not None
        assert anchor.handler.citation.start_line == (2 if method == "GET" else 5)
        assert anchor.handler.citation.end_line == (4 if method == "GET" else 9)
        assert any(
            h.kind == "operation" and h.value == ("read" if method == "GET" else "add")
            for h in anchor.hints
        )


def test_route_group_is_left_out_of_the_path(project: Path) -> None:
    assert any(
        a.path == "/health" and a.method == "GET" for a in extract(project).anchors
    )


def test_pages_api_route_accepts_any_method(project: Path) -> None:
    anchor = next(a for a in extract(project).anchors if a.method == "ANY")
    assert anchor.path == "/api/teams"
    assert (
        anchor.handler is not None
        and anchor.handler.symbol == "pages/api/teams/index.ts#default"
    )
    assert (
        anchor.handler.citation is not None and anchor.handler.citation.start_line == 1
    )
    assert not any(h.kind == "operation" for h in anchor.hints)


def test_server_actions_are_anchors_of_kind_action(project: Path) -> None:
    actions = [a for a in extract(project).anchors if a.kind == "action"]
    assert {a.path for a in actions} == {"actions.ts#addTeam", "actions.ts#removeTeam"}
    for anchor in actions:
        assert anchor.method is None
        assert anchor.id == anchor_id("root", "action", None, anchor.path)
        assert not any(h.kind == "operation" for h in anchor.hints)


def test_imported_zod_schema_becomes_input_hints(project: Path) -> None:
    result = extract(project)
    anchor = next(a for a in result.anchors if a.method == "POST")
    assert [h.name for h in anchor.hints if h.kind == "input_type"] == ["TeamInput"]
    assert {(h.name, h.value) for h in anchor.hints if h.kind == "input_rule"} == {
        ("name", "z.string().min(1)"),
        ("email", "z.string().email()"),
    }
    assert all(
        h.citation.path == "schemas.ts"
        for h in anchor.hints
        if h.kind.startswith("input_")
    )
    assert not next(
        a for a in result.anchors if a.method == "GET" and a.path == "/api/teams/[id]"
    ).hints[1:]
    assert not result.model.fact_types


def test_unused_zod_schema_gives_nothing(project: Path) -> None:
    result = extract(project)
    assert not any(
        h.name in {"UnusedInput", "secret"} for a in result.anchors for h in a.hints
    )
    assert not result.model.fact_types


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/route.ts", "/"),
        ("src/app/(public)/@modal/api/[...slug]/route.js", "/api/[...slug]"),
        ("app/[[...slug]]/route.ts", "/[[...slug]]"),
        ("app/app/route.ts", "/app"),
        ("pages/api/index.js", "/api"),
        ("src/pages/api/teams/[id].ts", "/api/teams/[id]"),
        ("pages/pages/api/index.ts", None),
        ("app/_private/route.ts", None),
        ("pages/api/_private/index.ts", None),
        ("app/api/route.tsx", None),
        ("app/api/route.jsx", None),
        ("app/api/route.d.ts", None),
        ("node_modules/app/route.ts", None),
        ("vendor/app/route.js", None),
        (".next/app/route.ts", None),
        ("app/page.tsx", None),
        ("middleware.ts", None),
    ],
)
def test_filesystem_route_contract(
    tmp_path: Path, path: str, expected: str | None
) -> None:
    put(
        tmp_path, path, "export function GET() {}\nexport default function handler() {}"
    )
    result = extract(tmp_path)
    assert {a.path for a in result.anchors} == (
        {expected} if expected is not None else set()
    )


@pytest.mark.parametrize(
    "declaration",
    [
        "export async function GET() {}",
        "export function GET() {}",
        "export const GET = () => {};",
        "export const GET = function () {};",
        "const handler = () => {}; export const GET = handler;",
        "function handler() {} export { handler as GET };",
        "const GET = () => {}; export { GET };",
    ],
)
def test_app_export_forms(tmp_path: Path, declaration: str) -> None:
    put(tmp_path, "app/route.ts", declaration + "\nexport function TRACE() {}")
    assert [(a.method, a.path) for a in extract(tmp_path).anchors] == [("GET", "/")]


@pytest.mark.parametrize(
    "default",
    [
        "export default function handler() {}",
        "export default async function () {}",
        "const handler = () => {}; export default handler;",
        "export default async (request) => {};",
    ],
)
def test_pages_default_forms(tmp_path: Path, default: str) -> None:
    put(tmp_path, "pages/api/index.ts", default + "\nexport function GET() {}")
    assert [(a.method, a.path) for a in extract(tmp_path).anchors] == [("ANY", "/api")]


@pytest.mark.parametrize("extension", ["ts", "tsx", "js", "jsx"])
@pytest.mark.parametrize(
    "directive",
    ["'use server';", '/* comment */ "use server";', "// comment\n'use server';"],
)
def test_server_directive_and_async_forms(
    tmp_path: Path, extension: str, directive: str
) -> None:
    put(
        tmp_path,
        f"actions.{extension}",
        directive
        + """
export async function first() {}
export const second = async () => {};
export const third = async function () {};
export const sync = () => {};
""",
    )
    assert {a.path for a in extract(tmp_path).anchors} == {
        f"actions.{extension}#{name}" for name in ("first", "second", "third")
    }


@pytest.mark.parametrize(
    "source",
    [
        "export async function action() { 'use server'; }",
        "const before = 1; 'use server'; export async function action() {}",
    ],
)
def test_inline_or_late_server_directive_is_not_a_file_action(
    tmp_path: Path, source: str
) -> None:
    put(tmp_path, "actions.ts", source)
    assert not extract(tmp_path).anchors


@pytest.mark.parametrize(
    "method", ["parse", "safeParse", "parseAsync", "safeParseAsync"]
)
@pytest.mark.parametrize(
    "binding",
    [
        "import { z } from 'zod';",
        "import { z as z } from 'zod';",
        "import * as z from 'zod';",
    ],
)
def test_used_zod_schema_through_relative_barrels(
    tmp_path: Path, method: str, binding: str
) -> None:
    put(
        tmp_path,
        "schemas/input.ts",
        binding
        + """
export const TeamInput = z.object({
  name: z.string().min(1), 'email': z.string().email(),
  nested: z.object({ inside: z.string() }),
  shorthand, ...other, [computed]: z.number(),
}).strict();
""",
    )
    put(
        tmp_path, "schemas/index.ts", "export { TeamInput as Input } from './input.js';"
    )
    put(tmp_path, "barrel.ts", "export * from './schemas';")
    put(
        tmp_path,
        "app/route.ts",
        "import { Input as Schema } from '../barrel';\n"
        + f"export async function POST(req) {{ Schema.{method}(req); "
        + "Schema.parse(req); }",
    )
    anchor = extract(tmp_path).anchors[0]
    assert [h.name for h in anchor.hints if h.kind == "input_type"] == ["TeamInput"]
    assert {h.name for h in anchor.hints if h.kind == "input_rule"} == {
        "name",
        "email",
        "nested",
    }


@pytest.mark.parametrize("extension", ["ts", "js", "jsx", "tsx"])
def test_local_schema_and_actual_zod_alias(tmp_path: Path, extension: str) -> None:
    put(
        tmp_path,
        f"actions.{extension}",
        """'use server';
import { z as schema } from 'zod';
const Input = schema.object({ name: schema.string() });
export async function action(input) { Input.parse(input); }
""",
    )
    assert any(
        h.kind == "input_type" and h.name == "Input"
        for h in extract(tmp_path).anchors[0].hints
    )


@pytest.mark.parametrize(
    "source",
    [
        "const z = custom; const Input = z.object({name: z.string()}); "
        "export function POST(x) { Input.parse(x); }",
        "import { z } from 'other'; const Input = z.object({name: z.string()}); "
        "export function POST(x) { Input.parse(x); }",
        "import { z } from 'zod'; export function POST(x) { "
        "const Input = z.object({name:z.string()}); Input.parse(x); }",
        "import { z } from 'zod'; const Input=z.object({name:z.string()}); "
        "export function POST(Input) { Input.parse({}); }",
        "import { z } from 'zod'; const Input=z.object({name:z.string()}); "
        "export const POST = Input => Input.parse({});",
    ],
)
def test_unbound_or_local_schema_calls_give_no_input_hints(
    tmp_path: Path, source: str
) -> None:
    put(tmp_path, "app/route.ts", source)
    assert not any(
        h.kind.startswith("input_") for h in extract(tmp_path).anchors[0].hints
    )


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        ("GET", "read"),
        ("HEAD", "read"),
        ("OPTIONS", None),
        ("POST", "add"),
        ("PUT", "change"),
        ("PATCH", "change"),
        ("DELETE", "remove"),
    ],
)
def test_http_methods_and_operations(
    tmp_path: Path, method: str, operation: str | None
) -> None:
    put(tmp_path, "app/route.js", f"export const {method} = () => {{}};")
    anchor = extract(tmp_path).anchors[0]
    assert anchor.method == method
    assert [h.value for h in anchor.hints if h.kind == "operation"] == (
        [operation] if operation else []
    )


@pytest.mark.parametrize("extension", ["ts", "tsx", "js", "jsx"])
@pytest.mark.parametrize(
    "barrel",
    [
        "export { Input as default } from './schema';",
        "import { Input } from './schema'; export default Input;",
    ],
)
def test_default_schema_imports_and_index_files(
    tmp_path: Path, extension: str, barrel: str
) -> None:
    put(
        tmp_path,
        f"schemas/schema.{extension}",
        "import * as z from 'zod'; "
        "export const Input = z.object({ name: z.string() });",
    )
    put(tmp_path, f"schemas/index.{extension}", barrel)
    put(
        tmp_path,
        "app/route.js",
        "import Schema from '../schemas'; "
        "export function POST(req) { Schema.parse(req); }",
    )
    assert [
        h.name for h in extract(tmp_path).anchors[0].hints if h.kind == "input_type"
    ] == ["Input"]


@pytest.mark.parametrize(
    "source",
    [
        "import { handler } from './missing'; export const GET = handler;",
        "export { handler as GET };",
    ],
)
def test_unfollowed_handler_cites_export(tmp_path: Path, source: str) -> None:
    put(tmp_path, "app/route.ts", source)
    anchor = extract(tmp_path).anchors[0]
    assert anchor.handler is not None
    assert anchor.handler.symbol == "app/route.ts#GET"
    assert anchor.handler.citation == anchor.citations[0]


def test_nested_bindings_do_not_hide_module_schema_uses(tmp_path: Path) -> None:
    put(
        tmp_path,
        "app/route.ts",
        """
import { z } from 'zod';
const Input = z.object({ name: z.string() });
export function POST(req) {
  function other(Input) { Input.parse(req); }
  { const Input = custom; Input.parse(req); }
  return Input.parse(req);
}
""",
    )
    assert [
        h.name for h in extract(tmp_path).anchors[0].hints if h.kind == "input_type"
    ] == ["Input"]


def test_non_handler_exports_and_import_cycles_give_no_spurious_hints(
    tmp_path: Path,
) -> None:
    put(tmp_path, "schemas.ts", "export * from './other';")
    put(tmp_path, "other.ts", "export * from './schemas';")
    put(
        tmp_path,
        "app/route.ts",
        "import { Input } from '../schemas'; "
        "export const POST = () => { Input.parse({}); }; "
        "export const GET = 42; export const DELETE = factory();",
    )
    anchors = extract(tmp_path).anchors
    assert [a.method for a in anchors] == ["POST"]
    assert not any(h.kind.startswith("input_") for h in anchors[0].hints)


def test_entry_points_use_repository_relative_paths(tmp_path: Path) -> None:
    repositories = tuple(
        RepositoryRef(key=name, path=name, commit="1" * 40, dirty=False)
        for name in ("web", "app", "pages", "_legacy")
    )
    files = {
        "web/actions.ts": "'use server'; export async function save() {}",
        "app/src/app/api/y/route.ts": "export function GET() {}",
        "pages/pages/api/z.ts": "export default function handler() {}",
        "_legacy/app/api/q/route.ts": "export function GET() {}",
    }
    for path, source in files.items():
        put(tmp_path, path, source)
    result = build_structure(tmp_path, repositories)
    assert {
        (a.repository, a.method, a.path, a.handler.symbol)
        for a in result.anchors
        if a.handler is not None
    } == {
        ("web", None, "actions.ts#save", "actions.ts#save"),
        ("app", "GET", "/api/y", "src/app/api/y/route.ts#GET"),
        ("pages", "ANY", "/api/z", "pages/api/z.ts#default"),
        ("_legacy", "GET", "/api/q", "app/api/q/route.ts#GET"),
    }
    for anchor in result.anchors:
        assert anchor.id == anchor_id(
            anchor.repository, anchor.kind, anchor.method, anchor.path
        )
        assert anchor.handler is not None and anchor.handler.citation is not None
        assert anchor.handler.citation.path in files


@pytest.mark.parametrize("prefix", ["apps/_shared", "_archive"])
def test_private_folders_above_routing_tree_are_not_skipped(
    tmp_path: Path, prefix: str
) -> None:
    put(tmp_path, f"{prefix}/app/api/route.ts", "export function GET() {}")
    put(
        tmp_path, f"{prefix}/pages/api/index.ts", "export default function handler() {}"
    )
    assert {(a.method, a.path) for a in extract(tmp_path).anchors} == {
        ("GET", "/api"),
        ("ANY", "/api"),
    }


def test_deep_handler_body_does_not_drop_nextjs_anchors(tmp_path: Path) -> None:
    expression = " + ".join("'term'" for _ in range(600))
    put(tmp_path, "app/route.ts", f"export function GET() {{ return {expression}; }}")
    put(tmp_path, "app/other/route.ts", "export function POST() {}")
    result = extract(tmp_path)
    assert {(a.method, a.path) for a in result.anchors} == {
        ("GET", "/"),
        ("POST", "/other"),
    }
    assert not any(f.reason == "unreadable_source" for f in result.findings)


@pytest.mark.parametrize(
    "parameters, body",
    [
        ("{ T }", "T.parse(1);"),
        ("{ T = fallback }", "T.parse(1);"),
        ("{ input: T }", "T.parse(1);"),
        ("{ input: { value: T = fallback } }", "T.parse(1);"),
        ("[T]", "T.parse(1);"),
        ("[, [T = fallback]]", "T.parse(1);"),
        ("r", "const { T } = r; T.parse(1);"),
        ("r", "const { T = fallback } = r; T.parse(1);"),
        ("r", "const { input: { value: T = fallback } } = r; T.parse(1);"),
        ("r", "const [, [T = fallback]] = r; T.parse(1);"),
        ("r", "for (const T of r) { T.parse(1); }"),
        ("r", "for (const { input: T } of r) { T.parse(1); }"),
        ("r", "for (let [T] of r) { T.parse(1); }"),
        ("r", "for (const T in r) { T.parse(1); }"),
        ("r", "for (var T of r) {} T.parse(1);"),
        ("r", "try {} catch ({ input: T }) { T.parse(1); }"),
    ],
)
@pytest.mark.parametrize("extension", ["ts", "js"])
def test_destructured_and_loop_bindings_shadow_module_schema(
    tmp_path: Path, parameters: str, body: str, extension: str
) -> None:
    put(
        tmp_path,
        f"app/route.{extension}",
        "import { z } from 'zod'; "
        "const T = z.object({ a: z.string() }); "
        f"export async function POST({parameters}) {{ {body} }}",
    )
    anchor = extract(tmp_path).anchors[0]
    assert anchor.method == "POST"
    assert not any(h.kind.startswith("input_") for h in anchor.hints)


@pytest.mark.parametrize(
    "body",
    [
        "for (const T of r) { T.parse(1); } T.parse(1);",
        "{ const { T } = r; T.parse(1); } T.parse(1);",
        "const { T: other } = r; T.parse(1);",
        "const { other = T.parse(1) } = r;",
    ],
)
def test_only_bound_names_in_their_scope_shadow_module_schema(
    tmp_path: Path, body: str
) -> None:
    put(
        tmp_path,
        "app/route.ts",
        "import { z } from 'zod'; "
        "const T = z.object({ a: z.string() }); "
        f"export async function POST(r) {{ {body} }}",
    )
    assert [
        h.name for h in extract(tmp_path).anchors[0].hints if h.kind == "input_type"
    ] == ["T"]


@pytest.mark.parametrize(
    "implementation",
    [
        "export async function actual(req) { T.parse(req); }",
        "export const actual = async (req) => { T.parse(req); };",
    ],
)
def test_relative_method_reexports_follow_handler_and_schema(
    tmp_path: Path, implementation: str
) -> None:
    put(
        tmp_path,
        "impl.ts",
        "import { z } from 'zod';\n"
        "const T = z.object({ a: z.string() });\n" + implementation,
    )
    put(
        tmp_path,
        "barrel/index.ts",
        "export { actual as GET, actual as POST } from '../impl';",
    )
    put(tmp_path, "app/route.ts", "export { GET, POST } from '../barrel';")
    anchors = extract(tmp_path).anchors
    assert {a.method for a in anchors} == {"GET", "POST"}
    for anchor in anchors:
        assert anchor.handler is not None
        assert anchor.handler.symbol == f"app/route.ts#{anchor.method}"
        assert anchor.handler.citation is not None
        assert anchor.handler.citation.path == "impl.ts"
        assert anchor.handler.citation.start_line == 3
        assert anchor.citations[0].path == "app/route.ts"
        assert [h.name for h in anchor.hints if h.kind == "input_type"] == ["T"]
        assert [(h.name, h.value) for h in anchor.hints if h.kind == "input_rule"] == [
            ("a", "z.string()")
        ]


@pytest.mark.parametrize(
    "source",
    [
        "export { GET, POST } from './missing';",
        "export { actual as GET, actual as POST } from './missing';",
        "export const { GET, POST } = handlers;",
        "export const { a: GET, b: POST, other } = handlers;",
    ],
)
def test_unfollowed_reexports_and_destructured_methods_cite_registration(
    tmp_path: Path, source: str
) -> None:
    put(tmp_path, "app/route.ts", source)
    anchors = extract(tmp_path).anchors
    assert {a.method for a in anchors} == {"GET", "POST"}
    for anchor in anchors:
        assert anchor.handler is not None
        assert anchor.handler.symbol == f"app/route.ts#{anchor.method}"
        assert anchor.handler.citation == anchor.citations[0]
        assert not any(h.kind.startswith("input_") for h in anchor.hints)


@pytest.mark.parametrize("extension", ["tsx", "js", "jsx"])
def test_jsx_in_server_file_does_not_hide_later_exports(
    tmp_path: Path, extension: str
) -> None:
    put(
        tmp_path,
        f"actions.{extension}",
        """'use server';
const view = <section><span>Example</span></section>;
export async function first() { return view; }
export const second = async () => <div>Done</div>;
""",
    )
    expected = {f"actions.{extension}#first", f"actions.{extension}#second"}
    if extension in {"js", "jsx"}:
        put(
            tmp_path,
            f"app/actions.{extension}",
            "'use server';\n"
            "export async function a(x) { return x < y && z > (w) }\n"
            "export async function b() {}\n",
        )
        expected.update({f"app/actions.{extension}#a", f"app/actions.{extension}#b"})
    result = extract(tmp_path)
    assert {a.path for a in result.anchors} == expected


@pytest.mark.parametrize("module", ["zod", "zod/v4", "zod/v3"])
@pytest.mark.parametrize("binding", ["z", "{ z }", "{ z as z }", "* as z"])
def test_zod_versions_and_default_import(
    tmp_path: Path, module: str, binding: str
) -> None:
    put(
        tmp_path,
        "app/route.ts",
        f"import {binding} from '{module}'; "
        "const T = z.object({ a: z.string() }); "
        "export function POST(r) { T.parse(r); }",
    )
    hints = extract(tmp_path).anchors[0].hints
    assert [h.name for h in hints if h.kind == "input_type"] == ["T"]
    assert [(h.name, h.value) for h in hints if h.kind == "input_rule"] == [
        ("a", "z.string()")
    ]
