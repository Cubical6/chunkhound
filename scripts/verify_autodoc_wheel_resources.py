from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

_REQUIRED_WHEEL_PATHS: tuple[str, ...] = (
    # Prompt templates (filesystem reads via cleanup.py)
    "chunkhound/autodoc/prompts/cleanup_system_v2.txt",
    "chunkhound/autodoc/prompts/cleanup_user_v2.txt",
    "chunkhound/autodoc/prompts/cleanup_user_end_user_v1.txt",
    # Packaged Astro assets (read via importlib.resources)
    "chunkhound/autodoc/assets/__init__.py",
    "chunkhound/autodoc/assets/astro.config.mjs",
    "chunkhound/autodoc/assets/tsconfig.json",
    "chunkhound/autodoc/assets/README.md",
    "chunkhound/autodoc/assets/package.json",
    "chunkhound/autodoc/assets/src/layouts/DocLayout.astro",
    "chunkhound/autodoc/assets/src/styles/global.css",
    "chunkhound/autodoc/assets/src/components/ArchitectureMap.astro",
    "chunkhound/autodoc/assets/src/components/ArchitectureMap.tsx",
    "chunkhound/autodoc/assets/src/components/ArchitectureMiniMap.astro",
    "chunkhound/autodoc/assets/src/components/ArchitectureMiniMap.tsx",
    "chunkhound/autodoc/assets/src/pages/architecture/index.astro",
    "chunkhound/autodoc/assets/vendor/likec4/manifest.json",
    "chunkhound/autodoc/assets/vendor/likec4/README.md",
    "chunkhound/autodoc/assets/vendor/likec4/NOTICE",
    "chunkhound/autodoc/assets/public/favicon.ico",
    "chunkhound/autodoc/assets/public/fonts/SourceSans3VF-Upright.ttf.woff2",
    "chunkhound/autodoc/assets/public/fonts/SourceSans3VF-Italic.ttf.woff2",
    "chunkhound/autodoc/assets/public/fonts/DMSerifDisplay-Regular.ttf",
    "chunkhound/autodoc/assets/public/fonts/DMSerifDisplay-Italic.ttf",
    "chunkhound/autodoc/assets/public/fonts/licenses/SourceSans3-LICENSE.md",
    "chunkhound/autodoc/assets/public/fonts/licenses/DMSerif-OFL.txt",
    "chunkhound/autodoc/assets/public/fonts/licenses/DMSerif-LICENSE.txt",
)


def _verify_wheel_contents(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())
    missing = [p for p in _REQUIRED_WHEEL_PATHS if p not in names]
    if missing:
        missing_rendered = "\n".join(f"- {item}" for item in missing)
        raise RuntimeError(
            "Wheel is missing required AutoDoc resources: "
            f"{wheel_path}\n{missing_rendered}"
        )


