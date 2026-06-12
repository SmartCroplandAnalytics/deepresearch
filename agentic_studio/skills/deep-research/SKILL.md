---
name: deep-research
description: Produce a comprehensive, well-cited, long-form research report on any topic by running a two-stage, file-based workflow (build a structured knowledge base, then write the report section by section), grounded in web search plus any mounted local corpus and databases. Use when the user asks for "deep research", a "research report", "调研报告", "深度研究", a market/industry/competitive/policy analysis or literature review, or any multi-section written deliverable that must be backed by real, cited evidence. Do NOT use for short Q&A, single-link summaries, or coding tasks.
---

# Deep Research (file-based, two-stage)

This skill turns the agent into a deep-research agent. It is adapted from FS-Researcher's two-stage workflow; the only change is the tool layer (this host uses web search/extract tools + the workspace VFS + optional databases, not Jina scripts).

1. **Stage 1 — Knowledge Base Building.** Gather, archive, and distill evidence into a structured `knowledge_base/` tree, tracked by `index.md`. Multiple rounds with a self-check loop.
2. **Stage 2 — Report Writing.** Draft `report.md` **one top-level section per round** from `report_outline.md`, with all citations in a single `# References` block at the end.

The goal is an information-dense, well-structured, fully-cited report. Shortcuts (one-shot reports, shallow searches, fabricated citations) are forbidden — this skill is optimized for completeness and traceability over speed.

## Tools on this host (replaces FS-Researcher's Jina scripts)

| Need | Use |
|---|---|
| Web search | the **web search tool** (`web_search`; provider-configurable, default free Jina): returns top results (url + title + snippet) for a query. |
| Read a full web page | the **web read tool** (`web_read`): fetches the full text/markdown of a URL. |
| Archive / notes / report | the built-in **file tools** (`write_file`, `read_file`, `ls`, `edit`, `grep`, `glob`) — they operate on the workspace VFS. |
| Local corpus (if mounted) | read/grep the corpus paths given in the brief's `source_scope.vfs_includes`. Treat archived local docs like web sources. |
| Structured database (if mounted at `/db/<alias>`) | **double-channel** (see the `db-analysis` discipline): read `/db/<alias>/database.json` + `…/schema.json` for structure, then `run_sql(database, sql)` for JOIN/aggregation. Never `python open('/db/...')` — DB paths are VFS-only. |

**Parallelism:** issue multiple web-search and web-read calls **in the same tool batch**. A "one search at a time" pattern is a quality failure.

## Workspace layout (single source of truth)

The current workspace root is the research workspace. Create all artifacts at root:

```
/
├── index.md              # Stage 1 master index (topic breakdown + Target Hierarchy + TODOs)
├── kb_log.md             # Stage 1 round-by-round log + self-check results
├── knowledge_base/
│   ├── sources/          # Archived full text of every source read (raw evidence)
│   │   └── <slug>.md
│   └── <hierarchy>/      # Evidence notes organized by the Target Hierarchy in index.md
├── report_outline.md     # Stage 2 outline; per-section Status [TODO|IN-PROGRESS|COMPLETE]
├── report.md             # Stage 2 final report
└── report_log.md         # Stage 2 round log + self-check results
```

**Invariants (hard rules):**

- Each file under `knowledge_base/sources/` is the archive of exactly one source (one web page, or one local/DB excerpt). Written by you via `write_file` with a YAML frontmatter (`url`/`path`, `title`, `fetched_at`). Never fabricate.
- Each evidence note under `knowledge_base/<hierarchy>/` cites one or more files under `knowledge_base/sources/` by relative path.
- `report.md` cites **only** files under `knowledge_base/sources/` — never the evidence notes.
- Filenames are self-explaining lowercase hyphen slugs. Forbidden: `notes.md`, `source_1.md`, `misc.md`, `tmp.md`.

## At every round — orient first

1. `ls` the workspace (top level + `knowledge_base/` two levels).
2. If `index.md` / `kb_log.md` / `report_outline.md` / `report.md` exist, **read them in full**.
3. Decide the stage:
   - No `index.md` → Stage 1, round 1.
   - `index.md` exists but `kb_log.md` has no `[ALL COMPLETE]` line → continue Stage 1.
   - `kb_log.md` has `[ALL COMPLETE]` but `report_log.md` does not → Stage 2.
   - `report_log.md` has `[ALL COMPLETE]` → task done; confirm with the user before doing anything else.
