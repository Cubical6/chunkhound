# Copied from CodeBoarding (MIT, see chunkhound/code_mapper/c4/codeboarding/LICENSE) at 13adc4a0:
# tests/static_analyzer/names/test_inventory.py.
# Changes: imports point at chunkhound.code_mapper.c4.codeboarding.names; the units_from_graph(s) tests were left out.
from chunkhound.code_mapper.c4.codeboarding.names import Trie
from tests.code_mapper.c4.codeboarding.names.conftest import node_of, unit


class TestTrie:
    def test_counts_units_per_subtree(self):
        trie = Trie([unit("p/x/a.py", "A"), unit("p/x/b.py", "B"), unit("p/y/c.py", "C")])
        assert trie.root.count == 3
        assert node_of(trie, ("p", "x")).count == 2
        assert node_of(trie, ("p", "y")).count == 1
        assert trie.node(("p", "z")) is None

    def test_a_unit_at_the_root_is_a_root_unit(self):
        trie = Trie([unit("a.py", "A"), unit("p/b.py", "B")])
        assert [u.unit_id for u in trie.root.units] == ["a.py"]
        assert node_of(trie, ("p",)).count == 1
