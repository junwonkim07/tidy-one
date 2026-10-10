# SaaS connector and ingestion frameworks for tidy-one (personal cross-device index of "everything I put in the cloud")

Context carried through all sections: tidy-one = Vultr VPS (Seoul, 4 GB RAM, Ubuntu 24.04) holding a SQLite + sqlite-vec catalog and serving MCP tools to Claude Code, Codex, claude.ai web/mobile and Aside; embeddings run on a MacBook M2 24 GB where possible. Sources the user wants: Notion (personal + team, meeting-notes DBs), Slack (company workspace), Google Workspace (the work account, already authenticated via `gws` CLI on the Mac, plus personal Gmail accounts), Plaud (voice recorder; existing Plaud→Whisper→Notion pipeline), maybe GitHub/Vercel/Figma. Research date: 2026-10-10. Star counts, licenses and release dates were pulled from the GitHub REST API on 2026-10-10 unless noted.

## Q1. Frameworks: license, footprint, source coverage, incremental sync, OAuth ownership, MCP, maturity, library/CLI mode

### Takeaway
No "platform" option fits on a 4 GB VPS next to other services: Onyx needs at least 10 GB RAM, Airweave's self-host stack runs about 12 containers, and the Airbyte platform and Nango syncs are out of reach too. Two projects also changed status in 2026. Airweave's open-source repo was archived on 29 Aug 2026, and SurfSense turned into a desktop app for local files, with its cloud service deleted on 18 Oct 2026. What fits a one-person setup is library-mode code. The options are PyAirbyte with declarative connectors, dlt verified sources, LlamaIndex readers, unstructured-ingest, or connector classes lifted from Onyx. The simplest option is thin custom pollers on official CLIs and APIs (`gws`, the `plaud` CLI, a Notion personal access token). Hosted auth brokers (Pipedream Connect, Composio, Nango Cloud, Paragon, Merge) are built for multi-tenant B2B products, and they put a third party in custody of your tokens.

### Cited Findings

