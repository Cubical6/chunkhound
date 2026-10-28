# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: tests/static_analyzer/test_source_inspector.py; license: chunkhound/code_mapper/c4/codeboarding/LICENSE.
# Changes: redirect imports to the vendored package.
# Changes: use a project-local CallSite path literal.
# Changes: retain Python, JS, TS, TSX, PHP and language-independent behavior tests only.
# Changes: cover source-only inheritance for target grammars and JSX identifier positions.
"""Tests for chunkhound.code_mapper.c4.codeboarding.source_inspector.SourceInspector."""

import re
from pathlib import Path

import pytest

from chunkhound.code_mapper.c4.codeboarding.models import CallSite
from chunkhound.code_mapper.c4.codeboarding.source_inspector import SourceInspector


def _positions(sites: list[CallSite]) -> set[tuple[int, int]]:
    return {(site.line, site.column) for site in sites}


def test_call_site_exposes_human_and_lsp_positions() -> None:
    site = CallSite.from_lsp_position(file=".scratch/app.py", line=0, column=4)

    assert site.line == 1
    assert site.column == 5
    assert site.human_line == 1
    assert site.human_column == 5
    assert site.lsp_line == 0
    assert site.lsp_column == 4


@pytest.mark.parametrize(
    "suffix,source",
    [
        ("py", "def f(x: Ignored):\n try: pass\n except (m.ExpectedOne, ExpectedTwo) as bound: pass\n"),
        ("py", "try: pass\nexcept* m.ExpectedOne as bound: pass\ntry: pass\nexcept: pass\n"),
        (
            "py",
            "def f(x):\n    match x:\n        case ExpectedOne(a=1, b=m.ExpectedTwo()):\n            pass\n"
            "        case E.VALUE | ExpectedThree() | [ExpectedFour(), *rest]:\n            pass\n"
            "        case ExpectedFive() as bound if guard:\n            pass\n        case capture:\n            pass\n",
        ),

        ("php", "<?php function f(Ignored $x) { try {} catch (N\\ExpectedOne | ExpectedTwo $e) {} }"),
        ("php", "<?php function f($x) { if ($x instanceof N\\ExpectedOne) {} }"),
        ("ts", "function f(x: Ignored) { try {} catch (bound) { if (bound instanceof N.ExpectedOne) {} } }"),
        ("js", "function f() { try {} catch { } try {} catch (bound) { if (bound instanceof ExpectedOne) {} } }"),

    ],
)
def test_runtime_references_exclude_bindings_and_annotations(tmp_path: Path, suffix: str, source: str) -> None:
    path = tmp_path / f"sample.{suffix}"
    path.write_text(source)
    expected = {
        (source[: match.start()].count("\n") + 1, match.start() - source.rfind("\n", 0, match.start()))
        for match in re.finditer(r"Expected\w+", source)
    }
    inspector = SourceInspector()
    sites = inspector.find_runtime_reference_sites(path)
    assert _positions(sites) == expected
    assert not any(inspector.is_construction_site(site) for site in sites)


