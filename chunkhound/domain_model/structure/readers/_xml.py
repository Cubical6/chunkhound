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


def parse_xml(text: str, path: str, reader: str) -> tuple[Element, ...]:
    data = text.encode("utf-8")
    tree = get_parser("xml").parse(data)

    def value(node: Node) -> str:
        return data[node.start_byte : node.end_byte].decode("utf-8")

    def elements(node: Node) -> tuple[Element, ...]:
        if node.type != "element":
            return tuple(e for child in node.named_children for e in elements(child))
        tag = next(
            (c for c in node.named_children if c.type in {"STag", "EmptyElemTag"}),
            None,
        )
        if tag is None:
            return ()
        name = next((value(c) for c in tag.named_children if c.type == "Name"), "")
        attributes = {}
        for attr in tag.named_children:
            if attr.type == "Attribute":
                parts = attr.named_children
                if len(parts) == 2:
                    # Deliberately retain entity references literally: no DTD or IO.
                    attributes[value(parts[0])] = value(parts[1])[1:-1]
        return (
            Element(
                name,
                attributes,
                tuple(
                    e
                    for child in node.named_children
                    if child.type == "content"
                    for e in elements(child)
                ),
                Span(
                    path=path,
                    start_line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                    reader=reader,
                ),
            ),
        )

    return elements(tree.root_node)
