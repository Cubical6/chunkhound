# {{TITLE}}

Generated docs site built from AutoDoc output.

## Quick start

Requires Node.js 22.23.4 or newer and npm 9.6.5 or newer.

```bash
npm install
npm run dev
```

## Optional architecture map

When the selected Code Mapper index has a usable version-1 C4 sidecar, full
AutoDoc generation publishes `/architecture/`, an overview preview and direct
topic-to-element links. Search includes architecture elements; shared URLs retain
the selected view. Missing or invalid sidecars warn and produce an ordinary site
without React or LikeC4 dependencies.

Map sites use the bundled LikeC4 archive in `vendor/likec4/`, with local shipped
fonts and strict DSL validation. Keep the archive with the generated project.
Invalid generated `likec4/*.c4` fails the site build rather than hiding the map.

## Refreshing presentation

From the ChunkHound project:

```bash
chunkhound autodoc --assets-only --out-dir path/to/this/site
```

Then run `npm install` and `npm run build` here. This refreshes managed templates
and runtime assets, not topic Markdown, search/navigation data, architecture JSON
or DSL. A changed producer model requires full generation. Back up customizations
to managed templates before refreshing; unrelated files are preserved.
