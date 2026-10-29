"""Static evidence is complete, binding-based, and safe on damaged source."""

from pathlib import Path

import pytest

from chunkhound.code_mapper.c4.files import list_scope_files
from chunkhound.code_mapper.c4.references import scan_references
from chunkhound.core.config.config import Config
from chunkhound.core.config.indexing_config import IndexingConfig


@pytest.mark.asyncio
async def test_static_reference_rules(fixture_repo: Path) -> None:
    sources = {
        "rules.py": (
            "from shop.payments import PaymentGateway as Gateway\n"
            "from shop.storage import Storage\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from shop.storage import OrderRecord\n"
            "class Checkout(Gateway):\n"
            "    record: OrderRecord\n"
            "Gateway()\n"
            "unknown()\n"
        ),
        "public.py": "from shop.storage import Storage\n__all__ = ['Storage']\n",
        "unused.py": "from shop.storage import Storage\n",
        "client.php": (
            "<?php\nuse Vendor\\Client\\Gateway as Remote;\n"
            "require('./admin/src/Base.php');\n"
            "class Client extends Remote {}\nnew Remote();\n"
        ),
        "worker.go": 'package main\nimport "local"\nfunc main() { local.Run() }\n',
        "local/local.go": "package local\nfunc Run() {}\n",
    }
    for name, content in sources.items():
        path = fixture_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    files = [
        "rules.py",
        "public.py",
        "unused.py",
        "client.php",
        "worker.go",
        "shop/__init__.py",
        "shop/payments.py",
        "web/src/index.ts",
    ]
    scan = await scan_references(project_root=fixture_repo, files=files)
    rows = [(r.from_file, r.line, r.to, r.kind, r.status) for r in scan.references]
    assert ("rules.py", 1, "shop/payments.py", "import", "counts") in rows
    assert ("rules.py", 2, "shop/storage.py", "import", "unused") in rows
    assert ("rules.py", 5, "shop/storage.py", "import", "type_only") in rows
    assert ("rules.py", 6, "shop/payments.py", "inherit", "counts") in rows
    assert ("rules.py", 8, "shop/payments.py", "call", "counts") in rows
    assert ("public.py", 1, "shop/storage.py", "import", "counts") in rows
    assert ("unused.py", 1, "shop/storage.py", "import", "unused") in rows
    assert ("shop/__init__.py", 3, "shop/orders.py", "import", "counts") in rows
    assert ("shop/payments.py", 3, "package:requests", "import", "counts") in rows
    assert ("shop/payments.py", 8, "package:requests", "call", "counts") in rows
    assert ("web/src/index.ts", 1, "web/src/api.ts", "import", "counts") in rows
    assert ("web/src/index.ts", 2, "web/src/api.ts", "import", "type_only") in rows
    assert ("web/src/index.ts", 6, "web/src/api.ts", "call", "counts") in rows
    assert ("client.php", 2, "package:Vendor\\Client", "import", "counts") in rows
    assert ("client.php", 4, "package:Vendor\\Client", "inherit", "counts") in rows
    assert ("client.php", 5, "package:Vendor\\Client", "call", "counts") in rows
    assert ("worker.go", 2, "local/local.go", "import", "counts") in rows
    assert len(scan.references) == 17
    assert scan.imports_only_files == frozenset({"worker.go"})
    assert scan.external_sites == {
        "requests": [("shop/payments.py", 3)],
        "Vendor\\Client": [("client.php", 2)],
    }


@pytest.mark.asyncio
async def test_unparsable_file_does_not_abort(fixture_repo: Path) -> None:
    (fixture_repo / "bytes.py").write_bytes(b"\xff\xfe\n")
    (fixture_repo / "broken.py").write_text(
        "from shop.storage import Storage\nclass Broken(\nStorage()\n",
        encoding="utf-8",
    )
    scan = await scan_references(
        project_root=fixture_repo,
        files=["bytes.py", "broken.py", "shop/__init__.py"],
    )
    assert [(r.from_file, r.line, r.kind) for r in scan.references] == [
        ("broken.py", 1, "import"),
        ("shop/__init__.py", 3, "import"),
    ]
    assert scan.imports_only_files == frozenset({"broken.py"})


@pytest.mark.asyncio
async def test_repeated_imports_are_not_truncated(fixture_repo: Path) -> None:
    (fixture_repo / "many.py").write_text(
        "from shop.storage import Storage\n" * 1101, encoding="utf-8"
    )
    scan = await scan_references(project_root=fixture_repo, files=["many.py"])
    assert [r.line for r in scan.references] == list(range(1, 1102))


def test_scope_files_respect_indexing_without_a_ceiling(fixture_repo: Path) -> None:
    scope = fixture_repo / "uncapped"
    scope.mkdir()
    for index in range(1101):
        (scope / f"source_{index}.py").touch()
    (scope / "excluded.py").touch()
    (scope / "ignored.py").touch()
    (scope / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    config = Config.model_construct(indexing=IndexingConfig(exclude=["excluded.py"]))
    files = list_scope_files(scope_path=scope, project_root=fixture_repo, config=config)
    assert set(files) == {f"uncapped/source_{index}.py" for index in range(1101)}


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["js", "jsx", "ts", "tsx"])
async def test_aliases_keep_their_own_targets(fixture_repo: Path, suffix: str) -> None:
    (fixture_repo / "aliases.py").write_text(
        "import shop.payments as payment, shop.storage as storage\n"
        "payment.load_gateway()\n"
        "storage.Storage()\n"
        "unbound.load_gateway()\n",
        encoding="utf-8",
    )
    script = f"aliases.{suffix}"
    (fixture_repo / script).write_text(
        "import {Base as Parent} from '@vendor/client/models';\n"
        "import * as api from './web/src/api';\n"
        "class Child extends Parent {}\n"
        "api.fetchOrders();\n"
        'const marker = "😀"; api.fetchOrders();\n'
        "unknown.fetchOrders();\n"
        "unknown().Parent();\n",
        encoding="utf-8",
    )
    scan = await scan_references(
        project_root=fixture_repo, files=["aliases.py", script]
    )
    assert [
        (r.from_file, r.line, r.to, r.kind, r.status) for r in scan.references
    ] == sorted(
        [
            ("aliases.py", 1, "shop/payments.py", "import", "counts"),
            ("aliases.py", 1, "shop/storage.py", "import", "counts"),
            ("aliases.py", 2, "shop/payments.py", "call", "counts"),
            ("aliases.py", 3, "shop/storage.py", "call", "counts"),
            (script, 1, "package:@vendor/client", "import", "counts"),
            (script, 2, "web/src/api.ts", "import", "counts"),
            (script, 3, "package:@vendor/client", "inherit", "counts"),
            (script, 4, "web/src/api.ts", "call", "counts"),
            (script, 5, "web/src/api.ts", "call", "counts"),
        ]
    )