4. Append `# Round N` to the relevant log (`kb_log.md` or `report_log.md`); `N` starts at 1.

## Stage 1 — Knowledge Base Building

**Objective:** a broad, structured, self-explanatory knowledge base that alone could answer any reasonable question about the topic. The product is the populated `knowledge_base/`, NOT a narrative answer.

**Round 1:**
1. Create `index.md` with three sections: **Topic Deconstruction & Key Questions** (prefer questions/hypotheses over noun labels; list specific data needed, known debates, gaps), **Target Hierarchy** (an ASCII tree of the planned `knowledge_base/` with a one-sentence purpose per node), **TODOs** (granular `[TODO]` items, each tied to a hierarchy node).
2. **Fan out searches:** ≥4 web-search calls in parallel with complementary queries (synonyms/aliases, sub-questions, authority-biased queries like `官方`/`白皮书`/`annual report`/`filing`, local language + English if regional). If a local corpus or DB is in scope, also survey it (grep/read; `list_databases` + read schema).
3. **Fan out reads:** pick the most promising URLs, issue ≥6 web-read calls in parallel; for each, `write_file` the full text to `knowledge_base/sources/<slug>.md` (frontmatter + body). Add **≥8 distinct archives** by end of round 1. Prefer official/primary, academic, reputable industry/news; avoid empty paywalls and social home pages.
4. **Write evidence notes** under `knowledge_base/<hierarchy>/<descriptive>.md`: distill data, quotes, arguments, methodologies, comparisons — each cited to its `sources/` file. Avoid vague summaries ("this source discusses X") — extract specifics.
5. Append a round summary to `kb_log.md` (new URLs archived, notes created, TODO changes, gaps).
6. **Run the Stage 1 self-check** (below) in `kb_log.md` under `## Self-check for Round 1`. Convert every "No" into concrete `[TODO]`s.

**Round 2+:** read `index.md` + `kb_log.md`; focus on `[TODO]`/`[IN-PROGRESS]` and last round's gaps; refine the Target Hierarchy (add/split nodes, never silently delete — mark `[SUPERSEDED]`); add **≥5 new archives** per round unless the web tool is rate-limited; rerun the self-check.

**Citation format inside evidence notes** (resolves to a `## References` block at the end of the note; tag type + reliability):

```
China's urban disposable income per capita reached 54,188 yuan in 2024, up 4.4% YoY [1].

## References
[1] /knowledge_base/sources/nbs-china-income-2024.md
    - Type: Official Statistics
    - Reliability: High
```

Reliability: **High** = official/primary, standards bodies, peer-reviewed, audited filings; **Medium** = reputable industry/analyst, named-reporter news; **Low** = blogs/forums/social — always cross-validate.

**Stage 1 self-check (every round, answer Yes/No + one-line reason in `kb_log.md`):**
1. Tasks complete — every `[TODO]` in `index.md` now `[COMPLETE]`?
2. Hierarchy match — `knowledge_base/` mirrors the Target Hierarchy?
3. No placeholders — all filenames self-explaining and specific?
4. Full traceability — every evidence note cites its `sources/` file(s)?
5. Exhaustive coverage — any reasonable question the KB can't answer? Missing regional/temporal/stakeholder angles? Claims on only 1–2 weak sources?
6. Information density — open a random note: specific data/quotes/methods, or vague? If vague, fetch again and extract.
7. Archive floor — does `knowledge_base/sources/` hold **≥20 distinct cited archives** (≥25 for broad/multi-aspect topics), and does every sub-topic have **≥3 dedicated sources**?

Only when all seven are a clean "Yes" do you append `[ALL COMPLETE]` to `kb_log.md` and move to Stage 2. A "No" on Q7 is **never** waived for budget. Plan for ≥2 rounds, expect 3.

## Stage 2 — Report Writing

**Objective:** `report.md`, a long-form, **paragraph-first**, fully-cited report. **One top-level `##` section per round** — a hard constraint preventing the single-round-dump failure.

**Round 1 (outline only):** read `index.md`, skim `knowledge_base/`. Create `report_outline.md` with `## 0. Key Takeaways` plus typically 6–12 numbered main-body sections covering every requirement in the brief. Each block: `Key Question`, `Content` (1–3 concrete sentences), `Status: [TODO]`. Create `report_log.md`. **Write no `report.md` content in round 1.**

