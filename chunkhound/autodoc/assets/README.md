# {{TITLE}}

Generated docs site built from AutoDoc output.

## Quick start

Requires Node.js 22.23.4 or newer and npm 9.6.5 or newer.

```bash
npm install
npm run dev
```

## Optional architecture map

Place the version-1 `<scope>_c4_model.json` sidecar beside the selected
`<scope>_code_mapper_index.md`. With a usable model, full AutoDoc generation
publishes `/architecture/`, an overview preview and direct topic-to-element
links. Search includes architecture elements; shared URLs retain the selected
view. Missing or invalid sidecars warn and produce an ordinary site without
React or LikeC4 dependencies.

Map sites use the bundled LikeC4 archive in `vendor/likec4/`, with local shipped
fonts and strict DSL validation. Keep the archive with the generated project.
Invalid generated `likec4/*.c4` fails the site build rather than hiding the map.

Architecture source links use each source repository's recorded commit and
inclusive line range for recognized `github.com`, `gitlab.com` and
`bitbucket.org` remotes. If the remote, commit or repository/path mapping cannot
produce a safe URL, the source path and range remain readable text instead.
Links never use moving branches, editor URLs or embedded remote credentials.

## Refreshing presentation

From the ChunkHound project:

```bash
chunkhound autodoc --assets-only --out-dir path/to/this/site
```

Then run `npm install` and `npm run build` here. This refreshes managed templates
and runtime assets, not topic Markdown, search/navigation data, architecture JSON
or DSL. A changed producer model requires full generation. Back up customizations
to managed templates before refreshing; unrelated files are preserved.
