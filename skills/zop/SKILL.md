---
name: zop
description: Use when managing a Zotero reference library from the CLI or via an agent — search/read items, list and reorganize collections, batch-move items, bulk-create collections from a plan, export BibTeX/CSL-JSON/RIS, or extract PDF text/outlines. Trigger on any mention of Zotero, citations, bibliographies, or moving items into a collection, even when the word 'zop' is not used. zop prints a parseable JSON envelope; reads use a local Zotero SQLite db (offline), writes need an API key.
---

# zop — high-throughput Zotero CLI

A command-line tool for batch operations on a Zotero library. **Reads hit the local SQLite database (offline, no key); writes go through the Zotero Web API (need a key).**

## Prerequisites

Install, then point it at a library:

```bash
uv tool install zop-cli          # the command is `zop`
```

Config search order: `$ZOP_CONFIG` → platform dir (Windows `%LOCALAPPDATA%\zop\`, macOS `~/Library/Application Support/zop/`, Linux `~/.config/zop/`) → `~/.config/zop/config.toml`. Put it at any of these:

```toml
[zotero]
data_dir = "/path/to/zotero"     # must contain zotero.sqlite (drives reads)
library_id = "12345"             # for writes
api_key = "your-key"             # for writes (omit for read-only use)
```

A write command failing with error code `auth_missing` means the key/library_id is unset.

## Output contract — parse, don't grep

By default `zop` detects whether stdout is a tty: **non-tty (pipes/agents) → compact JSON; tty → human table.** Force one with the global `--json` / `--human` flag. As an agent, rely on JSON.

Every command prints exactly one JSON object to stdout:

```json
{"ok": true, "data": <list|object>, "error": null, "meta": {"count": 3, "latency_ms": 12}}
```

- `ok` — whether the operation succeeded
- `data` — the payload (collections / items / etc.)
- `error` — on failure, `{"code", "message", "hint", "retryable"}`. Codes: `not_found`, `auth_missing`, `conflict`, `api_error`
- Exit codes: `0` success · `1` app error · `2` usage error **or** partial batch failure

Always `json.loads(stdout)` and branch on `ok`. Never string-match the output.

**`export` is special**: in non-tty/JSON mode it returns `{ok, data: {format, content, count}}` where `content` is the raw bibtex/ris string or the csl-json array. In tty mode (or with `--out FILE`) it writes the raw format directly (pipe-friendly: `zop export K > refs.bib`).

## Commands

### Reads (offline, no key needed)

| Goal | Command |
|------|---------|
| Collections as list / tree | `zop collection list [--tree]` |
| Item keys in a collection | `zop collection items <KEY>` |
| Search items (title/abstract/author) | `zop item search "<q>" [--limit N]` |
| Full metadata for one item | `zop item read <KEY>` |
| Library overview | `zop stats` |
| Recently added items | `zop recent [--days N] [--limit N]` |
| Suspected duplicates | `zop duplicates [--by doi\|title]` |
| Tags with usage counts | `zop tag list` |
| Notes on an item | `zop note list <KEY>` |
| Export to BibTeX/CSL-JSON/RIS | `zop export <KEY...> --format bibtex [--out FILE]` |
| PDF full text | `zop pdf read <KEY> [--max-chars N]` |
| PDF outline (bookmarks) | `zop pdf outline <KEY>` |
| One PDF section (1-indexed) | `zop pdf section <KEY> <N>` |

### Writes (need key)

| Goal | Command |
|------|---------|
| Create collection (+ parent) | `zop collection create "Name" [--parent "ParentKeyOrName"]` |
| Delete collection (cascades) | `zop collection delete <KEY> [-y]` |
| Move collection under new parent | `zop collection reparent <KEY> [--parent "KeyOrName"]` |
| Move items into a collection | `zop collection move <K1> <K2> --to <KEY>` |
| Update item metadata | `zop item update <KEY> [--title ...] [--set K=V]` |
| Add items by DOI | `zop item add --doi 10.x/y [--doi ...] [--from-file dois.txt]` |
| Delete items | `zop item delete <KEY...> [-y]` |
| Add tags (comma-separated) | `zop tag add <KEY...> --tags t1,t2` |
| Remove tags | `zop tag remove <KEY...> --tags t1,t2` |
| Add a note | `zop note add <KEY> --text "..." [--file note.md]` |

Parent references accept a KEY or a NAME in write commands (`--parent "KeyOrName"`); a NAME is resolved locally first, then via the Web API if not yet synced. Accept either from the user.

### Batch reorg (zop's highlight)

Author a plan JSON, **dry-run to validate**, then execute:

```bash
zop collection plan plan.json --dry-run      # checks name conflicts, parent resolution, item existence
zop collection plan plan.json --execute      # creates collections (topo order), then moves items into them
```

Plan shape:

```json
{"collections": [{"name": "Topic", "parent": "ExistingOrPlannedName", "items": ["KEY1", "KEY2"]}]}
```

Always inspect the dry-run `unresolved_parents` / `conflicts` before `--execute`. Intra-plan parents (a new collection whose parent is another new collection) are supported and created in topological order.

On `--execute`, the envelope reports `assignments_done` (`[item_key, coll_key]` pairs actually moved) and `assignments_failed` (`[item_key, error]`). Items move via the API, so they land in the new collections even before Zotero syncs them locally.

For every flag of any command, run `zop <command> --help` rather than guessing.

## Working as an agent

- **Gather state with reads first** — they are offline and fast; resolve names/keys before any write.
- **For multi-step reorgs, author a plan and `--dry-run`** — let zop validate conflicts; don't reimplement the checks.
- **Batch writes isolate failures**: `collection move`, `tag add/remove`, and `item delete` return per-item success/failure in one envelope and don't abort the batch. Report which keys failed from the `failed` array; exit code `2` means partial failure.
- **Versions matter for writes**: if a write fails with `conflict`, the item changed server-side — re-read and retry rather than looping blindly.
- **Reads lag writes briefly**: writes hit the Web API, reads use the local SQLite snapshot. A just-created collection/item isn't visible to read commands until Zotero syncs it (seconds to minutes). To chain creates, pass the returned KEY (e.g. `--parent <KEY>`) rather than the new NAME — or rely on the NAME→API fallback.
- **stats vs recent count differently**: `stats` is a full overview — it counts annotations/highlights in `total_items` and `by_type`. `recent`/`search`/`duplicates` list only bibliographic items (annotations have no title, so they'd be empty noise in a list). Don't expect the two counts to match.