**Round 2+ (one H2 per round):**
1. Pick the **first** section with status `[TODO]`/`[IN-PROGRESS]`.
2. Read `report_log.md` for prior self-check failures on it; read the relevant KB notes and sources.
3. Draft/revise that single H2 in `report.md` (append; don't rewrite existing sections; use H3 where helpful, avoid H4+). If `report.md` doesn't exist, create it with `# <Report Title>` then the section.
4. Inline citations: `[N]` **immediately after the claim** (two sources → `[1][2]`). Maintain a single `# References` block at the end, entries pointing **only** to `knowledge_base/sources/` files, deduped (one source = one index, in order of first use).
5. Run the section-level self-check; record Q&A in `report_log.md`; set status `[COMPLETE]` (all pass) or `[IN-PROGRESS]` (any fail).
6. **Stop the round.** Do not start another section.

**Final round (report-level audit):** when every section is `[COMPLETE]`, read `report.md` end-to-end, run the report-level self-check, fix small format issues directly; on pass append `[ALL COMPLETE]` to `report_log.md`. On content fail, flip the section to `[IN-PROGRESS]` and loop.

**Citation rules (most common failure — read carefully).** In `report.md`: only `[N]` indices resolving to the single trailing `# References` block, each entry a `knowledge_base/sources/<slug>.md` path. **Forbidden:** inline relative paths / backtick `.md` paths as citations; citing evidence notes (`knowledge_base/<hierarchy>/...`); per-section reference lists; bare URLs or `(Reuters, 2024)` prose citations; dangling `[N]` or orphan entries. Before closing a section, grep the report for `knowledge_base/sources/`, `../sources/`, and backtick `.md` — every hit must be replaced by `[N]`.

**Section-level self-check (any "No" → fix before `[COMPLETE]`):** Key Question answered & Content covered? "So what" for each fact group? Opens with 1–3 prose paragraphs before any table/list? Prose-to-list ratio ≥2:1 by line count (Key Takeaways exempt)? Every table has a one-line caption + ≥1 interpreting paragraph? Jargon defined, acronyms spelled out on first use? **(hard gates)** every concrete claim carries `[N]` right after it; zero inline-path citations; every `[N]` in the single `# References` points to a `sources/` file (not an evidence note); every `[N]` resolves to an archive that actually exists.

## Global principles (both stages)

1. **Parallelism is mandatory** — batch search/read calls.
2. **Archive first, summarize second** — never distill a page you haven't saved to `knowledge_base/sources/`. If a fetch fails, log the URL in `kb_log.md` and move on; never fabricate.
3. **Read before edit** — re-read a file with line numbers immediately before any range edit.
4. **Additive over destructive** — append/split/version; when correcting a note keep the original with `[SUPERSEDED]` + a link.
5. **Match the brief's language** — if the topic is Chinese, write index/notes/outline/report in Chinese; keep filenames as lowercase English slugs; don't mix languages within a section.
6. **Cite or kill** — every number, name, date, quote carries a citation. Uncited prose is only for connective tissue.
7. **Depth over thrift** — do not throttle searches to save tokens. Stop fanning out only on (a) an explicit rate-limit error, or (b) a clean self-check pass on all seven Stage-1 questions. "Probably enough" is not a stop condition.

## Quality bar (hard gates — falling short triggers another round, never a shipped report)

- **Sources:** ≥20 distinct cited archives (25–35 for broad prompts); ≥40% High-reliability; mix official/academic/industry/news.
- **Structure:** typically 8–12 sections + Key Takeaways + References; paragraph-first; prose:list ≥2:1 per section; tables carry captions + interpretation.
- **Reader-friendly:** acronyms spelled out on first use; jargon defined; every number framed by "what it means".
- **Traceability:** every claim has a `[N]` resolving to one trailing `# References` block of `knowledge_base/sources/` files only.
- **Coverage:** every requirement in the brief is addressed (regional/temporal/sub-topic breakdowns the brief calls for must appear).
- **Honesty:** conflicts between sources are surfaced, not flattened; weak sources cross-validated or labeled.

If any check fails, loop another round — do not ship early.