class TestGetSourceLine:
    def test_reads_existing_line(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("line0\nline1\nline2\n")
        si = SourceInspector()
        assert si.get_source_line(f, 0) == "line0"
        assert si.get_source_line(f, 1) == "line1"
        assert si.get_source_line(f, 2) == "line2"

    def test_returns_none_for_out_of_range(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("only one line")
        si = SourceInspector()
        assert si.get_source_line(f, 100) is None

    def test_returns_none_for_missing_file(self):
        si = SourceInspector()
        assert si.get_source_line(Path("/nonexistent/file.py"), 0) is None

    def test_caches_file_content(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("cached")
        si = SourceInspector()
        si.get_source_line(f, 0)
        # Modify file — cached version should still be returned
        f.write_text("modified")
        assert si.get_source_line(f, 0) == "cached"



class TestIsConstructionSite:
    """Which call sites run a constructor, for constructor expansion."""



    def test_conservative_on_missing_file(self):
        site = CallSite.from_lsp_position(file="/nonexistent.java", line=0, column=0)
        assert SourceInspector().is_construction_site(site) is False

class TestFindCallSites:
    def test_finds_regular_calls(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("foo()\nbar(x)\n")
        si = SourceInspector()
        sites = si.find_call_sites(f)
        positions = _positions(sites)
        assert (1, 1) in positions  # foo
        assert (2, 1) in positions  # bar


    def test_a_private_method_call_queries_the_member(self, tmp_path: Path):
        """``this`` resolves to the class, so querying there names no method at all."""
        f = tmp_path / "test.js"
        f.write_text("class A {\n  #save() {}\n  run() { this.#save(); }\n}\n")
        si = SourceInspector()
        assert (3, 16) in _positions(si.find_call_sites(f))  # #save

    def test_a_column_counts_utf16_units_not_bytes(self, tmp_path: Path):
        """A server reads the character as UTF-16; bytes would land past the callee."""
        f = tmp_path / "test.py"
        f.write_text("s = 'héllo wörld'; target()\n", encoding="utf-8")
        si = SourceInspector()
        assert (1, 20) in _positions(si.find_call_sites(f))  # target

    def test_returns_empty_for_missing_file(self):
        si = SourceInspector()
        assert si.find_call_sites(Path("/nonexistent.py")) == []


    def test_reads_module_suffixes(self, tmp_path: Path):
        f = tmp_path / "test.mjs"
        f.write_text("foo()\n")
        si = SourceInspector()

        assert (1, 1) in _positions(si.find_call_sites(f))

class TestValueBindings:
    """Binding a callable to a name passes it as a value; each grammar spells it its own way."""

    def _sites(self, path: Path) -> set[tuple[int, int]]:
        return {(site.line, site.column) for site in SourceInspector().find_method_group_sites(path)}

    def test_python_assignment(self, tmp_path: Path):
        source = tmp_path / "app.py"
        source.write_text("def handler():\n    pass\n\n\ndef build():\n    callback = handler\n")

        assert (6, 16) in self._sites(source)


    def test_python_parameter_default(self, tmp_path: Path):
        source = tmp_path / "app.py"
        source.write_text("def handler():\n    pass\n\n\ndef run(callback=handler, typed: int = handler):\n    pass\n")

        assert {(5, 18), (5, 40)} <= self._sites(source)

    def test_typescript_class_field(self, tmp_path: Path):
        source = tmp_path / "app.ts"
        source.write_text("function handler() {}\n\nclass Widget {\n  private cb = handler;\n}\n")

        assert (4, 16) in self._sites(source)

    def test_javascript_class_field(self, tmp_path: Path):
        source = tmp_path / "app.js"
        source.write_text("function handler() {}\n\nclass Widget {\n  cb = handler;\n}\n")

        assert (4, 8) in self._sites(source)


class TestParseErrorsAreReported:
    def test_a_file_the_grammar_cannot_parse_is_logged(self, tmp_path: Path, caplog):
        """A call the parser swallowed is an edge lost, and a silent loss is the worst kind."""
        source = tmp_path / "broken.py"
        source.write_text("def run(:\n    helper(\n")

        with caplog.at_level("WARNING"):
            SourceInspector().find_call_sites(source)

        assert any("error node" in record.getMessage() for record in caplog.records)


class TestDeclaredNameAt:
    def test_a_declaration_name_is_declared_here(self, tmp_path: Path):
        source = tmp_path / "app.ts"
        source.write_text("export function target() { return 1; }\n")

        assert SourceInspector().declared_name_at(source, 0, 16) == "target"

    def test_an_import_binding_is_not(self, tmp_path: Path):
        """A server answers at an import binding as readily as at a declaration.

        Reading the name there as one this file declares matches it to whatever the file
        happens to declare under the same name -- a different function entirely.
        """
        source = tmp_path / "app.ts"
        source.write_text('import { target as other } from "./b";\nexport function target() { return 2; }\n')

        assert SourceInspector().declared_name_at(source, 0, 9) == ""

    def test_a_python_aliased_import_is_not(self, tmp_path: Path):
        source = tmp_path / "app.py"
        source.write_text("from b import target as other\n\n\ndef target():\n    return 2\n")

        assert SourceInspector().declared_name_at(source, 0, 14) == ""

    def test_a_parameter_sharing_a_declarations_name_is_not(self, tmp_path: Path):
        source = tmp_path / "app.ts"
        source.write_text("export function render(graph: Graph) { return graph; }\nexport function graph() {}\n")

        assert SourceInspector().declared_name_at(source, 0, 23) == ""

    def test_a_column_past_an_astral_character_counts_utf16_units(self, tmp_path: Path):
        source = tmp_path / "app.ts"
        source.write_text('const s = "\U0001f600"; export function target() {}\n', encoding="utf-8")

        assert SourceInspector().declared_name_at(source, 0, 32) == "target"


class TestReturnedAndGroupedValues:
    """A callable handed back, or held in a literal, is passed as a value in each grammar's spelling."""

    def _sites(self, path: Path) -> set[tuple[int, int]]:
        return {(site.line, site.column) for site in SourceInspector().find_method_group_sites(path)}

    def test_python_yield(self, tmp_path: Path):
        source = tmp_path / "app.py"
        source.write_text("def gen():\n    yield handler\n")

        assert (2, 11) in self._sites(source)


class TestTreeCacheEviction:
    def test_single_file_larger_than_budget_is_still_usable(self, tmp_path: Path):
        f = tmp_path / "big.py"
        f.write_text("\n".join(f"call{i}()" for i in range(200)))
        si = SourceInspector(tree_node_budget=1)

        assert len(si.find_call_sites(f)) == 200

class TestConditionalCompilationBodies:

    def test_a_hash_comment_language_is_left_alone(self, tmp_path: Path):
        # ``#`` opens a comment in Python; blanking those lines would be wrong.
        f = tmp_path / "mod.py"
        f.write_text("# call_me()\ndef f():\n    real()\n")
        si = SourceInspector()
        positions = _positions(si.find_call_sites(f))
        assert (3, 5) in positions
        assert not any(p[0] == 1 for p in positions)

class TestJsxElementSites:
    def test_rendering_a_component_is_a_call_site(self, tmp_path: Path):
        f = tmp_path / "app.tsx"
        f.write_text("export function App() {\n  return <Card x={1} />;\n}\n")
        si = SourceInspector()

        assert (2, 11) in _positions(si.find_call_sites(f))

    def test_a_dotted_element_name_resolves_to_its_last_part(self, tmp_path: Path):
        f = tmp_path / "app.tsx"
        f.write_text("export function App() {\n  return <ns.Card>{1}</ns.Card>;\n}\n")
        si = SourceInspector()
        positions = _positions(si.find_call_sites(f))

        assert (2, 14) in positions  # Card in the opening tag
        assert (2, 11) not in positions  # ns, the namespace it hangs off
        assert (2, 25) not in positions  # Card in the closing tag

    def test_a_jsx_attribute_expression_is_a_method_group(self, tmp_path: Path):
        f = tmp_path / "app.tsx"
        f.write_text("export function App() {\n  return <Card onClick={handler} x={1} />;\n}\n")
        si = SourceInspector()
        positions = _positions(si.find_method_group_sites(f))

        assert (2, 25) in positions  # handler
        assert (2, 16) not in positions  # onClick, the attribute name


class TestOptionalChaining:
    def test_a_php_nullsafe_member_call_is_a_call_site(self, tmp_path: Path):
        f = tmp_path / "app.php"
        f.write_text("<?php\nfunction label(?Task $t): string {\n    return $t?->getLabel() ?? 'none';\n}\n")
        si = SourceInspector()

        assert (3, 17) in _positions(si.find_call_sites(f))

    def test_typescript_optional_chaining_needs_no_entry_of_its_own(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("export function label(t?: Task) {\n    return t?.getLabel();\n}\n")
        si = SourceInspector()

        assert (2, 15) in _positions(si.find_call_sites(f))



class TestDecoratorSites:
    def test_a_bare_python_decorator_is_a_call_site(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("@register\ndef run():\n    pass\n")
        si = SourceInspector()

        assert (1, 2) in _positions(si.find_call_sites(f))

    def test_a_dotted_decorator_resolves_to_the_member(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("@registry.add\ndef run():\n    pass\n")
        si = SourceInspector()
        positions = _positions(si.find_call_sites(f))

        assert (1, 11) in positions  # add
        assert (1, 2) not in positions  # registry

    def test_an_applied_decorator_is_counted_once(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("@cache(maxsize=2)\ndef run():\n    pass\n")
        si = SourceInspector()
        positions = [(site.line, site.column) for site in si.find_call_sites(f)]

        assert positions.count((1, 2)) == 1

    def test_a_typescript_decorator_is_a_call_site(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("@Injectable\nexport class Service {}\n")
        si = SourceInspector()

        assert (1, 2) in _positions(si.find_call_sites(f))


class TestKeywordArgumentValues:
    def test_the_value_is_the_site_not_the_keyword(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("def run():\n    subscribe(key=handler)\n")
        si = SourceInspector()
        positions = _positions(si.find_method_group_sites(f))

        assert (2, 19) in positions  # handler
        assert (2, 15) not in positions  # key, the keyword


class TestDeclaresFunctionValue:
    def test_an_arrow_bound_to_a_const(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("const handler = () => 1;\n")
        si = SourceInspector()

        assert si.declares_function_value(f, 0, 6) is True

    def test_a_function_in_an_object_literal(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("const api = { load: function () {} };\n")
        si = SourceInspector()

        assert si.declares_function_value(f, 0, 14) is True

    def test_a_python_lambda_bound_to_a_name(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("double = lambda x: x * 2\n")
        si = SourceInspector()

        assert si.declares_function_value(f, 0, 0) is True

    def test_a_constant_is_not_a_function_value(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("const LIMIT = 5;\n")
        si = SourceInspector()

        assert si.declares_function_value(f, 0, 6) is False

    def test_a_declared_function_is_not_a_function_value(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("function handler() { return 1; }\n")
        si = SourceInspector()

        assert si.declares_function_value(f, 0, 9) is False

    def test_both_names_of_a_chained_assignment_map_to_the_one_literal(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("var allocate = (Mod.allocate = function () {\n  return 0;\n});\n")

        assert SourceInspector().function_values(f) == {(0, 4): (0, 31), (0, 20): (0, 31)}

    def test_a_member_assigned_a_lambda(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("class A:\n    def __init__(self):\n        self.on_move = lambda event: event\n")

        assert SourceInspector().declares_function_value(f, 2, 13) is True


class TestReceiversOf:
    def test_each_call_on_a_bare_receiver_is_keyed_by_that_receiver(self, tmp_path: Path):
        f = tmp_path / "app.js"
        f.write_text("import { log } from './log';\nexport function run() {\n  log.warn('x');\n  log.info('y');\n}\n")
        si = SourceInspector()

        receivers = si.receivers_of(f, si.find_call_sites(f))

        assert {at: (site.lsp_line, site.lsp_column, member) for at, (site, member) in receivers.items()} == {
            (2, 2): (2, 6, "warn"),
            (3, 2): (3, 6, "info"),
        }

    def test_a_chained_receiver_is_not_a_bare_name(self, tmp_path: Path):
        f = tmp_path / "app.js"
        f.write_text("export function run() {\n  api.client.send('x');\n}\n")
        si = SourceInspector()

        assert si.receivers_of(f, si.find_call_sites(f)) == {}

    def test_a_plain_call_has_no_receiver(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("def run():\n    helper()\n")
        si = SourceInspector()

        assert si.receivers_of(f, si.find_call_sites(f)) == {}


class TestNamesBaseMember:
    def _bound(self, path: Path, source: str, line: int, column: int) -> bool:
        path.write_text(source)
        return SourceInspector().names_base_member(CallSite.from_lsp_position(str(path), line, column))

    def test_a_base_member_read_rather_than_called(self, tmp_path: Path):
        source = "class A extends B {\n  m() {\n    super.m.apply(this, arguments);\n  }\n}\n"

        assert self._bound(tmp_path / "a.ts", source, 2, 10)
        assert not self._bound(tmp_path / "a.ts", source, 2, 12)

    def test_typescript_super_member(self, tmp_path: Path):
        assert self._bound(tmp_path / "a.ts", "class A extends B {\n  m() {\n    super.m();\n  }\n}\n", 2, 10)

    def test_python_super_call_member(self, tmp_path: Path):
        assert self._bound(tmp_path / "a.py", "class A(B):\n    def m(self):\n        super().m()\n", 2, 16)


    def test_php_parent_member(self, tmp_path: Path):
        source = "<?php\nclass A extends B {\n  function m() {\n    parent::m();\n  }\n}\n"
        assert self._bound(tmp_path / "a.php", source, 3, 12)

    def test_a_member_on_this_or_another_receiver_dispatches(self, tmp_path: Path):
        f = tmp_path / "a.ts"
        source = "class A extends B {\n  constructor() {\n    super();\n    this.m();\n    other.m();\n  }\n}\n"

        # ``super()`` itself constructs; the target's kind, not the receiver, rules that out.
        assert not self._bound(f, source, 2, 4)
        assert not self._bound(f, source, 3, 9)
        assert not self._bound(f, source, 4, 10)


class TestFindMemberSites:
    def test_reads_and_writes_under_a_listed_name(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text(
            "class Panel {\n"
            "  connect(fast: boolean) {\n"
            "    const bound = this.redraw.bind(this);\n"
            "    this.model.size = 3;\n"
            "    return fast ? this.redraw : this.other;\n"
            "  }\n"
            "}\n"
        )

        reads, writes = SourceInspector().find_member_sites(f, {"redraw", "size"})

        assert _positions(reads) == {(3, 24), (5, 24)}
        assert _positions(writes) == {(4, 16)}

    def test_a_python_attribute_read(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("def run(engine):\n    if engine.dirs:\n        return engine.name\n")

        reads, writes = SourceInspector().find_member_sites(f, {"dirs"})

        assert _positions(reads) == {(2, 15)}
        assert writes == []

    def test_a_member_named_in_a_type_is_not_read(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text(
            "type Icon = ReturnType<typeof graphic.createIcon>;\nfunction draw(make: typeof graphic.createIcon) {}\n"
        )

        assert SourceInspector().find_member_sites(f, {"createIcon"}) == ([], [])

    def test_a_python_annotation_is_not_read(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("def run(engine: mod.Engine) -> mod.Engine:\n    return engine\n")

        assert SourceInspector().find_member_sites(f, {"Engine"}) == ([], [])


class TestOverloadImplementations:
    def test_each_signature_maps_to_the_implementation_below_it(self, tmp_path: Path):
        f = tmp_path / "graph.ts"
        f.write_text(
            "class Node {\n"
            "  getModel(): number;\n"
            "  getModel(path: string): number;\n"
            "  getModel(path?: string): number { return 1; }\n"
            "}\n"
            "class Edge {\n"
            "  getModel(): number;\n"
            "  getModel(path?: string): number { return 2; }\n"
            "}\n"
            "export function make(a: string): void;\n"
            "export function make(a: any): void {}\n"
            "interface Api {\n"
            "  load(x: string): void;\n"
            "  load(x: number): void;\n"
            "}\n"
        )

        assert SourceInspector().overload_implementations(f) == {
            (1, 2): (3, 2),
            (2, 2): (3, 2),
            (6, 2): (7, 2),
            (9, 16): (10, 16),
        }


class TestDeclaresSetter:
    def test_a_typescript_set_accessor(self, tmp_path: Path):
        f = tmp_path / "m.ts"
        f.write_text("class M {\n  get size() { return 1; }\n  set size(v: number) {}\n}\n")
        si = SourceInspector()

        assert si.declares_setter(f, 2, 6) is True
        assert si.declares_setter(f, 1, 6) is False

    def test_a_python_property_setter(self, tmp_path: Path):
        f = tmp_path / "m.py"
        f.write_text(
            "class M:\n    @property\n    def size(self):\n        return 1\n\n"
            "    @size.setter\n    def size(self, value):\n        pass\n"
        )
        si = SourceInspector()

        assert si.declares_setter(f, 6, 8) is True
        assert si.declares_setter(f, 2, 8) is False



class TestChainedComparisons:
    def test_a_chained_comparison_shape_in_another_language_is_left_alone(self, tmp_path: Path):
        f = tmp_path / "m.js"
        f.write_text("const x = a < b > (c);\n")
        assert SourceInspector().find_call_sites(f) == []


@pytest.mark.parametrize(
    "suffix,source,expected",
    [
        ("py", "class Dog(Animal):\n pass\n", [("Dog", ["Animal"])]),
        ("py", "class Duck(Animal, SwimmingMixin, metaclass=M):\n pass\n",
         [("Duck", ["Animal", "SwimmingMixin"])]),
        ("py", "class A(metaclass=M):\n pass\n", []),
        ("py", "class Dog(\n Animal,\n SwimmingMixin,\n):\n pass\n",
         [("Dog", ["Animal", "SwimmingMixin"])]),
        ("js", "class Dog extends Animal {}", [("Dog", ["Animal"])]),
        ("jsx", "class Dog extends Animal { render() { return <Card />; } }",
         [("Dog", ["Animal"])]),
        ("ts", "class Dog extends Animal<T> implements Walker, Runner {}",
         [("Dog", ["Animal", "Walker", "Runner"])]),
        ("tsx", "class Dog extends Animal { render() { return <Card />; } }",
         [("Dog", ["Animal"])]),
        ("ts", "interface Dog extends Animal, Walker {}", [("Dog", ["Animal", "Walker"])]),
        ("php", "<?php class Dog extends Animal implements Walker, Runner {}",
         [("Dog", ["Animal", "Walker", "Runner"])]),
        ("php", "<?php interface Dog extends Animal, Walker {}",
         [("Dog", ["Animal", "Walker"])]),
        ("py", "class Plain:\n pass\n", []),
    ],
)
def test_inheritance_is_read_without_a_language_server(tmp_path, suffix, source, expected):
    path = tmp_path / f"sample.{suffix}"
    path.write_text(source)
    assert SourceInspector().find_type_bases(path) == expected


@pytest.mark.parametrize("suffix", ["jsx", "tsx"])
def test_jsx_calls_and_identifier_positions(tmp_path, suffix):
    path = tmp_path / f"sample.{suffix}"
    path.write_text("const view = <Card />;\n")
    inspector = SourceInspector()
    assert _positions(inspector.find_call_sites(path)) == {(1, 15)}
    assert inspector.identifier_at(path, 0, 14) == "Card"
