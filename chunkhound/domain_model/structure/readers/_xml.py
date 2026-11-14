"""Small, non-resolving XML view backed by tree-sitter source ranges."""

from dataclasses import dataclass

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.structure.schema import Span


@dataclass(frozen=True)
class Element:
    name: str
    attributes: dict[str, str]
    children: tuple["Element", ...]
    span: Span


def parse_xml(
    text: str, path: str, reader: str, errors: list[Span] | None = None
) -> tuple[Element, ...]:
    data = text.encode("utf-8")
    tree = get_parser("xml").parse(data)

    def value(node: Node) -> str:
        return data[node.start_byte : node.end_byte].decode("utf-8")

    def span(node: Node) -> Span:
        return Span(
            path=path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            reader=reader,
        )

    nodes = []
    stack = [tree.root_node]
    first_error = None
    while stack:
        node = stack.pop()
        nodes.append(node)
        if first_error is None and (node.is_error or node.is_missing):
            first_error = node
        stack.extend(reversed(node.children))
    if tree.root_node.has_error and errors is not None:
        errors.append(span(first_error if first_error is not None else tree.root_node))

    # Bottom-up assembly avoids recursion even for arbitrarily nested XML.
    parsed: dict[int, tuple[Element, ...]] = {}
    for node in reversed(nodes):
        if node.type != "element":
            parsed[node.id] = tuple(
                e for child in node.named_children for e in parsed[child.id]
            )
            continue
        tag = next(
            (c for c in node.named_children if c.type in {"STag", "EmptyElemTag"}),
            None,
        )
        if tag is None:
            parsed[node.id] = ()
            continue
        name = next((value(c) for c in tag.named_children if c.type == "Name"), "")
        attributes = {}
        for attr in tag.named_children:
            if attr.type == "Attribute":
                parts = attr.named_children
                if len(parts) == 2:
                    # Deliberately retain entity references literally: no DTD or IO.
                    attributes[value(parts[0])] = value(parts[1])[1:-1]
        parsed[node.id] = (
            Element(
                name,
                attributes,
                tuple(
                    e
                    for child in node.named_children
                    if child.type == "content"
                    for e in parsed[child.id]
                ),
                span(node),
            ),
        )
    return parsed[tree.root_node.id]
