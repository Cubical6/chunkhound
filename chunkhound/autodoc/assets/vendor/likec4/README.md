# Pinned LikeC4 distribution

This directory is the complete publication boundary for the local
`likec4@1.60.0-chunkhound.2` fork. It modifies LikeC4's native element
and relationship details and preserves selected neutral boundary and hierarchy
relationships with native compound-frame geometry. It does not add a renderer
or public adapter API.
No external fork remote, registry publication, or runtime download is required
to consume the tarball. Normal npm dependencies still require installation.

## Contents and identity

- `manifest.json`: upstream and local fork commit identities, toolchain, build
  commands, and SHA-256 checksums.
- `chunkhound.patch`: the complete source/package/lockfile patch against the
  pinned upstream commit; reconstructs the fork without its local Git DB.
- `likec4-1.60.0-chunkhound.2.tgz`: the native `packages/likec4` package, not the
  monorepo root. Existing `likec4/react` and `likec4/vite-plugin` exports remain.
- `LICENSE` and `NOTICE`: MIT license and retained attribution, including NVIDIA.

## Reconstruct and pack

Use Node 24.18.1, pnpm 11.28.5 and Bun 1.4.4, as recorded in the manifest.
The lockfile pins the added oxfmt 0.75.0 development tool. With this directory
available at the absolute path assigned to `VENDOR`:

```sh
VENDOR=/absolute/path/to/chunkhound/autodoc/assets/vendor/likec4
git clone https://github.com/likec4/likec4.git likec4-source
git -C likec4-source checkout --detach 0375d146f8de2eb919033bd3b43b3701194f518b
git -C likec4-source apply "$VENDOR/chunkhound.patch"
cd likec4-source
pnpm install --frozen-lockfile
pnpm turbo run build --filter=likec4 --concurrency=1
pnpm turbo run pack --filter=likec4
```

The archive is produced at
`packages/likec4/likec4-1.60.0-chunkhound.2.tgz`. The ordinary native build
`pnpm turbo run build --filter=likec4` was also exercised: this checkout's
parallel tasks can race when React reads diagram declaration files while
diagram cleans its output. Serial Turbo scheduling avoids that race without
skipping any native generate, styles, React, SPA, or plugin prerequisite.

Verified for `chunkhound.2` (the only change from `chunkhound.1` is the
English `sources` detail-panel label, English fixture statuses and the version
bump): the complete patch applies to a fresh checkout of the pinned upstream
commit and reproduces the committed fork tree; a frozen install and the serial
build/pack above succeeded; the language-server hierarchy and relation specs and
the core boundary-relations, clean-connections and multiple-relationships specs
passed; the archive contains the `sources` label in the element and
relationship details and no `bronnen`. In a clean npm consumer the installed
archive validated and built a small model and imported the `likec4`,
`likec4/react` and `likec4/vite-plugin` exports. The browser, hierarchy-geometry
and strict-plugin checks that passed for `chunkhound.1` were not repeated.
Gzip timestamps and embedded build identities need not be byte-identical;
the checksum identifies this shipped archive, not every reconstruction.

## Consume

Install the actual tarball via a `file:` dependency, then use the existing
LikeC4 Vite plugin and its `likec4:react` virtual module. Avoid a second
standalone diagram runtime alongside that virtual module. Pass structured
JSON text in `metadata.chunkhound_detail`, retaining separate
`metadata.chunkhound_id` and native links/readable metadata. The schema is
version 1: element kind/status/sources/topics/focusView/defaultView, or relation
status/sources/source/target. The patch is the authoritative decoder contract.
Focus resolves a metadata view ID using native navigation; relationship
endpoints use the actual underlying native model FQN. Source links accept
credential-free HTTP(S) or root-relative URLs. URLs with a nonempty parsed
username/password, malformed URLs, and null/unsafe URLs render as plain labels
without anchors; valid source and topic URLs retain their original hrefs.

Selected direct container relationships carrying existing `metadata.chunkhound_id`
remain visible beside expanded components. Ancestor/descendant relationships
are admitted only when that individual underlying relation has a nonempty
string `chunkhound_id`; a marked relation never admits an unmarked neighbor.
The corresponding native computed-view predicates and exact relation lookup
retain those same originals. Internal relation context reaches both language
server layout routes and model layout, allowing a bounded post-Graphviz repair
only for marked edges between actual ancestor/descendant nodes. It uses real
laid-out bounds and native marker offsets, label placement and view bounds;
it neither flattens hierarchy nor creates proxy endpoints.
Unmarked and empty-marker hierarchy relationships retain native validation,
and ordinary unmarked models retain upstream redundancy semantics.

The Node/plugin entry points bundle the patched core and all imported core
subpaths into their shared native chunks; leaving the core dependency external
would silently install upstream computation instead. Browser internals and the
copied React artifacts continue sharing their existing external core runtime,
so native model classes are not mixed across browser copies. Package exports,
metadata schema and normal dependency installation are unchanged.

For a fully local site, use LikeC4's existing `injectFontCss={false}` prop and
locally bundled `@fontsource-variable/ibm-plex-sans` CSS, as the native SPA does.
The React default font injector points to a CDN. The clean consumer proof used
font package 5.3.0 and loaded its CSS/WOFF2 from the site's own assets directory.
Set the Vite plugin's `ai: 'disabled'` for this non-AI consumer so environment
API keys do not activate optional AI integrations during preview.

## Verify Python distribution

With Node.js 24 and npm available, run from the ChunkHound checkout:

```bash
uv build --wheel --clear
uv run python scripts/verify_autodoc_wheel_resources.py dist/*.whl
uv build --sdist --out-dir dist
```

The verifier preserves its `wheels...` CLI. It reads packaged resources through
the existing Python resource loader, checks the manifest-named archive, patch
and license SHA-256 values, package name/version, generated CSS and export
targets. A temporary npm consumer then installs the local archive and executes
the `likec4`, `likec4/react` and `likec4/vite-plugin` exports. This explicit
distribution integration check requires npm registry access for dependencies;
it is not part of ordinary network-free AutoDoc unit tests. A missing archive,
checksum mismatch or broken export fails verification, without an upstream
fallback.

Also unpack the sdist outside the checkout, build a wheel there with
`uv build --wheel --out-dir <rebuilt-dist>`, and run the same verifier against
that wheel. Install the original wheel into a fresh venv and generate/build a
site outside the checkout with `PYTHONPATH` unset. Check actual imported module
paths, lockfile local-archive resolution, native details, local fonts/CSS and
browser navigation; file presence alone is not end-to-end evidence. This
distribution check does not replace the native reconstruction/geometry gates.

## Replace or upgrade

Pin the new upstream commit, rebase these native detail, neutral-boundary and
bounded hierarchy changes, update the local package version, and refresh the
pinned pnpm lockfile. Run scoped oxfmt, upstream oxlint and typecheck, then the
full serialized native build and pack. Exercise all six hierarchy directions
from the unchanged eight-relationship fixture through computed and layouted
models and actual native browser clicks, checking real nesting, frame/child
boundaries, arrowheads, labels, exact selected IDs and endpoint-to-Focus actions.
Also retain direct-plus-derived and marked-plus-ordinary aggregation, distinct
statuses/sources, collision identities, hostile text, strict invalid-input
failure, and local fonts/styles. Regenerate the complete patch from upstream to
a committed fork source tree; repeat every archive consumer/browser contract
from a clean upstream-plus-patch rebuild before replacing provenance/checksums
and tarball together. Preserve LICENSE/NOTICE.
Never copy only a prebuilt dist tree or depend on the ignored local checkout.