def _verify_fork(root: Path) -> None:
    vendor = root / "chunkhound/autodoc/assets/vendor/likec4"
    manifest = json.loads((vendor / "manifest.json").read_text())
    for key in ("artifact", "patch", "license"):
        record = manifest[key]
        name = record["file"]
        if Path(name).name != name:
            raise RuntimeError(f"Invalid {key} resource filename: {name}")
        path = vendor / name
        if not path.is_file():
            raise RuntimeError(f"Missing LikeC4 {key} resource: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != record["sha256"]:
            raise RuntimeError(f"LikeC4 {key} SHA-256 mismatch: {name}: {actual}")

    if not (vendor / "NOTICE").read_text().strip():
        raise RuntimeError("Empty LikeC4 NOTICE resource")

    artifact = manifest["artifact"]
    archive = vendor / artifact["file"]
    _verify_archive(archive, artifact["package"], artifact["version"])
    _verify_installed_exports(root, archive)
    print(f"LikeC4 {artifact['version']}: SHA-256, notices and installed exports OK")


def _verify_archive(archive: Path, name: str, version: str) -> None:
    with tarfile.open(archive, mode="r:gz") as tgz:
        package_file = tgz.extractfile("package/package.json")
        if package_file is None:
            raise RuntimeError("LikeC4 archive has no package.json")
        package = json.load(package_file)
        if (package["name"], package["version"]) != (name, version):
            raise RuntimeError(
                "LikeC4 archive package name/version differs from manifest"
            )
        names = set(tgz.getnames())
        for export in (".", "./react", "./vite-plugin"):
            target = package["exports"][export]
            while isinstance(target, dict):
                target = target.get("import", target.get("default"))
            if (
                not isinstance(target, str)
                or "package/" + target.removeprefix("./") not in names
            ):
                raise RuntimeError(f"Missing executable LikeC4 export: {export}")
        license_file = tgz.extractfile("package/LICENSE")
        if license_file is None or not license_file.read().strip():
            raise RuntimeError("Missing LikeC4 attribution: package/LICENSE")
        if not any(name.endswith(".css") for name in names):
            raise RuntimeError("LikeC4 archive has no generated styles")


def _verify_installed_exports(root: Path, archive: Path) -> None:
    # Explicit distribution integration check, not a networked unit test.
    # Resolve dependencies normally, so broken transitive exports cannot pass
    # merely because their filenames exist in the tarball.
    consumer = root / "fork-consumer"
    consumer.mkdir()
    (consumer / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "type": "module",
                "dependencies": {
                    "likec4": f"file:{archive.as_posix()}",
                    "react": "19.3.0",
                    "react-dom": "19.3.0",
                },
            }
        )
    )
    for command in (
        [shutil.which("npm") or "npm", "install", "--no-audit", "--no-fund"],
        [
            "node",
            "--input-type=module",
            "-e",
            (
                "import { LikeC4 } from 'likec4';"
                "import { LikeC4View } from 'likec4/react';"
                "import { LikeC4VitePlugin } from 'likec4/vite-plugin';"
                "if (typeof LikeC4.fromSource !== 'function' ||"
                "typeof LikeC4View !== 'function' ||"
                "typeof LikeC4VitePlugin !== 'function')"
                "throw Error('LikeC4 executable exports unavailable');"
            ),
        ],
    ):
        result = subprocess.run(
            command,
            cwd=consumer,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"LikeC4 installed export verification failed: {command[0]}\n"
                f"{result.stdout}\n{result.stderr}"
            )


def _verify_runtime_reads(*, wheel_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="chunkhound-wheel-verify-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(wheel_path) as zf:
            zf.extractall(root)
        _verify_fork(root)

        body = "## Overview\\nB"
        code = "\n".join(
            [
                "from chunkhound.autodoc.cleanup import _build_cleanup_prompt",
                "from chunkhound.autodoc.template_loader import load_bytes, load_text",
                "",
                'assert load_text("src/layouts/DocLayout.astro").strip()',
                'assert load_text("src/styles/global.css").strip()',
                'assert load_bytes("public/favicon.ico")',
                'assert load_bytes("public/fonts/SourceSans3VF-Upright.ttf.woff2")',
                'assert load_bytes("public/fonts/SourceSans3VF-Italic.ttf.woff2")',
                'assert load_bytes("public/fonts/DMSerifDisplay-Regular.ttf")',
                (
                    'assert load_text("public/fonts/licenses/SourceSans3-LICENSE.md")'
                    ".strip()"
                ),
                "",
                f"_build_cleanup_prompt(title='T', body='{body}', audience='balanced')",
                f"_build_cleanup_prompt(title='T', body='{body}', audience='end-user')",
            ]
        )

        env = os.environ.copy()
        # Ensure we load from extracted wheel contents, not from the repo working tree.
        env["PYTHONPATH"] = str(root)

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(root),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Wheel runtime resource verification failed.\n"
                f"wheel={wheel_path}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}\n"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify AutoDoc wheel resources, fork integrity and installed Node exports "
            "(requires Node 24, npm and registry access for ordinary dependencies)."
        )
    )
    parser.add_argument(
        "wheels",
        nargs="+",
        type=Path,
        help="Path(s) to .whl file(s) to verify.",
    )
    args = parser.parse_args(argv)

    wheel_paths: list[Path] = []
    for raw in args.wheels:
        if raw.is_file() and raw.suffix == ".whl":
            wheel_paths.append(raw)
            continue
        raise FileNotFoundError(f"Wheel not found: {raw}")

    for wheel_path in wheel_paths:
        _verify_wheel_contents(wheel_path)
        _verify_runtime_reads(wheel_path=wheel_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
