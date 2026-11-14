"""Literal Magento data-patch attributes, attached to the declarative schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.structure.files import select_files
from chunkhound.domain_model.structure.readers._magento import Module
from chunkhound.domain_model.structure.readers._php import (
    arguments,
    literal_text,
    span,
    text,
    walk,
)
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext

READER = "magento_eav"
ENTITIES = {
    "catalog_product": "catalog_product_entity",
    "catalog_category": "catalog_category_entity",
    "customer": "customer_entity",
    "customer_address": "customer_address_entity",
}
CONSTANTS = {
    "Magento\\Catalog\\Model\\Product::ENTITY": "catalog_product",
    "Magento\\Catalog\\Model\\Category::ENTITY": "catalog_category",
    "Magento\\Customer\\Model\\Customer::ENTITY": "customer",
    "Magento\\Customer\\Api\\AddressMetadataInterface::ENTITY_TYPE_ADDRESS": (
        "customer_address"
    ),
}
SETUPS = {"Magento\\Eav\\Setup\\EavSetup", "Magento\\Customer\\Setup\\CustomerSetup"}


@dataclass
class PHPSource:
    path: str
    root: Node
    namespace: str
    imports: dict[str, str]

    def resolve(self, name: str) -> str:
        if name.startswith("\\"):
            return name.lstrip("\\")
        head, _, tail = name.partition("\\")
        if head in self.imports:
            return self.imports[head] + ("\\" + tail if tail else "")
        return (self.namespace + "\\" if self.namespace else "") + name


def _array(node: Node) -> dict[str, Node] | None:
    if node.type != "array_creation_expression":
        return None
    result = {}
    for child in node.named_children:
        if child.type == "comment":
            continue
        parts = child.named_children
        if child.type != "array_element_initializer" or len(parts) != 2:
            return None
        key = literal_text(parts[0])
        if key is None:
            return None
        result[key] = parts[1]
    return result


@dataclass(frozen=True)
class Attribute:
    entity: str
    code: str
    datatype: str | None
    required: bool | None
    unique: bool
    values: tuple[str, ...]
    origin: Span
    value_origin: Span | None

    @property
    def table(self) -> str:
        return ENTITIES[self.entity]


def _sources(ctx: ReadContext, modules: tuple[Module, ...]) -> list[PHPSource]:
    own_modules = [module for module in modules if not module.third_party]
    if not own_modules:
        return []
    paths = {
        f"{module.path}/{path}"
        for module in own_modules
        for path in select_files(ctx.project_root / module.path, ("**/*.php",))
    }
    parser = get_parser("php")
    sources = []
    for path in sorted(paths):
        source = ctx.read(path)
        if source is None:
            continue
        root = parser.parse("\n".join(source.lines).encode()).root_node
        namespace = ""
        imports = {}
        for node in root.named_children:
            if node.type == "namespace_definition":
                namespace = text(node.child_by_field_name("name"))
            elif node.type == "namespace_use_declaration":
                for clause in node.named_children:
                    if clause.type != "namespace_use_clause":
                        continue
                    name = text(clause.named_children[0]).lstrip("\\")
                    alias = (
                        text(clause.child_by_field_name("alias"))
                        or name.split("\\")[-1]
                    )
                    imports[alias] = name
        sources.append(PHPSource(path, root, namespace, imports))
    return sources


def _source_values(
    source: PHPSource, declaration: Node
) -> tuple[tuple[str, ...], Span | None]:
    for method in declaration.named_children:
        if method.type == "declaration_list":
            for member in method.named_children:
                if (
                    member.type != "method_declaration"
                    or text(member.child_by_field_name("name")) != "getAllOptions"
                ):
                    continue
                returns = [n for n in walk(member) if n.type == "return_statement"]
                if len(returns) != 1 or not returns[0].named_children:
                    return (), None
                options = returns[0].named_children[0]
                if options.type != "array_creation_expression":
                    return (), None
                values = []
                for option in options.named_children:
                    if option.type == "comment":
                        continue
                    if len(option.named_children) != 1:
                        return (), None
                    mapping = _array(option.named_children[0])
                    value = mapping.get("value") if mapping else None
                    literal = literal_text(value)
                    if (
                        literal is None
                        and value is not None
                        and value.type in {"integer", "float", "boolean"}
                    ):
                        literal = text(value)
                    if literal is None:
                        return (), None
                    values.append(literal)
                return tuple(values), span(returns[0], source.path, READER)
    return (), None


def _receiver_type(source: PHPSource, node: Node | None, types: dict[str, str]) -> str:
    if node is None:
        return ""
    if node.type == "object_creation_expression" and node.named_children:
        return source.resolve(text(node.named_children[0]))
    if node.type == "parenthesized_expression" and node.named_children:
        return _receiver_type(source, node.named_children[0], types)
    if (
        node.type == "member_call_expression"
        and text(node.child_by_field_name("name")) == "create"
    ):
        factory = _receiver_type(source, node.child_by_field_name("object"), types)
        return factory[:-7] if factory.endswith("Factory") else ""
    return types.get(text(node), "")


def collect_attributes(
    ctx: ReadContext, modules: tuple[Module, ...]
) -> tuple[list[Attribute], list[tuple[str, str | None, Span]]]:
    """Collect own-module declarations; vendor source models are never inspected."""
    if not any(not module.third_party for module in modules):
        return [], []
    sources = _sources(ctx, modules)
    classes = {}
    parents = {}
    for source in sources:
        for node in walk(source.root):
            if node.type != "class_declaration":
                continue
            name = source.resolve(text(node.child_by_field_name("name")))
            classes[(ctx.repository_of(source.path).key, name)] = (source, node)
            base = next(
                (c for c in node.named_children if c.type == "base_clause"), None
            )
            if base and base.named_children:
                parents[(ctx.repository_of(source.path).key, name)] = source.resolve(
                    text(base.named_children[0])
                )

    attributes = []
    unresolved: list[tuple[str, str | None, Span]] = []
    for source in sources:
        if not any(
            source.path.startswith(m.path + "/Setup/Patch/Data/")
            and "/" not in source.path[len(m.path + "/Setup/Patch/Data/") :]
            for m in modules
            if not m.third_party
        ):
            continue
        repo = ctx.repository_of(source.path).key
        types = {}
        # Only PHP type declarations are evidence of a setup/factory receiver.
        for declaration in walk(source.root):
            if declaration.type not in {
                "simple_parameter",
                "property_promotion_parameter",
                "property_declaration",
            }:
                continue
            declared_type = declaration.child_by_field_name("type")
            if declared_type is None or declared_type.type != "named_type":
                continue
            typename = source.resolve(text(declared_type))
            if declaration.type == "property_declaration":
                for member in declaration.named_children:
                    if member.type == "property_element":
                        name = text(member.child_by_field_name("name"))
                        types["$this->" + name.lstrip("$")] = typename
            else:
                name = text(declaration.child_by_field_name("name"))
                types[name] = typename
                if declaration.type == "property_promotion_parameter":
                    types["$this->" + name.lstrip("$")] = typename
        for node in walk(source.root):
            if node.type == "assignment_expression":
                left = text(node.child_by_field_name("left"))
                types[left] = _receiver_type(
                    source, node.child_by_field_name("right"), types
                )
            if (
                node.type != "member_call_expression"
                or text(node.child_by_field_name("name")) != "addAttribute"
            ):
                continue
            receiver = _receiver_type(source, node.child_by_field_name("object"), types)
            seen = set()
            while receiver and receiver not in SETUPS and receiver not in seen:
                seen.add(receiver)
                receiver = parents.get((repo, receiver), "")
            if receiver not in SETUPS:
                continue
            args = arguments(node)
            origin = span(node, source.path, READER)
            if len(args) < 2:
                unresolved.append(("non_literal_argument", None, origin))
                continue
            entity = literal_text(args[0])
            if entity is None and args[0].type == "class_constant_access_expression":
                parts = text(args[0]).split("::", 1)
                entity = CONSTANTS.get(
                    source.resolve(parts[0].strip()) + "::" + parts[1].strip()
                )
            code = literal_text(args[1])
            if entity is None or code is None:
                unresolved.append(("non_literal_argument", None, origin))
                continue
            if entity not in ENTITIES:
                unresolved.append(("model_table_unknown", entity, origin))
                continue
            options = _array(args[2]) if len(args) > 2 else None
            options = options or {}
            values: tuple[str, ...] = ()
            value_origin = None
            model = options.get("source")
            if model is not None:
                raw = text(model)
                model_name = (
                    source.resolve(raw.rsplit("::", 1)[0].strip())
                    if model.type == "class_constant_access_expression"
                    and raw.rsplit("::", 1)[-1].strip().lower() == "class"
                    else literal_text(model)
                )
                own = classes.get((repo, model_name)) if model_name else None
                if own:
                    values, value_origin = _source_values(*own)
            required = options.get("required")
            attributes.append(
                Attribute(
                    entity=entity,
                    code=code,
                    datatype=literal_text(options.get("type")),
                    required=False
                    if required is None
                    else {"true": True, "false": False}.get(text(required).lower()),
                    unique=text(options.get("unique")).lower() == "true",
                    values=values,
                    origin=origin,
                    value_origin=value_origin,
                )
            )
    return attributes, unresolved


def apply_attribute(schema: Schema, attribute: Attribute) -> None:
    a = attribute
    if a.table not in schema.tables:
        schema.create_table(
            Table(name=a.table, columns=(), constraints=(), defined_at=a.origin)
        )
        schema.mark_uncertain(a.table, a.origin, "entity_table_missing")
    column = Column(
        name=a.code,
        datatype=a.datatype,
        mandatory=a.required,
        origin=(a.origin,),
        defined_at=a.origin,
        target=f"eav:{a.entity}.{a.code}",
    )
    if any(c.name == a.code for c in schema.tables[a.table].columns):
        schema.change_column(a.table, a.code, column)
    else:
        schema.add_column(a.table, column)
    if a.unique:
        schema.add_constraint(
            a.table, Constraint(kind="unique", columns=(a.code,), spans=(a.origin,))
        )
    if a.values:
        schema.add_constraint(
            a.table,
            Constraint(
                kind="value",
                columns=(a.code,),
                allowed_values=a.values,
                spans=(a.value_origin or a.origin,),
            ),
        )
