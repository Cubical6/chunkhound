# {{TITLE}}

Generated docs site built from AutoDoc output.

## Quick start

Requires Node.js 22.23.4 or newer and npm 9.6.5 or newer.

```bash
npm install
npm run dev
```

For a production build and local inspection:

```bash
npm run build
npm run preview -- --host 127.0.0.1
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
The archive is copied from the installed ChunkHound distribution, not downloaded
as an upstream LikeC4 replacement. Run `npm install` after copying or refreshing
the site so `package-lock.json` resolves its local `file:vendor/likec4/...tgz`
dependency. Keep the vendor license/notice files when redistributing the project.
No external font service or browser-side LLM is needed for the map.

Architecture source links use each source repository's recorded commit and
inclusive line range for recognized `github.com`, `gitlab.com` and
`bitbucket.org` remotes. If the remote, commit or repository/path mapping cannot
produce a safe URL, the source path and range remain readable text instead.
Links never use moving branches, editor URLs or embedded remote credentials.

Use the View selector or native navigation to move between system, container,
component, focus and topic views. Element details show evidence and weighted
topic links; a merged arrow shows each direct/derived relationship separately,
with its own status and sources. Copy “Link to this view” to share the current
view. An unknown view opens system context with a visible notice.

## Refreshing presentation

From the ChunkHound project:

```bash
chunkhound autodoc --assets-only --out-dir path/to/this/site
```

Then run `npm install` and `npm run build` here. This refreshes managed templates
and runtime assets, not topic Markdown, search/navigation data, architecture JSON
or DSL. A changed producer model requires full generation. Back up customizations
to managed templates before refreshing; unrelated files are preserved.
