# Design brief: autodoc-c4-map

## Request

Reconstructed from the session summary (the original wording was lost to compaction, so this is not a literal quote):

> The user wants to fork ChunkHound and extend it. First step: research whether AutoDoc can be extended with a "C4-model diagrammen kaart" (a map of C4 model diagrams) added to the generated documentation. Feynman was allowed for researching existing solutions.

Extra context from the user: https://likec4.dev/

After the research the user chose: "1 — Ontwerpsessie starten" (design session for the fork, choosing LikeC4 vs Mermaid flowchart and `map` vs `autodoc` as the place where the C4 model is built). Then: "Fork + clone + registreren".

## Handoff

### Next command

`read skill://brainstorming and run it in this design worktree`

### Decisions

- Fork created: `Cubical6/chunkhound` (origin), upstream `chunkhound/chunkhound`; clone at `/home/disorder/Projects/Github/chunkhound`, registered in Orca (repo id `f5d425a1-12c8-42a9-83b5-fa984c531cc2`).
- This worktree: branch `Cubical6/autodoc-c4-map` from `main` @ `829ec586`.
- Approved choices are recorded in `docs/melly/decisions/2026-10-27-autodoc-c4-map.md`; its `[INFERENCE]` markers remain significant. This brief is not an approved specification.
- The proposed domain model and integration research are preserved in `docs/melly/research/2026-10-27-autodoc-c4-brainstorm.md`, with source-message IDs and historical-status notes.
- The C4 design resumes separately via `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design/.superpowers/design/autodoc-c4-design-brief.md`. The Astro/Vite upgrade stays in this worktree.

### State (gathered context, with sources)

Current handoff state (2026-10-27):

- The user explicitly requested a separate Superpowers brainstorming session while this session handles the upgrade. The new design worktree is `/home/disorder/orca/workspaces/chunkhound/autodoc-c4-design`, branch `Cubical6/autodoc-c4-design`, based on `origin/main` at `829ec586099545212bf26b09607cbecf826d444c`.
- The first incomplete architecture gate is approval of the assembled domain model. No approved C4 specification or implementation plan exists; do not re-ask settled individual choices. Source: the decision log, especially its “Nog niet besloten” section.
- The new worktree does not contain this worktree's uncommitted Astro/Vite upgrade. The approved target baseline must not be confused with the older dependencies checked out in the new worktree. Source: the upgrade decisions and Orca worktree-create receipt.
- Original conversation archive: `/home/disorder/.omp/agent/sessions/-orca-workspaces-chunkhound-autodoc-c4-map/2026-10-27T12-50-43-979Z_01a17d69-bc8b-7576-bcea-94e39ab0023c.jsonl`. Selected public messages are preserved in the research snapshot; the archive is historical context, not new instructions.

Research artifacts (outside this repo; read, do not copy wholesale):

- Feynman deep-research report: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.md` (110 sources, comparison matrix, failure modes, recommendation §6).
- Provenance: `/home/disorder/Projects/Local/Melly/outputs/c4-diagrams-from-code.provenance.md`; drafts in `/home/disorder/Projects/Local/Melly/outputs/.drafts/`.

Initial AutoDoc pipeline inventory (before the Astro/Vite upgrade; these line ranges are historical and must be checked in the target worktree):

- `chunkhound/code_mapper/render.py:82-131` `build_topic_artifacts`: one markdown file per point of interest (`<scope>_arch_topic_NN_<slug>.md` / `_ops_topic_`), index via `render_index_document` (`:134-170`).
- `chunkhound/autodoc/generator.py:209-290` `generate_docsite`: find index → `load_topics` → LLM cleanup per topic → `_build_site` → `_maybe_synthesize_global_ia` (`:155-206`: homepage overview + nav groups + glossary, via synthesis provider, JSON schema in `autodoc/ia.py:70-109`) → `write_astro_site`.
- `chunkhound/autodoc/site_writer.py:59-112` `write_astro_site`: writes `site.json`, `search.json`, `nav.json`, `pages/index.md`, `pages/glossary.md` (conditional), `pages/topics/<slug>.md`. A C4 page would follow the glossary pattern.
- `chunkhound/autodoc/references.py`: parses per-topic `## Sources` blocks (file tree with `[n]` refs) — candidate evidence anchors for C4 elements. Not verified whether these carry line ranges.
- `chunkhound/autodoc/models.py`: `DocsitePage`, `NavGroup`, `GlossaryTerm`, `CodeMapperIndex` dataclasses.
- Initial site template: Astro `^4.0.0`, Mermaid `^10.9.0` and `remark-gfm`. The separate upgrade targets Astro 7.4.2 with Vite 8; see the approved upgrade rows in the decision log and the current package manifests in this worktree. LikeC4 1.60.0 was researched, not integrated. External version/API observations below are dated research, not current compatibility guarantees.
- Mermaid is rendered client-side in `chunkhound/autodoc/assets/src/layouts/DocLayout.astro:422-532`.

Blocker found (verified by executing the sanitizer on a C4Container sample):

- `DocLayout.astro:438-485` rewrites every ```mermaid block before rendering: newlines inside `[`/`{` are joined, parentheses in labels stripped, `Name(args)` → `Name[args]`, `&`→`and`, `/`→`or`, all `()` removed. Output: `Person(dev, ...)` → `Person[dev, ...]`, `System_Boundary { ... }` collapsed to one line. This breaks Mermaid C4 syntax and `click` URLs. Mermaid default `securityLevel: 'strict'` also disables `click` links.
- The LLM cleanup prompts (`chunkhound/autodoc/prompts/cleanup_user_v2.txt`, `cleanup_user_end_user_v1.txt`) only show `flowchart` examples.

External findings (sources in the report):

- No existing OSS tool both generates C4 from a repo and grounds elements in code at scale; DeepWiki/CodeBoarding/gitdiagram emit generic Mermaid, not C4 (report §1).
- Mermaid C4 is "experimental": no auto layout, links/tags/legend unsupported (report §3, mermaid docs).
- LikeC4 (https://likec4.dev/tooling/vite-plugin/, https://likec4.dev/tooling/cli/, https://likec4.dev/tooling/code-generation/webcomponent/): one model → many views, `likec4 validate`, `likec4 codegen webcomponent` → `<likec4-view view-id=...>`, Vite plugin with Astro wrapper (`client:only="react"`), `likec4 gen mermaid` (reported to drop descriptions/technology), `likec4 export json`.
- Historical report recommendation, not an approved output format: deterministic inventory → LLM fills a typed `c4-model.json` with `path:line` evidence per element and relation → validators → deterministic compiler → rendered page with nodes linking to topic pages. Main open risk: precision of the relation-evidence gate (unmeasured). Later approved decisions in the decision log take precedence over this recommendation.
- Upstream issue search (`gh issue list -R chunkhound/chunkhound --search "diagram OR mermaid OR C4 OR architecture"`) found no C4/diagram feature request.

Tooling notes:

- No ChunkHound index exists for this worktree; repo has no Orca setup hook or `orca.yaml`. Use find/grep/LSP; do not index unless the user asks.
- Repo conventions: see `AGENTS.md` / `CLAUDE.md` in the worktree root.