#### Snapshot (GitHub API, 2026-10-10)
| Project | Stars | License (verified from LICENSE file) | Latest release | Status |
|---|---|---|---|---|
| airweave-ai/airweave | 6,559 | MIT | v0.9.73, 2026-06-05 | **Archived** (read-only) — [GitHub](https://github.com/airweave-ai/airweave) |
| onyx-dot-app/onyx | 32,377 | MIT for CE; `ee/` dirs under "Onyx Enterprise License" | v4.9.0, 2026-10-07 | Active — [GitHub](https://github.com/onyx-dot-app/onyx) |
| MODSetter/SurfSense | 16,342 | Apache-2.0, except `surfsense_backend/app/proprietary/` under BSL 1.1 | v2.2.0, 2026-10-09 | Active, pivoted to desktop — [GitHub](https://github.com/MODSetter/SurfSense) |
| run-llama/llama_index | 52,451 | MIT | v0.14.25, 2026-09-21 | Active — [GitHub](https://github.com/run-llama/llama_index) |
| Unstructured-IO/unstructured-ingest | 110 | Apache-2.0 | 1.11.23, 2026-10-09 | Active — [GitHub](https://github.com/Unstructured-IO/unstructured-ingest) |
| airbytehq/airbyte | 22,198 | ELv2 (source-available) | v2.0.0, 2025-10-15 | Active — [GitHub](https://github.com/airbytehq/airbyte) |
| airbytehq/PyAirbyte | 342 | ELv2 (LICENSE.md) | v0.71.2, 2026-10-06 | Active — [GitHub](https://github.com/airbytehq/PyAirbyte) |
| dlt-hub/dlt | 5,949 | Apache-2.0 | 1.31.0, 2026-10-07 | Active — [GitHub](https://github.com/dlt-hub/dlt) |
| dlt-hub/verified-sources | 124 | Apache-2.0 | (last push 2026-07-03) | Slower — [GitHub](https://github.com/dlt-hub/verified-sources) |
| PipedreamHQ/pipedream | 11,720 | "Pipedream Source Available License v1.0" (commercial/competing use excluded) | no GitHub releases | Active — [GitHub](https://github.com/PipedreamHQ/pipedream) |
| NangoHQ/nango | 12,583 | ELv2 | v0.71.12, 2026-10-02 | Active — [GitHub](https://github.com/NangoHQ/nango) |
| ComposioHQ/composio | 30,480 | MIT (SDK/CLI only) | @composio/openai 0.13.0, 2026-09-29 | Active — [GitHub](https://github.com/ComposioHQ/composio) |
| useparagon/paragon-mcp | 48 | no license file | (push 2026-09-30) | — [GitHub](https://github.com/useparagon/paragon-mcp) |
| makenotion/notion-mcp-server | 4,662 | MIT | (push 2026-09-20) | — [GitHub](https://github.com/makenotion/notion-mcp-server) |
| (adjacent) khoj-ai/khoj | 37,613 | AGPL-3.0 | (push 2026-08-02) | — [GitHub](https://github.com/khoj-ai/khoj) |
| (adjacent) supermemoryai/supermemory | 31,176 | MIT | (push 2026-10-10) | — [GitHub](https://github.com/supermemoryai/supermemory) |

#### Airweave
- The repo banner reads "This repository was archived by the owner on Aug 29, 2026. It is now read-only", and the page gives no reason and no successor — [GitHub](https://github.com/airweave-ai/airweave). Every other repo in the airweave-ai org is archived too: python-sdk, typescript-sdk, cli, claude-plugin, slack-knowledge-assistant and others — [GitHub org](https://github.com/airweave-ai).
- The YC profile still says "Active" (Spring 2025 batch). Its latest news item is a $6M seed round dated 2025-07-03, and it lists 7 employees. It mentions no shutdown or pivot — [YC](https://www.ycombinator.com/companies/airweave).
- Product pitch: it connects apps, syncs and indexes them, and exposes the result via SDKs, REST and MCP, with 50+ integrations — [README](https://github.com/airweave-ai/airweave).
- Source modules in the final code include notion, slack, gmail, google_drive, google_docs, google_slides, google_calendar, github, fireflies and zoom. There is no Plaud module — [repo `backend/airweave/platform/sources`](https://github.com/airweave-ai/airweave/tree/main/backend/airweave/platform/sources).
- The self-host docker-compose defines postgres 16, redis, backend, frontend, connect, a sentence-transformers inference container, temporal plus temporal-ui and temporal-worker, vespa 8, docling-serve and svix — [docker-compose.yml](https://github.com/airweave-ai/airweave/blob/main/docker/docker-compose.yml).

#### Onyx (formerly Danswer)
- License: CE is MIT, and everything under `ee/` directories falls under the Onyx Enterprise License — [LICENSE](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE).
- Standard deployment needs at least 4 vCPU, 10 GB RAM and 32 GB disk plus about 2.5× the indexed data. Per-container defaults add up to roughly 12 CPU and 24 GB: background 8 Gi, opensearch 4 Gi, each model server 4 Gi, among others — [Onyx resourcing docs](https://docs.onyx.app/deployment/getting_started/resourcing).
- "Onyx Lite" needs under 1 GB memory but "is not capable of indexing documents" — [README](https://github.com/onyx-dot-app/onyx).
- The README advertises an MCP server ("Point Claude Code, Open Code, Codex, or any MCP client at Onyx") that applies the same access controls as the person running it — [README](https://github.com/onyx-dot-app/onyx).
- Connector directory includes notion, slack, gmail, google_drive, google_site, github, gitlab, fireflies, gong, zoom, imap, web and file. There is no Plaud connector — [backend/onyx/connectors](https://github.com/onyx-dot-app/onyx/tree/main/backend/onyx/connectors).
- Connector contract: Load (bulk), Poll (time-range incremental), Slim (IDs only, used for pruning deletions) and Checkpointed connectors. The README shows how to run a connector standalone: instantiate it, call `load_credentials({...})`, then `load_from_state()` or `poll_source(start, end)` with `PYTHONPATH` set to `onyx/backend` — [connectors README](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/README.md).
- Normalized `Document` fields: `id`, `sections` (Text/Image/Tabular, each with `link`), `source`, `semantic_identifier`, `metadata`, `doc_updated_at`, `primary_owners`, `secondary_owners`, `title`, `external_access` (ACL) and `doc_metadata` — [models.py](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/models.py).

#### SurfSense
- The README now presents SurfSense as "a free, open-source desktop app for documents you can't upload", with "no account". The hosted web app is in sunset: "Export your workspaces before 18 October 2026" — [README](https://github.com/MODSetter/SurfSense).
- "The cloud service is export-only, and everything stored in it is deleted on 18 October 2026" — [SurfSense sunset page](https://www.surfsense.com/sunset).
- The backend code still has connector modules: notion_history, slack_history, google_drive, google_gmail_connector, google_calendar, github, composio_connector and others — [surfsense_backend/app/connectors](https://github.com/MODSetter/SurfSense/tree/main/surfsense_backend/app/connectors). The current README does not say whether the desktop app exposes them.

#### LlamaIndex readers (LlamaHub)
- Reader packages exist for notion, slack, github and google. The google package has sub-readers for calendar, chat, docs, drive, gmail, keep, maps and sheets — [llama-index-integrations/readers](https://github.com/run-llama/llama_index/tree/main/llama-index-integrations/readers). The old `run-llama/llama_hub` repo now returns 404 on the GitHub API (checked 2026-10-10).

#### Unstructured (unstructured-ingest)
- The connector modules include notion, slack, google_drive, github, gitlab, onedrive, outlook, confluence and jira, plus vector-DB destinations such as lancedb, qdrant and duckdb. There is no Gmail module — [processes/connectors](https://github.com/Unstructured-IO/unstructured-ingest/tree/main/unstructured_ingest/processes/connectors).
- The Slack connector tells user tokens (`xoxp-`) from bot tokens and has dedicated error paths for user tokens, so it can read as an individual — [slack.py](https://github.com/Unstructured-IO/unstructured-ingest/blob/main/unstructured_ingest/processes/connectors/slack.py).

#### Airbyte / PyAirbyte
- PyAirbyte packages Airbyte connectors as a Python library "removing the need for hosted services". Its default cache is local DuckDB, and incremental state is stored in an `_airbyte_state` table next to the data — [PyAirbyte getting started](https://docs.airbyte.com/using-airbyte/pyairbyte/getting-started); [DuckDB cache ref](https://docs.airbyte.com/developers/pyairbyte/reference/airbyte/caches/airbyte-caches-duckdb).
- Connector metadata, all license ELv2 — [airbyte repo metadata.yaml files](https://github.com/airbytehq/airbyte/tree/master/airbyte-integrations/connectors):
  - source-notion: certified, GA, declarative manifest.
  - source-slack: certified, GA, declarative manifest.
  - source-google-drive: certified, alpha, Python.
  - source-gmail: community, alpha.
  - source-google-calendar: community, alpha.
  - source-github: certified, GA.
- The PyAirbyte repo describes itself as powering "the Airbyte Cloud Replication MCP" — [GitHub](https://github.com/airbytehq/PyAirbyte).

#### dlt (dltHub)
- The verified-sources repo includes notion, slack, github, google_sheets, google_analytics, filesystem, inbox (IMAP), rest_api and unstructured_data. It has no dedicated Gmail-API or Google Drive source — [verified-sources/sources](https://github.com/dlt-hub/verified-sources/tree/master/sources).
- The Notion source's `notion_databases` uses `write_disposition="replace"`, which is a full refresh rather than incremental — [notion/__init__.py](https://github.com/dlt-hub/verified-sources/blob/master/sources/notion/__init__.py).
- The Slack source is incremental on the message `created_at`, and thread replies are opt-in (`replies=False` by default) — [slack/__init__.py](https://github.com/dlt-hub/verified-sources/blob/master/sources/slack/__init__.py).

#### Pipedream Connect
- The license is source-available. Its "Excluded Purpose" covers "any commercial use … including … software-as-a-service … that competes" — [LICENSE](https://github.com/PipedreamHQ/pipedream/blob/master/LICENSE).
- Workday signed a definitive agreement to acquire Pipedream on 2025-11-19, with closing expected by 2026-01-31 — [Workday newsroom](https://en-sg.newsroom.workday.com/2025-11-19-Workday-Signs-Definitive-Agreement-to-Acquire-Pipedream?asPDF=1).
- Pricing comes from a third party and was not verified on pipedream.com: Connect at $99/mo including 100 external users, then $2 per extra user, with self-serve pricing "left intact through June 2026" — [usagepricing.com](https://www.usagepricing.com/blueprint/pipedream), [airframe.ai](https://www.airframe.ai/product/pipedream-com/compare).

#### Nango
- Free self-hosting covers only "API Auth" and "Proxy". It excludes syncs, tool calls, webhooks, triggers, the MCP server, and "Pre-built syncs, tools & triggers" — [Nango self-hosting docs](https://nango.dev/docs/guides/platform/self-hosting.md).
- The recommended enterprise self-host is 5 Node services at "1 CPU, 2GB RAM per service" plus a database — [Nango self-hosting docs](https://nango.dev/docs/guides/platform/self-hosting.md).
- Enterprise self-hosting requires a fixed annual license fee — [Nango docs (search result)](https://docs.nango.dev/guides/self-hosting/enterprise-self-hosting).

#### Composio
- The official pricing page (fetched 2026-10-10) lists three tiers — [composio.dev/pricing](https://composio.dev/pricing):
  - Hobby: free, 100,000 tool calls and 50,000 triggers per month, hard-capped.
  - Pro: $29/mo; overage $0.0003 per tool call and $0.003 per trigger.
  - Enterprise: custom.
  - It states "bring your own" OAuth apps on all tiers, and mentions no self-hosting.
- **Conflicting third-party claims**: Free at 20K calls, a $599 Business tier, and self-managed credentials gated behind $599 — [dailyaifixs](https://dailyaifixs.com/blog/composio-pricing-2026-the-75-tool-call-cut), [scalekit blog](https://www.scalekit.com/blog/composio-pricing-change).
- A third-party write-up says the open-source repo holds only SDKs and CLI, while the credential store and execution backend are proprietary cloud — [bitdoze](https://www.bitdoze.com/executor-sh-vs-composio/).

#### Paragon and Merge
- Paragon's "Managed Sync" offers permission-aware ingestion of Google Drive, Notion, Confluence and more for RAG. It exposes a Sync API, a Permissions API and change webhooks — [Paragon docs](https://docs.useparagon.com/managed-sync/overview); [Paragon blog](https://www.useparagon.com/blog/how-to-build-connectors-for-rag).
- Neither Paragon (Connected-Users model) nor Merge Agent Handler publishes pricing; both are sales-quoted — [cdata](https://www.cdata.com/blog/paragon-alternatives-embedded-integrations); [knit](https://getknit.dev/blog/understanding-merge-dev-pricing-finding-the-right-unified-api-for-your-integration-needs.md).
- Merge lists a Plaud connector page — [merge.dev](https://www.merge.dev/connectors/plaud) (seen in search results, not opened).

### Inferences
- **Fit on a 4 GB VPS:**
  - Only library-style code fits: PyAirbyte with declarative connectors, dlt, LlamaIndex readers, unstructured-ingest without heavy partitioning, or Onyx connector classes copied out of the repo.
  - Onyx standard (10 GB minimum) and the Airweave stack (Vespa + Temporal + Postgres + Redis + docling + inference) do not fit.
  - The Airbyte platform and Nango syncs (enterprise-only for self-hosting) are also out.
  - Running connectors on the Mac (24 GB) relaxes RAM, but Airweave and Onyx still need Docker stacks there. That is overkill when tidy-one already owns storage, embeddings and MCP.
- **Airweave** should be treated as abandoned open source. A fork is possible (MIT), but nobody will maintain its connectors against API changes such as Notion's 2026 versions or Slack's 2025 terms.
- **Onyx's connector code is the best "reference implementation" to borrow.** Its Load/Poll/Slim split maps cleanly onto tidy-one's needs (backfill, incremental, deletion pruning), and its `Document`/`external_access` model is a good schema template. Running it standalone pulls the Onyx backend dependency tree onto `PYTHONPATH`, so copying 1–2 connector files (MIT, outside `ee/`) is more practical than depending on the package. This is an inference: the dependency weight was not measured.
- **PyAirbyte** gives cursor and state management for free. Its connectors are ELv2, which is fine for personal use but not OSI open source. Two cautions:
  - Gmail and Calendar sources are community/alpha quality.
  - Airbyte's Notion/Slack streams aim at tabular ELT and may not yield clean page-body text for RAG. This was not verified per stream.
- **dlt** is a good fit for structured incremental loads, but its Notion source is full-refresh and its Slack cursor is `created_at` only, so edits and late thread replies get missed.
- **The auth brokers (Pipedream Connect, Composio, Nango Cloud, Paragon, Merge)** solve the "many end-users' OAuth" problem, which tidy-one does not have: one user, and the tokens are already on the Mac. They add per-call cost and third-party token custody. Their main value would be an OAuth app for a source where you cannot create your own. That does not apply here: Notion has PATs, Slack allows internal apps, Google has the gws client, and Plaud logs in through its own CLI.
- **Recommended for tidy-one:** write about 5 thin Python/TS pollers on the Mac:
  - Notion via PAT, with search sorted by `last_edited_time`.
  - Google via the `gws` token, with Drive `changes.list` and Gmail `history.list`.
  - Plaud via the `plaud` CLI.
  - Slack via an internal app and user token, or federated search only (see Q3 and Q7).
  - GitHub via the `gh` API.

  Borrow parsing and edge-case handling from Onyx and LlamaIndex code. Optionally use PyAirbyte for one-off backfills.

### Gaps
- Why Airweave was archived: no announcement found. The YC page still says "Active".
- Whether the SurfSense desktop app (v2.x) still exposes the Notion/Slack/Gmail connectors in its UI. The modules exist in code, but the README no longer mentions them.
- Actual RAM footprint of PyAirbyte, unstructured-ingest and LlamaIndex readers per connector: not measured.
- Pipedream's post-Workday pricing and roadmap after June 2026: only third-party sources found.
- Composio's pricing conflicts between the official page and third-party posts; the official page was preferred.
- Supermemory (MIT, 31k stars) and Khoj (AGPL, 37.6k stars) also ship personal-oriented connectors, but they were not researched in depth.

## Q2. Notion API realities (2026)

### Takeaway
Notion **personal access tokens (PATs)** change the picture for a personal index. A PAT acts as the user, sees everything the user can see, and does not need pages shared via "Add connections". The catches are expiry (1-year default) and plan-based admin policy. Rate limits are 180 req/min per connection (600 on Business/Enterprise) plus a shared per-workspace budget. Incremental sync is done by polling search sorted by `last_edited_time`. Webhooks exist, but they only signal a change and need a public HTTPS endpoint. The hosted Notion MCP is built for interactive agents, not bulk sync.

### Cited Findings
- **Three auth modes:**
  - Internal integration: a static token. "The page must be manually shared with the connection", and creating one requires being a workspace owner — [Notion authorization](https://developers.notion.com/docs/authorization).
  - Public integration: OAuth 2.0 with `access_token` + `refresh_token`; refreshing issues a new pair — [Notion authorization](https://developers.notion.com/docs/authorization).
  - PAT: a user-scoped token that uses the creator's membership and page permissions, and "does not need pages to be shared with a bot through 'Add connections'" — [Notion PAT guide](https://developers.notion.com/guides/get-started/personal-access-tokens.md).
- **PAT details:**
  - Expiry options: 7, 30, 90 or 180 days, or 1 year (the default). After expiry the token "immediately stops working" — [PAT guide](https://developers.notion.com/guides/get-started/personal-access-tokens.md). The expiry options were added 2026-07-02 — [Notion changelog](https://developers.notion.com/page/changelog.md).
  - Admins can view and revoke PATs. Default policy on who may create them: Free = owners only; Plus = all members; Business = owners only (configurable); Enterprise = owners plus selected groups.
  - The "List all users" endpoint is unavailable to PATs, and Notion says PATs are not for multi-user products — [PAT guide](https://developers.notion.com/guides/get-started/personal-access-tokens.md).
- **Rate limits:**
  - Per connection: "600 requests per minute" on Business/Enterprise and "180 requests per minute (an average of 3 per second)" on all other plans, plus a separate per-workspace shared limit — [Request limits](https://developers.notion.com/reference/request-limits.md).
  - Over-limit requests get HTTP 429 `rate_limited` with `Retry-After` — [Request limits (search snippet)](https://developers.notion.com/reference/request-limits).
  - Changelog dates: workspace-level limits introduced 2026-06-16; per-connection 60-second-window enforcement on 2026-09-09; Free-workspace block limits enforced on the REST API from 2026-09-01 — [Notion changelog](https://developers.notion.com/page/changelog.md).
- **Size limits:** 1000 blocks and 500 KB per payload, 2000 characters per rich-text item, 100 elements per array — [Request limits](https://developers.notion.com/reference/request-limits.md).
- **Search endpoint:**
  - Returns pages and data_sources "shared with your connection", or for a PAT, accessible to the user.
  - Sort options are `last_edited_time` (asc/desc) or relevance. Filters are object type and `in_trash: true`, which lists deleted items.
  - Notion advises using "Query a data_source" for a specific database.
  - Current version in the examples is `Notion-Version: 2026-03-11`.
  - [POST /v1/search](https://developers.notion.com/reference/post-search.md)
- **Webhooks:** `page.content_updated` is aggregated. Payloads do not contain the content, so the integration must re-fetch — [Notion webhooks ref](https://developers.notion.com/reference/webhooks/page-content-updated); [Hookdeck guide](https://hookdeck.com/webhooks/platforms/guide-to-notion-webhooks-features-and-best-practices). A search summary said integration webhooks are "public beta" and require `Notion-Version: 2026-03-01`. That was not confirmed on an official page, because the docs URL returned 404.
- **Meeting notes:** API version 2026-03-11 renamed the `transcription` block type to `meeting_notes`. Content is reached through `summary_block_id`, `notes_block_id` and `transcript_block_id` children once the status is `notes_ready` — [Upgrade guide 2026-03-11](https://developers.notion.com/guides/get-started/upgrade-guide-2026-03-11) (via search summary); [Make community thread](https://community.make.com/t/get-full-notion-page-content-ai-meeting-notes/111013).
- **Hosted Notion MCP:**
  - Lives at `mcp.notion.com/mcp` with browser OAuth — [getunblocked](https://getunblocked.com/blog/notion-mcp/).
  - Changelog items: MCP access tokens extended from 1 to about 8 hours (2026-07-14); search/query limits raised to 20 per 10 s (2026-09-28); tool-specific rate limits removed (2026-10-06); consolidated into a single `notion-search` tool (2026-10-07) — [Notion changelog](https://developers.notion.com/page/changelog.md).
  - The MCP toolset includes `notion-query-meeting-notes` and `notion-query-data-sources` — [Notion changelog](https://developers.notion.com/page/changelog.md); [jitendrazaa guide](https://www.jitendrazaa.com/blog/ai/notion-mcp-server-complete-guide/).

### Inferences
- **Use a Notion PAT on the Mac**, set to 1-year expiry with a calendar reminder to rotate. Who may create one depends on plan: on a Business workspace such as a company workspace, by default only owners can, while on a Plus workspace any member can. If the company workspace forbids PATs, fall back to an internal integration plus page sharing.
- **Incremental loop:** page through `POST /v1/search` sorted by `last_edited_time` descending until reaching the stored high-water mark, then fetch blocks for the changed pages. Run a periodic `in_trash: true` sweep or ID reconciliation to catch deletions, mirroring Onyx's "Slim" pass.
- **Cost:** block-tree fetching dominates API usage, because each page needs one or more `blocks.children` calls. At 3 req/s, a first backfill of a few thousand pages takes tens of minutes, and incremental runs take seconds. This is a back-of-envelope estimate, not measured.
- **Webhooks** need a public HTTPS receiver, which the VPS could provide. They are only a trigger, though; polling every 15–60 minutes from the Mac is simpler for one person.
- **The Notion MCP is for interactive retrieval, not ingestion:** it has short tokens and per-10-second search limits. The two can coexist: tidy-one gives cross-source search, and Notion MCP handles write-back.

### Gaps
- Official confirmation of webhook beta status and availability for PATs: the official webhooks doc page returned 404. The PAT guide does not mention webhooks.
- Exact per-workspace rate-limit numbers by plan.
- Which plan the user's personal and company Notion workspaces are on, which sets PAT defaults and the 180 vs 600 rpm limit.

## Q3. Slack API realities (2026)

### Takeaway
Rate limits are not the blocker for an internal app built in your own workspace: such apps keep Tier-3 limits and up to about 1,000 objects per page. The May 2025 throttle of 1 request per minute and 15 objects hits commercially distributed non-Marketplace apps. The real issue is the **API Terms**. Since 29 May 2025 they forbid using API data to train LLMs and bulk export of message and file data, and for the Data Access API they forbid "persistent copies, archives, indexes, or long-term data stores". Slack's own path for AI agents is the Slack MCP server and the Real-time Search API, which are query-in-place and not sync. For a personal index of a company workspace, federated search is the low-risk design; copying messages into the VPS is a policy decision for the workspace owner.

### Cited Findings
- **May 2025 rate-limit change:**
  - `conversations.history` and `conversations.replies` drop to 1 request/minute and 15 objects/request for non-Marketplace, commercially distributed ("unlisted") apps. This applied immediately on 2025-05-29 to new apps and new installs.
  - "Internal customer-built apps" keep current limits ("1,000 objects per request at 50+ requests per minute"), as do Marketplace apps.
  - Rationale given: "prevent bulk data exfiltration by unvetted applications".
  - [Slack changelog 2025-05-29](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps)
- **Conflict on existing installs:** a search-engine summary of the same changelog said limits apply to existing installs of unlisted apps on 2026-03-03. The fetched page and the method docs say existing installs "will not be subject" — [changelog](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps); [conversations.history](https://docs.slack.dev/reference/methods/conversations.history). This is irrelevant for an internal app either way.
- **Scopes and access:** bot and user tokens both need `channels:history`, `groups:history`, `im:history` and `mpim:history`. A user token sees "private conversations the user belongs to plus all public channels". Standard tier is Tier 3 (50+ req/min) — [conversations.history](https://docs.slack.dev/reference/methods/conversations.history). Tier definitions: Tier 1 is 1+/min, Tier 2 20+/min, Tier 3 50+/min, Tier 4 100+/min — [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits).
- **API Terms (2025-05-29 version):**
  - "you may not: (A) use API Data to train a large language model; (B) bulk export Slack message and file data except where expressly allowed by an additional agreement"
  - "When using the Data Access API, you may not create persistent copies, archives, indexes, or long-term data stores."
  - The fetch found no explicit carve-out for internal apps.
  - [Slack API ToS archive 2025-05-29](https://slack.com/policy-archives/terms-of-service-api/2025-05-29)
- **Legal commentary:** a law firm summarizes the change as prohibiting "creation of persistent copies, archives, indexes or long-term data stores" and LLM usage, and notes that customers with internal LLMs built on Slack archives must redesign — [Hunton](https://www.hunton.com/privacy-and-cybersecurity-law-blog/salesforce-locks-down-slack-data-time-to-review-your-slack-api-terms).
- **Slack MCP server:**
  - Endpoint `https://mcp.slack.com/mcp` over Streamable HTTP.
  - Only "Directory-published apps or internal apps"; "Unlisted apps are prohibited".
  - User-token OAuth via the confidential flow.
  - Partner clients: Claude.ai, Claude Code, Perplexity, Cursor.
  - Workspace admins approve and manage MCP clients, and activity appears in audit logs.
  - Tool limits run from Tier 2 to Tier 4.
  - [Slack MCP overview](https://docs.slack.dev/ai/slack-mcp-server/). Announced 2026-02-17 — [Slack changelog](https://docs.slack.dev/changelog/2026/02/17/slack-mcp).
- **Real-time Search API (`assistant.search.context`):**
  - Searches messages, files, channels and users.
  - A user token needs no `action_token`; its scopes are `search:read.public/.private/.im/.mpim/.files/.users`.
  - Up to 20 results per request; user-level limit of 10 req/min.
  - Supports `im`/`mpim` channel types.
  - [assistant.search.context](https://docs.slack.dev/reference/methods/assistant.search.context)
  - Slack positions it as letting agents retrieve context "without the need to bulk download the data or store it elsewhere" — [Slack MCP + RTS blog (search result)](https://slack.dev/context-aware-agents-slack-mcp-server-real-time-search/).
- **Official exports:** only Owners and Admins can export. Pro and Business+ exports cover public channels. Private channels and DMs require an application with legal process, member consent or a legal right. Exports contain links to files, not the files — [Slack help: import/export](https://slack.com/help/articles/204897248).
- **App installation:** by default any member can install apps. Owners can turn on app approval, after which members request approval — [Slack help: add apps](https://slack.com/help/articles/202035138-add-an-app-to-your-workspace).

### Inferences
- **Technically,** an internal Slack app in the company workspace with a user token (`xoxp-`) can page `conversations.history` and `conversations.replies` at Tier 3 with `oldest=<last ts>` cursors. That is ample for one person.
- **Contractually,** persistently indexing Slack messages on a personal VPS sits in a grey-to-red zone under the 2025 Terms. RTS-derived indexes are explicitly barred. Bulk export of message data needs an additional agreement. Whether indexing for personal RAG retrieval counts as "use in LLMs" is unclear, and Hunton reads it broadly.
- **Options in order of safety:**
  1. Do not index Slack. At query time, tidy-one's MCP federates to Slack MCP or RTS (claude.ai and Claude Code already have the Slack connector), and tidy-one stores only pointers such as saved-item permalinks.
  2. Index only the user's own messages and explicitly saved items, with written approval from the workspace owner. If the user is the owner, document that decision.
  3. Do a full internal-app sync of channels and DMs only under an explicit company policy.
- Thread replies need separate `conversations.replies` calls, and edits do not move `ts`. A sync that keys only on `oldest` misses edits and late replies, which is the same weakness as dlt's `created_at` cursor.

### Gaps
- Whether the 2025 ToS restrictions (other than the Data Access API clause) apply to an organization's internal custom app used only by its own employee. The ToS text found has no explicit internal-use carve-out, and no Slack FAQ answering this was found.
- The current GA status and plan requirements of the RTS API: GA is mentioned in a Slack Feb-2026 feature-drop blog, which was not opened.
- Whether the company workspace has app approval turned on, and the user's role there (owner or admin?).

## Q4. Google Drive and Gmail realities (plus reusing the `gws` CLI)

### Takeaway
Google has the cleanest incremental primitives of the four sources. Drive offers `changes.getStartPageToken` → `changes.list` → `newStartPageToken`, and Gmail offers `history.list` from a stored `historyId`, with a full resync on 404. Docs export to Markdown, Sheets only export the first sheet to CSV, Slides export to plain text, and every export is capped at 10 MB. The user's `gws` CLI already exposes all of these methods and can print its decrypted credentials, so a Mac-side poller can reuse it. Watch the 7-day refresh-token trap for "Testing"-mode OAuth clients used with personal Gmail accounts.

### Cited Findings
- **Drive changes feed:**
  - Store the token from `changes.getStartPageToken`, page `changes.list` via `nextPageToken`, then store `newStartPageToken`.
  - `includeRemoved` and `restrictToMyDrive` are available.
  - `changes.watch` notifications "don't contain details about the changes", so a poll must follow.
  - [Drive: retrieve changes](https://developers.google.com/workspace/drive/api/guides/manage-changes)
- **Export formats:**
  - Docs: .docx, .pdf, .txt, .html, **.md**, .odt, .rtf, .epub.
  - Sheets: .xlsx, CSV/TSV ("first-sheet only"), pdf, ods, zipped HTML.
  - Slides: .pptx, .pdf, **.txt**, .odp.
  - Google Vids cannot use `files.export`.
  - [Export MIME types](https://developers.google.com/workspace/drive/api/guides/ref-export-formats)
- **Export size:** "the exported content is limited to 10 MB" — [files.export reference](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export).
- **Gmail sync:**
  - Full sync is `messages.list` plus batched `messages.get`, then store the latest `historyId`.
  - Partial sync is `history.list` from `startHistoryId`. History is "typically available for at least one week and often longer".
  - An out-of-range ID returns HTTP 404, and the client must "perform a full sync".
  - Use `format=minimal` for cached messages; push via watch is optional.
  - [Gmail: synchronize clients](https://developers.google.com/workspace/gmail/api/guides/sync)
- **OAuth refresh-token rules:**
  - "A Google Cloud Platform project with an OAuth consent screen configured for an external user type and a publishing status of 'Testing' is issued a refresh token expiring in 7 days."
  - Tokens unused for 6 months expire.
  - The limit is 100 refresh tokens per Google Account per client, after which the oldest is silently invalidated.
  - Admins can block tokens via `admin_policy_enforced`.
  - [Google OAuth 2.0 docs](https://developers.google.com/identity/protocols/oauth2#expiration)
- **`gws` CLI:**
  - [googleworkspace/cli](https://github.com/googleworkspace/cli): Apache-2.0, 31,284 stars, last push 2026-10-06. Described as "dynamically built from Google Discovery Service". The binary prints "This is not an officially supported Google product".
  - On the user's Mac: `gws` 0.22.5 (local check 2026-10-10) exposes `changes getStartPageToken|list|watch`, `users history list` (Gmail), `files export -o`, `--page-all` (NDJSON auto-pagination), and `auth export`, which "Print[s] decrypted credentials to stdout".
  - Credentials live in `~/.config/gws/credentials.enc` with `client_secret.json`. This is a local observation, consistent with the user's CLAUDE.md.

### Inferences
- **Mac-side poller loop:**
  1. `gws drive changes list --params '{"pageToken": <stored>, "includeRemoved": true, "fields": "..."}' --page-all`.
  2. For each changed Google-native file, `gws drive files export` as `text/markdown` (Docs) or `text/plain` (Slides). For Sheets, export xlsx or call the Sheets API per tab, because CSV export only covers the first sheet.
  3. Store `newStartPageToken`.
  4. Gmail: `gws gmail users history list --params '{"userId":"me","startHistoryId":...}'`, falling back to a full `messages.list` on 404.
- **No Python OAuth client needed:** a Python process can call `gws auth export` (or shell out to `gws` per call) to obtain a fresh access token. Do not copy the credentials into the repo or onto the VPS, per the user's existing rule.
- **Personal Gmail accounts:** use a separate OAuth client per account, or the same client with separate tokens. Move its consent screen to "In production", even if unverified for personal use, to avoid 7-day expiry. The company.team client can be "Internal" user type if it lives in the company GCP org. Whether the existing gws client is Internal or External was not checked.
- **Calendar** has an analogous `syncToken` mechanism (`events.list`). It was not researched here, but `gws` exposes it.
- **Large Docs over 10 MB** of export (rare for text) need the Docs API `documents.get` instead.

### Gaps
- Whether the company's Google Workspace admin restricts third-party or unconfigured OAuth apps ("API controls"). The fact that the gws login succeeded suggests it currently works.
- Drive changes token lifetime: Google's guide does not state an expiry for page tokens.
- Gmail restricted-scope verification requirements for a personal-use External app: not re-verified for 2026.

## Q5. Plaud: is there an official API, or only MCP?

### Takeaway
For an individual account the official access paths are the **Plaud MCP** (remote `https://mcp.plaud.ai/mcp` or local stdio) and the **Plaud CLI** (`@plaud-ai/cli`). Plaud says both became generally available for individuals on 12 May 2026. Both use browser OAuth. The "Plaud Developer Platform" REST API is a B2B partner API (client_id/secret → partner token → user token) for embedding Plaud devices and transcription in other products, not for exporting your own library. Neither path offers a change feed or webhooks, so incremental sync means polling by `created_at`.

### Cited Findings
- **Developer Platform:** announced 2025-10-07, with a Device SDK, Transcription API, Meeting Bot, and output as JSON transcripts and summaries — [Plaud blog](https://www.plaud.ai/blogs/news/plaud-developer-platform).
- **Positioning:** the dev portal targets B2B and vertical software, with API keys via portal.plaud.ai — [dev.plaud.ai](https://dev.plaud.ai/).
- **Auth model:** "Get Partner Token: Application-level token. Exchange your `client_id` and `secret_key`…, which is used to mint individual user tokens" — [Plaud docs index](https://docs.plaud.ai/llms.txt).
- **Plaud changelog, 2026-05-12, "v1.0.0":** "Plaud MCP (`@plaud-ai/mcp`) and Plaud CLI (`@plaud-ai/cli`) are now generally available. Individuals can connect their Plaud account…" — [Plaud MCP & CLI changelog](https://docs.plaud.ai/plaud-mcp-cli/changelog.md).
- **MCP:**
  - Local run via `npx -y @plaud-ai/mcp@latest`; HTTP remote for web clients goes through Plaud's US-hosted server, where data is "processed in transit only".
  - OAuth browser login and logout.
  - Tools: `list_files` (query, date_from, date_to, pagination), `get_file` (metadata plus presigned URLs valid 24 h), `get_note`, `get_transcript`, `get_current_user`.
  - [Plaud MCP docs](https://docs.plaud.ai/plaud-mcp-cli/mcp.md)
  - The remote URL is `https://mcp.plaud.ai/mcp` — [Plaud support (search result)](https://support.plaud.ai/hc/en-us/articles/57751078986265-Plaud-MCP).
- **CLI:**
  - Install with `npm install -g @plaud-ai/cli`.
  - Commands: `plaud login`, `plaud files --page N --page-size 10–100`, `plaud recent --days N`, `plaud transcript <id> -o file`, `plaud summary <id> -o file.md`, `plaud audio <id>` (a 24-hour URL).
  - `plaud search` is client-side over the 500 most recent recordings.
  - Tokens are stored at `~/.plaud/tokens.json`. Config `api_base` defaults to `https://platform.plaud.ai/developer/api`. Errors go to stderr, with exit code 2 for auth failure.
  - [Plaud CLI docs](https://docs.plaud.ai/plaud-mcp-cli/cli.md)
- **npm vs changelog versions:** the registry shows `@plaud-ai/cli` 0.3.15 and `@plaud-ai/mcp` 0.3.14, both modified 2026-10-08. That does not match the changelog's "v1.0.0" — [npm registry](https://www.npmjs.com/package/@plaud-ai/cli) (checked via `npm view`, 2026-10-10).
- **Third-party brokers** (Scalekit AgentKit, Merge) wrap the same Plaud MCP via OAuth 2.1/DCR — [Scalekit](https://docs.scalekit.com/agentkit/connectors/plaudmcp/).

### Inferences
- **The Plaud CLI is the right connector:** it runs on the Mac, owns its token file, and outputs plain text or Markdown that is scriptable.
- **Poll design:** run `plaud recent --days 3` (or page `plaud files`) on each run, diff IDs against the catalog, then fetch `transcript` and `summary` for new IDs. Re-fetch recent items for a few days, because Plaud transcripts and summaries finish asynchronously and can be regenerated.
- **Whisper pipeline:** the user's Plaud→Whisper→Notion pipeline already produces Notion pages. To avoid double-indexing, either index the Plaud transcript and summary directly and link the Notion page as `related_url`, or index only one (dedupe by Plaud file ID stored in a Notion property). Audio need not be stored in tidy-one; keep the Plaud ID and fetch a fresh 24-hour URL on demand.

### Gaps
- Plaud API rate limits are undocumented.
- Whether `list_files` exposes `updated_at` or edit markers: the CLI docs list only `created_at` and `start_at`.
- The meaning of the version mismatch (0.3.x on npm vs "v1.0.0" in the changelog).

## Q6. Recommended connector-layer architecture for tidy-one (Mac vs VPS, token storage, common schema)

### Takeaway
Run connectors **on the Mac** under launchd, because user auth (gws, plaud, the Notion PAT, the `gh` login) and the embedding GPU are both there. Each connector should be a small poller that stores its own cursor and emits normalized documents. The Mac chunks and embeds, then pushes upserts and tombstones to the VPS catalog over an authenticated API. The VPS should hold no SaaS credentials and run no sync jobs, only the index and MCP. Store secrets in the macOS Keychain or 1Password CLI rather than in plain files. Model the schema on Onyx's `Document`: id, source, link, title, owners, updated_at, sections, metadata, external_access.

### Cited Findings
- **Cursor primitives per source** (from Q2–Q5):
  - Notion: search sorted by `last_edited_time`, `in_trash` sweep — [Notion search](https://developers.notion.com/reference/post-search.md).
  - Drive: `startPageToken` → `newStartPageToken` — [Drive changes](https://developers.google.com/workspace/drive/api/guides/manage-changes).
  - Gmail: `historyId`, 404 → full sync — [Gmail sync](https://developers.google.com/workspace/gmail/api/guides/sync).
  - Slack: `oldest` ts with Tier-3 internal apps — [conversations.history](https://docs.slack.dev/reference/methods/conversations.history).
  - Plaud: `created_at` polling only — [Plaud CLI](https://docs.plaud.ai/plaud-mcp-cli/cli.md).
- **Onyx's three-pass model:** Load (full backfill), Poll (time-window incremental), Slim (IDs only, used to prune deleted docs) — [Onyx connectors README](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/README.md).
- **Onyx `Document` schema:** `id`, `source`, `semantic_identifier`, `title`, `sections[{text|image|table, link}]`, `metadata`, `doc_updated_at`, `primary_owners`/`secondary_owners`, `external_access`, `doc_metadata` — [Onyx models.py](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/models.py).
- **PyAirbyte state:** kept in an `_airbyte_state` table in the cache DB (DuckDB by default), which shows the "cursor next to data" pattern — [PyAirbyte docs](https://docs.airbyte.com/using-airbyte/pyairbyte/getting-started).
- **Token lifetimes to monitor:**
  - Notion PAT: up to 1 year — [PAT guide](https://developers.notion.com/guides/get-started/personal-access-tokens.md).
  - Google Testing-mode refresh tokens: 7 days; unused tokens: 6 months — [Google OAuth](https://developers.google.com/identity/protocols/oauth2#expiration).
  - Plaud: tokens in `~/.plaud/tokens.json`; auth failure is exit code 2 — [Plaud CLI](https://docs.plaud.ai/plaud-mcp-cli/cli.md).
  - Notion MCP tokens: about 8 hours — [Notion changelog](https://developers.notion.com/page/changelog.md).

### Inferences
- **Why the Mac and not the VPS:**
  1. Auth already lives on the Mac (gws OAuth, Plaud tokens, `gh`), and copying refresh tokens to an internet-facing VPS widens the blast radius.
  2. Embeddings run on the M2 anyway.
  3. On a 4 GB VPS, Python connector stacks compete with the MCP server and sqlite-vec.

  Downside: no sync while the Mac sleeps. That is acceptable for a personal index, since launchd catches up on wake and cursor-based APIs tolerate gaps. The exception is Gmail history beyond about a week, which forces a full resync.
- **Optional VPS-side pieces:** a webhook receiver for Notion, Drive `changes.watch` or Gmail Pub/Sub that only records "dirty" flags for the Mac to process. This adds complexity, and polling is probably sufficient.
- **Proposed tables:**
  - `sources(source_id, kind, account, workspace, enabled)`
  - `cursors(source_id, cursor_kind, value, updated_at)`
  - `documents(doc_id = "<kind>:<account>:<native_id>", source_id, native_id, url, title, author, participants, created_at, updated_at, content_hash, mime, parent_id, container, visibility, acl_json, deleted_at, extra_json)`
  - `chunks(chunk_id, doc_id, ordinal, text, token_count, embedding_model, vec)`

  Use `content_hash` to skip re-embedding unchanged text. Use tombstones (`deleted_at`) from Slim-style ID sweeps. `visibility` should be an enum such as `private`, `shared`, `workspace` or `company-restricted`, so MCP tools can filter what is exposed to claude.ai web or mobile versus the local Claude Code.
- **Chunking per source:**
  - Notion: chunk by heading blocks.
  - Docs: export Markdown and chunk by headings.
  - Sheets: per-tab CSV, row-group chunks.
  - Slides: per slide.
  - Gmail: one doc per thread with quoted text stripped.
  - Plaud: transcript chunks with timestamps plus the summary as its own doc.
  - Slack, if indexed at all: one doc per thread or per channel-day.
- **Secret storage:**
  - Prefer the macOS Keychain (`security find-generic-password`) or 1Password CLI (`op read op://…`) for the Notion PAT and the Slack token.
  - Leave the `gws` and `plaud` token stores where those CLIs manage them.
  - Never sync secrets via `~/claude-memory` or git.
  - The VPS needs only an ingest API key, scoped to write the catalog.

### Gaps
- No benchmark of end-to-end sync volume and time for the user's actual Notion, Drive and Gmail sizes.
- No source evaluated for best practice on sqlite-vec upsert/delete throughput at the expected scale. This is covered, if at all, by other researchers' notes.

## Q7. Privacy and compliance: indexing company Slack and Drive into a personal server

### Takeaway
Policy, not engineering, is the main risk.
- **Slack:** the 2025 API Terms prohibit bulk export of message data without an additional agreement, LLM training on API data, and persistent indexes built from Data Access API results. Official full exports need owner action and legal justification.
- **Notion:** workspace admins can see and revoke PATs, and Business plans limit PAT creation to owners by default.
- **Google Workspace:** admins can block OAuth apps (`admin_policy_enforced`).
- **Plaud:** the remote MCP routes data through US servers.

Company data should be either excluded, federated (queried live, not stored), or indexed only with explicit approval from the workspace owner, and tagged so it is never exposed beyond trusted clients.

### Cited Findings
- **Slack API Terms:** no LLM training on API data; no bulk export of message and file data "except where expressly allowed by an additional agreement"; no persistent copies or indexes from the Data Access API — [Slack API ToS 2025-05-29](https://slack.com/policy-archives/terms-of-service-api/2025-05-29). A law-firm reading treats this as broadly prohibiting archives and indexes — [Hunton](https://www.hunton.com/privacy-and-cybersecurity-law-blog/salesforce-locks-down-slack-data-time-to-review-your-slack-api-terms).
- **Slack exports:** limited to Owners and Admins. DM and private-channel export requires "valid legal process, consent of members, or a requirement or right under applicable laws" — [Slack help](https://slack.com/help/articles/204897248).
- **Slack MCP clients:** admin-approvable and audit-logged — [Slack MCP overview](https://docs.slack.dev/ai/slack-mcp-server/).
- **Notion PATs:** admins can view and revoke them, and plan-based defaults restrict who can create them — [Notion PAT guide](https://developers.notion.com/guides/get-started/personal-access-tokens.md).
- **Google:** refresh tokens can be invalidated by admin-enforced service restrictions (`admin_policy_enforced`) — [Google OAuth](https://developers.google.com/identity/protocols/oauth2#expiration).
- **Plaud HTTP MCP:** recording data passes through Plaud's US-hosted server, "processed in transit only" — [Plaud MCP docs](https://docs.plaud.ai/plaud-mcp-cli/mcp.md).
- **claude.ai-side connectors:** Notion's hosted MCP, Slack MCP and Plaud MCP are first-party, query-in-place connectors that respect the user's live permissions — [Slack MCP](https://docs.slack.dev/ai/slack-mcp-server/); [Plaud MCP](https://docs.plaud.ai/plaud-mcp-cli/mcp.md); [Notion MCP guide](https://getunblocked.com/blog/notion-mcp/).

### Inferences
- **Classify sources:**
  - Personal: personal Gmail, personal Notion, Plaud, personal Drive.
  - Company: company Slack, company Drive and Gmail, team Notion.
- **Company data defaults:**
  - Slack: federate via Slack MCP or RTS. If anything is stored, store only the user's own messages and pointers, after owner sign-off.
  - Drive and Gmail for the company account: index only if company policy allows personal copies on a non-company server. The VPS is personally operated (Vultr Seoul), so that is a data-residency and ownership question for company.
  - Team Notion: a PAT is visible to admins. Disclose it, or use an internal integration approved by an admin.
- **If the user is the founder or owner of the company,** the approval is self-granted. Writing a one-paragraph internal data-handling note still matters: what is copied, where, retention, and deletion on departure. Other employees' messages (DMs, threads) are third-party personal data.
- **Korean PIPA:** this may be relevant for colleagues' and customers' personal data, but it was not researched here.
- **Technical controls:**
  - Encrypt the VPS disk and SQLite backups.
  - Put `visibility`/`acl` columns in the schema and filter in MCP tools.
  - Restrict company-sourced results to authenticated MCP clients.
  - Support purge-by-source (`DELETE … WHERE source_id = …`) for offboarding.
  - Avoid indexing other people's DMs by default.
- **Duplication:** claude.ai already has native Notion, Slack and Google connectors that respect live permissions. tidy-one's added value for company sources may be better delivered as a federated search fan-out than as a stored copy, which keeps tidy-one's stored corpus mostly personal.

### Gaps
- The actual company policies: Slack plan and app approval, Google Workspace API controls, Notion plan and PAT policy, and any written data-handling policy. These cannot be determined from public sources.
- Whether Slack considers personal RAG indexing via an internal app as "use in LLMs" under the Terms. No official FAQ or ruling was found.
- Korean legal requirements (PIPA) for storing colleagues' messages on a personally controlled server were not researched.
