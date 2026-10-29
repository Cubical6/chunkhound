# Pinned LikeC4 distribution

This directory is the complete publication boundary for the local
`likec4@1.60.0-chunkhound.1` fork. It modifies LikeC4's native element
and relationship details; it does not add a renderer or public adapter API.
No external fork remote, registry publication, or runtime download is required
to consume the tarball. Normal npm dependencies still require installation.

## Contents and identity

- `manifest.json`: upstream and local fork commit identities, toolchain, build
  commands, and SHA-256 checksums.
- `chunkhound.patch`: all six source/package/lockfile changes against the pinned
  upstream commit; sufficient to reconstruct the fork without its local Git DB.
- `likec4-1.60.0-chunkhound.1.tgz`: the native `packages/likec4` package, not the
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
`packages/likec4/likec4-1.60.0-chunkhound.1.tgz`. The ordinary native build
`pnpm turbo run build --filter=likec4` was also exercised: this checkout's
parallel tasks can race when React reads diagram declaration files while
diagram cleans its output. Serial Turbo scheduling avoids that race without
skipping any native generate, styles, React, SPA, or plugin prerequisite.
The successful build/pack chain above was repeated from a second clean
upstream checkout plus the preserved patch. That independently packed archive
passed the same real-browser contract. Gzip timestamps and embedded build
identities need not be byte-identical; the checksum identifies this shipped
archive, not every possible reconstruction.

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

For a fully local site, use LikeC4's existing `injectFontCss={false}` prop and
locally bundled `@fontsource-variable/ibm-plex-sans` CSS, as the native SPA does.
The React default font injector points to a CDN. The clean consumer proof used
font package 5.3.0 and loaded its CSS/WOFF2 from the site's own assets directory.
Set the Vite plugin's `ai: 'disabled'` for this non-AI consumer so environment
API keys do not activate optional AI integrations during preview.

## Replace or upgrade

Pin the new upstream commit, rebase only these native detail changes, update
the local package version, and refresh the lockfile with the pinned pnpm.
Run scoped oxfmt, upstream oxlint and typecheck, then the full native build and
pack. Exercise an upstream-before/fork-after real consumer with one direct
plus two nested relations, distinct statuses/sources, exact endpoint actions,
weighted topics, Focus navigation, hostile text, and local fonts/styles.
Regenerate the complete patch from upstream to a committed fork source tree;
repeat a clean upstream-plus-patch build and tarball consumer before replacing
all provenance/checksums and the tarball together. Preserve LICENSE/NOTICE.
Never copy only a prebuilt dist tree or depend on the ignored local checkout.
