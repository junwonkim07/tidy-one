# Architecture patterns for indexing one person's files across their own devices (centralized vs P2P vs federated)

User context carried through: Korean solo developer; MacBook (Apple Silicon), iPhone, Windows laptop; private GitHub repo of markdown "memory" files synced to each device; Basic Memory (MCP, FastEmbed multilingual MiniLM, sqlite-vec) on the Mac and on a Vultr Seoul VPS (1 vCPU / 2 GB RAM, Ubuntu 24.04) behind mcp-auth-proxy (password OAuth, auto TLS) for claude.ai web/mobile. Target clients: Claude Code, OpenAI Codex, Aside browser agent, claude.ai web + mobile. Research date: 2026-10-10.

## Q1a. Centralized family (per-device agents push content + embeddings to one server): data flow, offline behavior, 2 GB VPS fit, conflicts, latency, privacy

### Takeaway
This is the most common pattern in shipped "personal AI search" products (Khoj, Open WebUI + oikb, Immich, Basic Memory Cloud): each device pushes full file content to a server, which parses, embeds and indexes it. It handles devices being offline well, because the server already holds a copy. The costs are a full copy of private data on the server, heavy server RAM (most of these stacks need 4–8 GB, more than the user's 2 GB VPS), and "last writer wins" conflict handling.

### Cited Findings
**Khoj (AGPL-3.0, ~37.6k stars, last push 2026-08-02)**
- Data flow: the Khoj Desktop app "automatically syncs your local files and folders" to Khoj. For self-hosting you set the "Khoj URL" field to your own server (default `http://127.0.0.1:42110`). — [Khoj docs: Desktop](https://docs.khoj.dev/clients/desktop); [Mintlify mirror](https://www.mintlify.com/khoj-ai/khoj/clients/desktop)
- Implementation (read from source): the desktop app runs a cron job `'0 */10 * * * *'` (every 10 minutes). It compares each file's `mtime` with a stored `lastSync` list and pushes only changed files, sending the **full file content** as multipart to `PUT/PATCH {hostURL}/api/content?client=desktop`. A file that disappeared locally is sent as an empty blob, which tells the server to delete it. There is no content hash and no OS file watcher; it polls mtime. — [khoj/src/interface/desktop/main.js](https://github.com/khoj-ai/khoj/blob/HEAD/src/interface/desktop/main.js) (read via GitHub API)
- The Content API indexes Markdown, Org, plain text, PDF, DOCX, images and most code formats. Text is extracted and embedded on the server. — [Khoj Content API (Mintlify)](https://www.mintlify.com/khoj-ai/khoj/api/update); [Khoj data sources](https://www.mintlify.com/khoj-ai/khoj/data-sources/files)
- RAM: Khoj "runs comfortably in about 4 GB with cloud LLM APIs". VPS guidance is 4 GB minimum and 8 GB recommended. The default of 6 Gunicorn workers can exceed memory, and guides suggest lowering it to 2–3. — [RamNode Khoj guide](https://ramnode.com/guides/khoj); [StackHarbor Khoj deploy](https://stackharbor.com/en/knowledge-base/khoj-self-host-deploy/) (third-party hosting guides, not official)
- "Khoj Cloud ... was sunset in 2026; self-hosting is now the only supported way." — [Mintlify Khoj mirror (search snippet)](https://www.mintlify.com/khoj-ai/khoj/clients/desktop). Not confirmed on an official Khoj page; treat as unverified.
- Reported problems:
  - No per-file sync status or index coverage report (Obsidian plugin). — [issue #1363, 2026-07-01](https://github.com/khoj-ai/khoj/issues/1363)
  - Markdown indexing never finishes on a long note that has a heading marker with no title. — [issue #1437, 2026-09-26](https://github.com/khoj-ai/khoj/issues/1437)
  - "Unable to index local files". — [issue #1105, 2025-02](https://github.com/khoj-ai/khoj/issues/1105)
  - "Documents take a long time to start indexing from desktop app". — [issue #730, 2024-04, older than 2025](https://github.com/khoj-ai/khoj/issues/730)

**Open WebUI + oikb (MIT, repo created 2026-05-20)**
- oikb keeps Open WebUI Knowledge Bases in sync from "a local directory, a GitHub repo, a Confluence space, an S3 bucket, Zotero, or any of 46 supported sources".
- "Only new and modified files are uploaded via incremental SHA-256 diffing". It has an `oikb watch <dir>` command for auto-sync on change and requires Open WebUI 0.9.6+.
- Source: [open-webui/oikb README](https://github.com/open-webui/oikb) (read via GitHub API); [Open WebUI docs: Knowledge Base Sync](https://docs.openwebui.com/ecosystem/knowledge-base-sync)

**Immich (photo pattern: phone/desktop upload to server)**
- Server needs at least 6 GB RAM (8 GB recommended) and 2 cores (4 recommended). "For systems with only 4GB of RAM, Immich can be run with machine learning features disabled." — [Immich requirements](https://docs.immich.app/install/requirements)
- iOS background upload is not under the app's control: "the operating system determines if a particular app can invoke background tasks based on multiple factors, most of which the Immich app has no control over". It needs Background App Refresh, and Low Power Mode blocks it. — [Immich automatic backup](https://docs.immich.app/features/automatic-backup)

**Basic Memory Cloud (centralized variant of the user's existing tool)**
- Uses rclone bisync between local folders and the cloud. After the files sync, "the cloud server indexes new/changed files into SQLite database".
- `bm sync --watch` re-syncs every 60 s. Conflicts are resolved with `conflict_resolve=newer` (most recent file wins), with a `max_delete=25` safety limit.
- Source: [Basic Memory cloud sync docs](https://docs.basicmemory.com/cloud/cloud-sync); [Mintlify mirror](https://www.mintlify.com/basicmachines-co/basic-memory/cloud/sync)
- The cloud version uses Postgres + S3, and the same engine is AGPL-3.0. Price is about $15/mo. — [dev.co listing](https://dev.co/ai/mcp/basic-memory) (aggregator; price unverified on an official page)

**Paperless-ngx consume folder**
- The docs page returned HTTP 403 and could not be read. See Gaps.

### Inferences
- **Offline behavior:** best of the three families. A sleeping laptop or an iPhone doesn't matter for search or fetch, because the server already has the content. Freshness is bounded by the push cadence (Khoj 10 min, Basic Memory Cloud 60 s, oikb on watch) and by whether the device was awake to push. iOS cannot be a reliable pusher (see Immich).
- **2 GB VPS fit:**
  - Khoj (~4 GB), Immich (≥6 GB) and MetaMCP-style Postgres stacks do not fit alongside Basic Memory.
  - A centralized design on this VPS only works if it stays SQLite-based (Basic Memory / sqlite-vec) and avoids embedding large volumes on the 1 vCPU. For example, compute embeddings on the Mac and push the vectors, or embed only summaries.
- **Conflicts:** server-side "newer wins" (Basic Memory Cloud) or "last push wins" (Khoj). This is acceptable for a read-mostly index but risky for two-way edited notes.
- **Privacy:** a full plaintext copy of every indexed file sits on a VPS. That is the largest exposure of the three families.
- **Latency:** fastest at query time. The search runs in a single SQLite process in Seoul, and fetching a file needs no extra hop.

### Gaps
- Paperless-ngx consume-folder behavior (inotify vs `PAPERLESS_CONSUMER_POLLING`) could not be verified: the docs page returned HTTP 403.
- AnythingLLM's server-side sync mechanism was not checked.
- No measured latency numbers were found for any of these stacks.
- No official Khoj page confirming the 2026 Khoj Cloud sunset was found.

## Q1b. P2P / sync-then-index-locally family (Syncthing, iCloud Drive, OneDrive, git; every device runs its own index)

### Takeaway
The user already runs this family for markdown: a git repo synced to each device, with a Basic Memory index per device. It gives the best privacy and needs no always-on hub. But every device holds a full copy and runs its own embedder, conflicts surface as files, the iPhone is a weak peer, and cloud-drive placeholders can fool or overload indexers.

### Cited Findings
**Syncthing**
- Change detection: "By regular full scans and by notifications received from the filesystem ('watcher'). By default the watcher is enabled and full scans are done once per hour."
- The watcher "accumulates changes for 10s", and deletions are delayed an extra minute.
- A file is rehashed when its mtime, size or permissions change. Blocks are 128 KiB–16 MiB, each hashed with SHA-256.
- Conflicts: one copy is renamed to `<filename>.sync-conflict-<date>-<time>-<modifiedBy>.<ext>`, and the copy with the older mtime becomes the conflict file.
- Source: [Syncthing docs: Understanding Synchronization](https://docs.syncthing.net/users/syncing.html)

**Syncthing on iPhone**
- Möbius Sync is paid, proprietary, "hasn't been updated in a year" and runs an older engine.
- Sushitrain/Synctrain is "free, and open source" and has been on the App Store since January 2025. It offers selective sync and on-demand file access.
- Source: [Manual do Usuário: BasicSync and Synctrain](https://manualdousuario.net/en/basicsync-android-synctrain-ios-syncthing-apps/)

**Basic Memory (the user's current per-device index)**
- AGPL-3.0, actively developed (last push 2026-10-09).
- Supports syncing notes "using optional cloud or manual sync with Git and Syncthing". — [dev.co listing](https://dev.co/ai/mcp/basic-memory)
- Semantic search runs on SQLite (built-in sqlite-vec) or Postgres. The default FastEmbed model is `bge-small-en-v1.5` at 384 dimensions, with an embedding batch size of 2. — [basic-memory docs/semantic-search.md](https://github.com/basicmachines-co/basic-memory/blob/main/docs/semantic-search.md)
- Local file watching is implemented in `index/watch_service.py` and `index/local_watch.py`, using the `watchfiles` dependency. — [basic-memory repo](https://github.com/basicmachines-co/basic-memory) (code search)

**Basic Memory multilingual benchmark (2026-08-30, Apple Silicon, FastEmbed 0.8.0, SQLite backend)** — [basic-memory docs/multilingual-embedding-benchmark.md](https://github.com/basicmachines-co/basic-memory/blob/main/docs/multilingual-embedding-benchmark.md)
- Quality, multilingual MiniLM vs BGE-small:
  - overall MRR@10 0.868 vs 0.768
  - cross-language recall@5 1.0 vs 0.857
  - negative-query false positives 0.0 vs 0.75
- Weaknesses of multilingual MiniLM:
  - The 0.55 similarity cutoff dropped some Japanese same-language and mixed-language queries.
  - Long-note "chunk boundary" recall@5 was 0.0.
- Cost of multilingual MiniLM on SQLite: model RSS grew by about 671 MB and the model cache was about 252 MB. BGE-small grew by about 221 MB.
- FastEmbed 0.8.0 switched multilingual MiniLM to mean pooling, so the model/version pair must be pinned.

**Smart Connections (Obsidian)**
- Its index lives in `.smart-env/` and syncs with Obsidian Sync, but with iCloud or Git you regenerate it on each device. — [PromptQuorum: local LLM with Obsidian 2026](https://www.promptquorum.com/power-local-llm/local-llm-with-obsidian-2026) (secondary)

**Cloud-drive placeholders**
- With OneDrive Files On-Demand, the Windows Search indexer (`SearchProtocolHost.exe`) has been reported to trigger downloads of cloud-only files. — [Microsoft Tech Community thread](https://techcommunity.microsoft.com/discussions/onedriveforbusiness/onedrive-files-on-demand-onedrivewindows11-automatically-downloads-vhdx-files-fr/4151433)

### Inferences
- **Offline behavior:** each device searches its own copy, so search works fully offline. A lid-closed laptop simply catches up later via Syncthing or `git pull`.
- **The iPhone is the problem peer:**
  - It cannot run Basic Memory or a persistent indexer.
  - With git, it needs an app such as Working Copy.
  - With Syncthing, it needs Sushitrain, and only while the app is foregrounded or allowed to run in the background (iOS-controlled).
  - So the iPhone should be a client, served via claude.ai mobile → VPS, not an index peer.
- **Conflicts:**
  - git gives explicit merge conflicts, which is good for markdown memory files and works well with AI-written notes when each device commits small changes.
  - Syncthing produces `.sync-conflict-*` files, which an indexer must exclude or flag.
  - Never sync SQLite index files (Basic Memory DB, `.smart-env/`) over Syncthing or git. Rebuild them per device; the Smart Connections docs give the same advice.
- **RAM:** every device pays the embedder cost (about 0.7 GB RSS for multilingual MiniLM). That is fine on the Mac and probably fine on the Windows laptop, and it is already known to run on the 2 GB VPS (the user's current setup). The VPS has little headroom for anything else.
- **Scope limit:** this family scales poorly to "all my files" (PDFs, downloads, project folders on Windows). Replicating everything to every device is wasteful, so P2P fits the curated markdown repo, not the whole disk.
- **Privacy:** best of the three, provided the git remote is private GitHub; GitHub itself is a third-party copy.

### Gaps
- No primary Apple source was found on how iCloud Drive "Optimize Mac Storage" (dataless files) interacts with third-party indexers. A search snippet claimed Spotlight does not hydrate dataless files, but its source URL was unclear, so the claim is excluded.
- Resilio Sync was not researched.
- No measured numbers were found on how often git conflicts occur with AI-written memory files.

## Q1c. Federated / metadata-only hub family (originals stay on devices; hub keeps a catalog and fetches content on demand over a private mesh)

### Takeaway
No mature, turnkey open-source project does "per-device MCP + central catalog + on-demand fetch" for personal files as of October 2026. The pieces exist:
- MCP aggregators: MetaMCP, mcp-proxy "named servers", Docker MCP Gateway, Tailscale Aperture.
- Mesh file access: Tailscale/Taildrive.
- The closest full product: Spacedrive v2 (VDFS with an MCP server), which is only reaching beta on 2026-11-01.

The pattern minimizes data on the VPS, but a sleeping device means its files cannot be fetched (unless the catalog keeps snippets or summaries), and it adds the most moving parts.

### Cited Findings
**Spacedrive v2**
- A "virtual distributed filesystem": files "stay where they are", and Spacedrive "creates a content-aware index that makes them searchable ... from anywhere". — [v2.spacedrive.com](https://v2.spacedrive.com/)
- Sync uses "Domain-Separated Library Sync ... without the complexity of distributed consensus algorithms like CRDTs". — [whitepaper page](https://v2.spacedrive.com/overview/whitepaper)
- Transport: peers connect over "Iroh and QUIC with end-to-end encryption. Devices connect directly when they can and fall back to relays when they must."
- Remote access: "range reads" power mounts, previews and playback "without copying the whole file first".
- Change detection and identity: watchers keep "names, sizes, timestamps, and content state current". BLAKE3 provides content identities, and sampled hashes find duplicate candidates.
- Agent access: exposed through "CLI, generated SDKs, skills, and MCP server".
- License: Apache-2.0 (AGPL-3.0 before 2026-03-24).
- Status: "v2 Beta launches November 1, 2026". Nightly builds exist for macOS ARM64 and Linux x86-64 only, and "can break or change schemas without migrations".
- Source for the items above: [spacedriveapp/spacedrive README](https://github.com/spacedriveapp/spacedrive)
- Earlier, v2.0.0-alpha.1 (Dec 26, 2025) shipped for macOS and Linux, with Windows planned for alpha.2. — [v2.spacedrive.com (search summary)](https://v2.spacedrive.com/)

**Tailscale Aperture (proprietary SaaS gateway; open-source status not stated)**
- "Aperture can aggregate tools and resources from multiple remote ... MCP servers and expose them to AI agents through a single `/v1/mcp` endpoint."
- Access is deny-by-default and governed by Tailscale identity and grants; clients need Tailscale authentication.
- Source: [Tailscale docs: MCP server proxying](https://tailscale.com/docs/aperture/mcp-server) (validated Aug 14, 2026)
- Reached GA on Aug 26, 2026, with "some initial tokens included". — [Aperture GA blog](https://tailscale.com/blog/aperture-ga)

**MetaMCP (MIT)**
- Namespaces group multiple MCP servers into one endpoint. Tools are prefixed `{ServerName}__{tool}`, and admin login supports OIDC. — [MetaMCP docs: namespaces](https://docs.metamcp.com/en/concepts/namespaces)
- Deployment and auth: Docker Compose with Postgres; upstreams over SSE, Streamable HTTP or OpenAPI; endpoint auth by API key or MCP OAuth (2025-06-18 spec).
- Reported issues:
  - Pool saturation near 100 connections makes `tools/list` return an empty array.
  - SSE is unstable behind Nginx.
  - Memory grows when servers are replicated across namespaces.
  - The maintainer said v1 "was released too early" before a 2.0 rewrite.
- Source for deployment, auth and issues: [mcp.directory MetaMCP guide 2026](https://mcp.directory/blog/metamcp-complete-guide-2026) (third-party)

**Docker MCP Gateway (MIT)**
- A Docker CLI plugin that "acts as a centralized proxy between MCP clients and servers". It starts each server in an isolated container with restricted privileges and injects credentials. — [Docker blog](https://www.docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/); [Docker docs](https://docs.docker.com/ai/mcp-gateway/)

**mcp-proxy (sparfenyuk; MIT, ~2.8k stars)**
- Bridges stdio and SSE/Streamable HTTP in both directions.
- "Named servers" host several MCP servers behind one proxy at `/servers/<name>/...`.
- Source: [GitHub](https://github.com/sparfenyuk/mcp-proxy)

**mcp-auth-proxy (sigbit; MIT; the user's current proxy)**
- An "OAuth 2.1 authentication proxy for MCP servers" supporting Google, GitHub, any OIDC provider, or an optional password.
- Converts stdio servers to `/mcp`, and provides auto TLS via `--tls-accept-tos`.
- Positioned for "one or a few MCPs" rather than a gateway.
- Source: [GitHub](https://github.com/sigbit/mcp-auth-proxy)

**jaxxstorm/tailscale-mcp-proxy**
- Proxies a stdio client to an HTTP MCP server over the tailnet, forwarding `X-Tailscale-User`, `X-Tailscale-Node` and `X-Tailscale-Tags` headers.
- One-to-one (no aggregation), with license unspecified.
- Source: [GitHub](https://github.com/jaxxstorm/tailscale-mcp-proxy)

**Taildrive**
- A WebDAV server at `100.100.100.100:8080` that shares directories from Linux, macOS, Windows and Synology.
- iOS and Android can access shares but not host them.
- Status is "Currently in alpha". It is gated by the `drive:share` / `drive:access` node attributes plus `tailscale.com/cap/drive` grants.
- Source: [Tailscale KB: Taildrive](https://tailscale.com/kb/1369/taildrive) (validated Jan 5, 2026)

**Everything (voidtools)**
- A precedent for metadata-only indexing: it builds a filename index from the NTFS MFT and keeps it current from the USN change journal, without indexing content, so it "uses very little memory". — [Wikipedia: Everything](https://en.wikipedia.org/wiki/Everything_(software)); [voidtools forum](https://voidtools.com/forum/viewtopic.php?p=486) (older material)

### Inferences
- **Data flow for this user:**
  1. Each device runs a small agent that watches files and pushes catalog rows to the VPS: device, path, size, mtime, BLAKE3/SHA-256 hash, MIME type, an optional short excerpt or LLM summary, and an optional embedding computed on the device.
  2. Each laptop also exposes a read-only per-device MCP or HTTP endpoint on its tailnet IP only, e.g. `fetch(path, range)` and `list(dir)`.
  3. The VPS hosts the catalog (SQLite FTS5 + sqlite-vec, the same stack as Basic Memory) plus an aggregator MCP. That MCP answers `search` from the catalog and proxies `fetch` to the owning device over Tailscale.
- **Offline or sleeping device:** search still works from the catalog, but `fetch` fails. The aggregator should return "device X offline, last seen T" plus any cached excerpt or summary.
  - Mitigations: keep the Mac awake on power (`caffeinate`/pmset); cache recently-fetched files on the VPS with a TTL; or selectively "pin" important folders to the VPS, which is a centralized fallback for a subset.
  - The iPhone can never be a content source here; its files must reach the Mac via iCloud Drive, Sushitrain or Working Copy first.
- **RAM on the 2 GB VPS:**
  - A metadata catalog is tiny. 100k files × ~1 KB of metadata is about 100 MB on disk, and 384-dim float32 vectors add ~1.5 KB each (~150 MB for 100k). This is arithmetic, not a benchmark.
  - Embedding on the VPS adds about 0.7 GB RSS for multilingual MiniLM (Basic Memory benchmark), so vectors should preferably be computed on the Mac and Windows devices.
  - Avoid MetaMCP (needs Postgres) on this VPS. A ~200-line custom aggregator, or mcp-proxy named servers behind mcp-auth-proxy, is lighter.
- **Conflicts:** none at the content level, because originals are never copied. The catalog is keyed by (device, path) with last-writer-wins per key, and duplicates across devices are detected by content hash.
- **Latency:** search costs the same as centralized. Fetch adds one tailnet hop from the Seoul VPS to the device: direct WireGuard when NAT traversal succeeds, otherwise through a DERP relay. This is inference; nothing was measured.
- **Privacy:** the VPS stores only metadata, excerpts and embeddings. Embeddings can still leak semantic content, so treat them as sensitive.
- **Prompt injection and exfiltration:** an aggregator that can read any file on any device is a powerful exfiltration tool. Use path allowlists, read-only tools and per-device ACLs.

### Gaps
- No 2025–2026 open-source project was found that ships exactly "per-device file-index MCP + central federated search MCP" for personal devices. The search turned up Tailscale-management MCPs, single-server proxies and gateways, but no federated personal-file indexer besides Spacedrive v2 (pre-beta). Spacedrive's iOS and Windows status for v2 beta, and whether its MCP server is reachable remotely or only locally, could not be confirmed.
- Docker MCP Gateway's support for remote (non-container) upstream servers and its footprint on headless Linux without Docker Desktop were not verified.
- No pricing details for Tailscale Aperture beyond "initial tokens included" were found.

## Q2. Networking and security: Tailscale / Headscale / Cloudflare Tunnel / WireGuard, claude.ai remote MCP auth, and whether claude.ai can reach tailnet-only endpoints

### Takeaway
claude.ai (web, desktop and mobile alike) connects to custom connectors from Anthropic's cloud. It therefore cannot reach tailnet or private endpoints. Its connector validation reportedly rejects private, CGNAT, loopback and link-local addresses, which covers Tailscale's 100.64.0.0/10 range.

The public face must be an internet-reachable HTTPS MCP with MCP-spec OAuth: the user's VPS behind mcp-auth-proxy already is one. Tailscale Funnel or a Cloudflare Tunnel would be alternatives. Device endpoints can stay tailnet-only behind it.

Claude Code and Codex run locally, so they can reach tailnet endpoints directly.

### Cited Findings
**claude.ai custom connectors**
- Connection origin and reachability, quoted from the article:
  - "Claude connects to your remote MCP server from Anthropic's cloud infrastructure, rather than from your local device."
  - "Your MCP server must be reachable over the public internet from Anthropic's IP ranges. Servers hosted on a private corporate network, behind a VPN, or blocked by a firewall won't connect."
- Mobile works because the connection originates from Anthropic's servers.
- OAuth client options: Claude's published identity (CIMD-style), automatic registration (DCR), or a custom OAuth client ID/secret.
- Source for the above: [Claude Help Center: Getting started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp)
- "Claude supports the 3/26 auth spec and (as of July) the 6/18 auth spec". — [Claude Help Center article 11503834 (search snippet; page returned 404 when fetched)](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers). Possibly a 2025 statement; may be outdated.

**Anthropic egress IPs (for allowlisting the VPS firewall)**
- Outbound IPv4 for MCP tool calls is `160.79.104.0/21`. The `34.162.x.x/32` addresses are listed as "Phased out". — [Anthropic docs: IP addresses](https://platform.claude.com/docs/en/api/ip-addresses)
- Conflict: one aggregator search snippet stated the reverse (34.162.x current, 160.79.104.0/21 retired). The official page fetched on 2026-10-10 wins.

**What claude.ai's connector validation rejects** — [Zuplo: works in Claude Code but not claude.ai](https://zuplo.com/learn/mcp/errors/mcp-server-works-in-claude-code-but-not-claude-ai) (third-party, verified 2026-07-29)
- claude.ai "reject[s] private, carrier-grade NAT, loopback, and link-local addresses".
- "Connectors are IPv4-only".
- Split-horizon or VPN-internal DNS fails.
- The `.well-known/oauth-protected-resource` and `.well-known/oauth-authorization-server` documents must be reachable from Anthropic's egress range.

**MCP authorization spec 2025-11-25** — [MCP spec: Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- OAuth 2.1 is required.
- Servers MUST publish OAuth Protected Resource Metadata (RFC 9728), discoverable via `WWW-Authenticate` or a well-known URI.
- Authorization servers MUST expose RFC 8414 or OIDC discovery.
- Client ID Metadata Documents are SHOULD; Dynamic Client Registration is MAY ("for backwards compatibility"). Client priority is: pre-registered → CIMD → DCR → manual entry.
- PKCE with S256 is MUST; clients refuse to proceed if `code_challenge_methods_supported` is absent.
- RFC 8707 `resource` is MUST, and servers MUST validate token audience and MUST NOT pass tokens through.
- Refresh tokens MUST rotate for public clients.

**OpenAI Codex**
- MCP servers are configured in `~/.codex/config.toml` (or a project-level `.codex/config.toml`) as `[mcp_servers.<name>]`. A `command` key means stdio; a `url` key means Streamable HTTP.
- Auth is a bearer token or OAuth via `codex mcp login <name>`.
- Source: [OpenAI Codex MCP docs](https://developers.openai.com/codex/mcp.md); [third-party Codex MCP guide, 2026-05](https://codex.danielvaughan.com/2026/05/19/codex-cli-mcp-server-management-cli-commands-oauth-streamable-http-production-patterns/)

**Tailscale Funnel** — [Tailscale KB: Funnel](https://tailscale.com/kb/1223/funnel) (validated Jan 20, 2026)
- Exposes a tailnet service to the internet on ports 443, 8443 and 10000 only, and only under `*.ts.net` names.
- Relay servers "do not decrypt the traffic"; the local Tailscale node terminates TLS.
- Has "non-configurable bandwidth limits".
- Requires v1.38.3+, MagicDNS, HTTPS certificates and a `funnel` node attribute.

**Headscale**
- Funnel (#1040) and Serve (#1234) are listed as not-yet-implemented. — [Headscale features page (mirror, v0.24.2 docs)](https://git.laurivan.com/Mirrors/juanfont.headscale/raw/branch/gh-pages/0.24.2/about/features/index.html); [issue #1040](https://github.com/juanfont/headscale/issues/1040). The docs version may be older than current; re-check.

**Tailscale free Personal plan**
- From April 8, 2026: up to 6 users, unlimited user-owned devices, 50 tagged resources (previously 3 users / 100 devices). — [CostBench](https://costbench.com/software/business-vpn/tailscale/free-plan); [IT Support Group newsletter](https://thisisanitsupportgroup.beehiiv.com/p/tailscale-s-free-tier-just-doubled-if-you-ve-been-putting-it-off-today-s-the-morning) (secondary; confirm on tailscale.com/pricing)

**Cloudflare**
- "Self-hosted applications in Cloudflare Access now support OAuth for MCP server authentication", and MCP server portals "provide a single MCP endpoint for multiple MCP servers". — [Cloudflare changelog, Aug 26, 2025](https://developers.cloudflare.com/changelog/2025-08-26-access-mcp-oauth)
- Access forwards the `Cf-Access-Jwt-Assertion` header. Managed OAuth should only be enabled for servers that validate the Access JWT. — [Cloudflare: Secure MCP servers (updated Aug 25, 2026)](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/secure-mcp-servers/index.md)

### Inferences
- **Topology for this user:**
  - claude.ai web/mobile → public VPS (`https://mcp.<domain>`, mcp-auth-proxy OAuth, firewall optionally restricted to 160.79.104.0/21 + the user's own IPs) → tailnet → Mac/Windows device endpoints, which are bound to their tailnet IP and never public.
  - Claude Code and Codex on the Mac or Windows can use either the public VPS endpoint (OAuth) or, for lower latency and no OAuth, the tailnet `https://<vps>.<tailnet>.ts.net` via Tailscale Serve. Tailscale identity headers can authenticate them.
- **Tailnet IPs and claude.ai:** Tailscale node IPs come from the 100.64.0.0/10 CGNAT block, which matches Zuplo's description of what claude.ai rejects. So "just give claude.ai the tailnet IP" will not work; this is consistent with Anthropic's "behind a VPN ... won't connect".
- **Funnel vs the VPS:** Funnel is unnecessary for the VPS, which already has a public IPv4 and auto TLS. It is an option only to expose the Mac directly, with bandwidth limits, an always-on requirement, and a larger attack surface; not recommended.
- **Headscale:** it has no Funnel/Serve and adds an always-on control server (it could run on the same VPS, consuming RAM). With a free Tailscale plan covering 1 user and unlimited devices, Headscale only makes sense for full self-sovereignty.
- **Cloudflare Tunnel + Access:** a viable alternative front door (no open inbound ports on the VPS). But mcp-auth-proxy already meets the claude.ai OAuth requirements, so switching adds complexity for little gain.
- **ACL design:**
  - Tag the VPS `tag:hub`.
  - Allow only `tag:hub` → `tag:device:<port>` for device MCPs.
  - Deny device ↔ device unless needed.
  - Keep device MCPs read-only, with path allowlists.
- **Audience binding:** the MCP spec forbids token passthrough, so the hub must not forward claude.ai's OAuth token to devices. Use tailnet identity or a separate hub→device credential.

### Gaps
- No Anthropic primary source was found that explicitly says "CGNAT / 100.64.0.0/10 addresses are rejected"; that claim comes from Zuplo (third-party).
- No source states whether claude.ai connectors currently support CIMD vs DCR exactly as the 2025-11-25 spec prefers. The Help Center lists "Claude's published identity", "automatic registration" and "custom OAuth client", which suggests all three.
- The Aside browser agent's MCP/connector capabilities were not researched; no source found.
- No measured Seoul-VPS ↔ Korean home/mobile tailnet latency (direct vs DERP) was found.

## Q3. Change detection for incremental indexing per OS (FSEvents, USN journal / ReadDirectoryChangesW, inotify, watchman, git diffs) and content hashing/dedup

### Takeaway
Use OS journals that survive downtime where possible: FSEvents event IDs on macOS and the NTFS USN journal on Windows let an agent resume "since last run" after sleep or reboot. Live watchers (ReadDirectoryChangesW, inotify, watchfiles/watchman) miss events while the agent is down. Every production syncer pairs a watcher with a periodic full rescan, which is a sound pattern to copy. Content hashing (SHA-256 / BLAKE3) gives dedup and rename detection.

### Cited Findings
**macOS: FSEvents**
- FSEvents stores events in "a persistent, per-volume database".
- Event IDs "are guaranteed to always be increasing ... even across system reboots".
- An app stores the latest event ID plus the device UUID (`FSEventsCopyUUIDForDevice`) and resumes via the `sinceWhen` parameter of `FSEventStreamCreateRelativeToDevice()`.
- Source: [Apple FSEvents Programming Guide](https://developer.apple.com/library/mac/documentation/Darwin/Conceptual/FSEvents_ProgGuide/UsingtheFSEventsFramework/UsingtheFSEventsFramework.html) (archived guide, pre-2025 but the API is still current)

**Windows: USN change journal vs ReadDirectoryChangesW**
- NTFS keeps a USN change journal per volume: "When any change is made to a file or directory in a volume, the USN change journal ... is updated."
- ReadDirectoryChangesW "requires that an application be running at all times".
- Change journals let indexing recover "without ... reindexing the entire volume".
- Source: [Microsoft Learn: Change Journals](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals) (page dated 2018, updated 2025-03-12)
- Everything uses the USN journal rather than ReadDirectoryChangesW. Its folder (non-NTFS) indexing uses ReadDirectoryChanges, "which can miss changes". — [voidtools forum](https://voidtools.com/forum/viewtopic.php?p=486); [Wikipedia: Everything](https://en.wikipedia.org/wiki/Everything_(software))

**Watchman (cross-platform)** — [Watchman install docs](https://facebook.github.io/watchman/docs/install)
- Uses FSEvents on macOS and inotify on Linux; supports Windows 10 64-bit and later.
- Linux needs tuning of `max_user_instances`, `max_user_watches` and `max_queued_events`.
- On inotify overflow it recrawls the tree.

**Syncthing (watcher + safety rescan)**
- Watcher plus a full rescan every hour, randomized to 3/4–5/4 of the interval.
- Rehashes only when mtime, size or permissions change; blocks are SHA-256 hashed.
- Source: [Syncthing docs](https://docs.syncthing.net/users/syncing.html)

**Shipped examples**
- Khoj desktop polls mtime every 10 minutes, with no hashing. — [khoj main.js](https://github.com/khoj-ai/khoj/blob/HEAD/src/interface/desktop/main.js)
- oikb uses SHA-256 diffing against the server, plus `watch` via watchdog with debounce. — [oikb](https://github.com/open-webui/oikb); [Open WebUI docs](https://docs.openwebui.com/ecosystem/knowledge-base-sync)
- Basic Memory uses `watchfiles` (Rust `notify`-based) watch services. — [basic-memory repo](https://github.com/basicmachines-co/basic-memory)
- Spacedrive v2 uses watchers, BLAKE3 content identity, and sampled hashes for fast duplicate candidates, with full-byte verification before destructive actions. — [Spacedrive README](https://github.com/spacedriveapp/spacedrive)

**iOS**
- No persistent background watcher is possible. The OS decides when background tasks run (Immich's experience). — [Immich docs](https://docs.immich.app/features/automatic-backup)

### Inferences
- **Recommended agent design:**
  - Mac: FSEvents with stored `lastEventId` + volume UUID, so the agent catches up after sleep.
  - Windows: USN journal for NTFS; it needs admin or a service to read the volume journal (not verified here). Fall back to ReadDirectoryChangesW plus a periodic scan.
  - Both: a daily full-scan reconciliation, as Syncthing does hourly.
  - Within the git-tracked markdown repo, `git diff --name-status <lastIndexedCommit>..HEAD` is the simplest durable change log, exact even after long offline periods. The hub can index straight from the GitHub repo or from a VPS clone on push (webhook or cron `git pull`), with no device agent at all.
- **Hashing:** pre-filter on mtime + size (as Syncthing does), then hash with BLAKE3 or SHA-256. Key catalog rows by (device_id, path), with `content_hash` as a secondary index for cross-device dedup. Use partial or sampled hashes (Spacedrive) for very large files.
- **Exclusions:**
  - `.sync-conflict-*` files
  - `.git/`
  - SQLite DBs
  - cloud-only placeholders: on Windows, check the `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`/OFFLINE attributes before reading, or risk triggering OneDrive downloads (Microsoft Tech Community thread above).

### Gaps
- Did not verify the privilege level needed to read the USN journal (`FSCTL_READ_USN_JOURNAL`) from a non-admin user process on Windows 11, or journal wrap and size defaults.
- Did not verify the exact Windows placeholder attribute names in primary Microsoft docs.
- No primary-source benchmark comparing watcher CPU/RAM cost on macOS vs Windows was found.

## Q4. Which pattern comparable open-source "personal AI memory/search" projects actually use, and what problems they report

### Takeaway
Most shipping projects are centralized push (Khoj, Open WebUI/oikb, Immich, Basic Memory Cloud) or local-per-device (Basic Memory local, Smart Connections, Everything). Federated "metadata hub + on-demand fetch" exists only in early or proprietary form (Spacedrive v2 pre-beta, Tailscale Aperture for MCP aggregation). Recurring problems:
- sync status opacity and stuck indexing (Khoj)
- iOS background limits (Immich)
- per-device re-indexing and "don't sync the index" (Smart Connections)
- gateway stability (MetaMCP)
- server RAM well above 2 GB

### Cited Findings
| Project | Pattern | License | Notable reported problems / constraints | Source |
|---|---|---|---|---|
| Khoj | Centralized push (desktop/Obsidian/Emacs clients → server `/api/content`; 10-min mtime polling) | AGPL-3.0 | No per-file sync status (#1363, 2026); stuck markdown indexing (#1437, 2026); "unable to index local files" (#1105, 2025); ~4 GB RAM | [main.js](https://github.com/khoj-ai/khoj/blob/HEAD/src/interface/desktop/main.js), [#1363](https://github.com/khoj-ai/khoj/issues/1363), [#1437](https://github.com/khoj-ai/khoj/issues/1437), [#1105](https://github.com/khoj-ai/khoj/issues/1105), [RamNode](https://ramnode.com/guides/khoj) |
| Open WebUI + oikb | Centralized push with SHA-256 incremental diff, `watch` mode | MIT (oikb) | New (May 2026); requires Open WebUI ≥0.9.6 | [oikb](https://github.com/open-webui/oikb) |
| Immich | Centralized upload from mobile/desktop | AGPL-3.0 (not verified in this pass) | iOS background backup OS-controlled; ≥6 GB RAM | [requirements](https://docs.immich.app/install/requirements), [auto backup](https://docs.immich.app/features/automatic-backup) |
| Basic Memory (local) | Local index per device; files synced by git/Syncthing | AGPL-3.0 | Multilingual MiniLM ~671 MB RSS; cutoff tuning for CJK; FastEmbed pooling change | [benchmark doc](https://github.com/basicmachines-co/basic-memory/blob/main/docs/multilingual-embedding-benchmark.md) |
| Basic Memory Cloud | Centralized (rclone bisync → cloud indexes) | AGPL engine; paid service | Newer-wins conflicts; `max_delete=25` guard | [cloud sync docs](https://docs.basicmemory.com/cloud/cloud-sync) |
| Smart Connections | Local index per device | (not verified) | Index must be regenerated per device with iCloud/Git | [PromptQuorum](https://www.promptquorum.com/power-local-llm/local-llm-with-obsidian-2026) |
| Spacedrive v2 | Federated/P2P metadata index, on-demand range reads, MCP server | Apache-2.0 | Pre-beta (beta 2026-11-01); nightly schema breaks; mobile/Windows maturity unclear | [README](https://github.com/spacedriveapp/spacedrive) |
| Tailscale Aperture | Federated MCP aggregation inside a tailnet | Proprietary | Tailnet clients only; claude.ai can't use it directly | [docs](https://tailscale.com/docs/aperture/mcp-server) |
| MetaMCP | MCP aggregator/gateway (Postgres) | MIT | Empty `tools/list` at pool saturation; SSE instability behind Nginx | [mcp.directory guide](https://mcp.directory/blog/metamcp-complete-guide-2026) |
| Everything (voidtools) | Metadata-only local index via USN | Freeware (closed) | Folder (non-NTFS) watchers can miss changes | [voidtools forum](https://voidtools.com/forum/viewtopic.php?p=486) |

### Inferences
- The industry default for "AI over my files" is centralized push, because it makes offline devices irrelevant and keeps query-time logic simple. The cost is server RAM and a full data copy, which the user's 2 GB VPS cannot afford for large non-markdown corpora.
- No project solves the iPhone as a source. All of them treat mobile as either an uploader with unreliable background execution (Immich) or a client only.
- **Lessons to copy:**
  - Expose sync and index status per file (the gap in Khoj #1363).
  - Use content hashes, not just mtime.
  - Never sync index databases.
  - Pin embedding model and version.
  - Keep the gateway simple (MetaMCP stability reports).

### Gaps
- No high-quality 2025–2026 HN/Reddit threads specifically about multi-device personal semantic search were found (searches returned only generic self-hosting threads), so the user-sentiment evidence is thin.
- Licenses for Immich and Smart Connections were not re-verified in this pass.

## Q5. Recommendation for this user's scale (1 person, Mac + Windows + iPhone, 2 GB Seoul VPS) and what existing pieces to reuse

### Takeaway
Recommended: a **hybrid**. Keep the existing P2P-plus-central setup for the markdown memory repo (git everywhere, with Basic Memory on the VPS as the always-on index for claude.ai). Add a **lightweight federated metadata catalog** for everything else: per-device agents on the Mac and Windows push metadata, hashes, short excerpts and device-computed embeddings to SQLite on the VPS. Content is fetched on demand over Tailscale, and only the VPS is public.

Avoid a full centralized content store (Khoj, Immich, MetaMCP) on the 2 GB VPS. Watch Spacedrive v2 (beta Nov 2026) as a possible future replacement for the custom device agent.

### Cited Findings
- claude.ai needs a public, OAuth-protected MCP and cannot reach VPN or private endpoints. — [Claude Help Center](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp)
- The VPS's mcp-auth-proxy already provides OAuth 2.1 + TLS and stdio→`/mcp`. — [mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy)
- The multilingual MiniLM embedder costs about 671 MB RSS in Basic Memory on SQLite. — [Basic Memory benchmark](https://github.com/basicmachines-co/basic-memory/blob/main/docs/multilingual-embedding-benchmark.md)
- Khoj needs about 4 GB and Immich at least 6 GB, so both are unsuitable for this VPS. — [RamNode Khoj](https://ramnode.com/guides/khoj); [Immich requirements](https://docs.immich.app/install/requirements)
- mcp-proxy "named servers" can host several MCP backends behind one process. — [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy)
- Taildrive can expose device folders over WebDAV inside the tailnet (alpha). — [Taildrive](https://tailscale.com/kb/1369/taildrive)
- FSEvents (persistent event IDs) and the USN journal let an agent catch up after sleep. — [Apple FSEvents guide](https://developer.apple.com/library/mac/documentation/Darwin/Conceptual/FSEvents_ProgGuide/UsingtheFSEventsFramework/UsingtheFSEventsFramework.html); [Microsoft change journals](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals)
- The free Tailscale Personal plan covers unlimited user devices (secondary source). — [CostBench](https://costbench.com/software/business-vpn/tailscale/free-plan)

### Inferences
**Concrete plan (staged)**

0. **Reuse as-is.**
   - The git markdown repo stays canonical; it is the conflict-resolution layer for AI-written memory.
   - Basic Memory stays local on the Mac (for Claude Code and Codex via stdio) and on the VPS (for claude.ai via mcp-auth-proxy).
   - On the VPS, feed Basic Memory from a cron or webhook `git pull` of the repo, so the VPS index stays current even when every laptop is asleep. In effect this is centralized for the small, high-value markdown corpus.
1. **Add Tailscale** to the VPS, Mac, Windows and iPhone (the iPhone as a client only).
   - Tag the VPS `tag:hub`.
   - ACL: only `tag:hub` → devices on the agent port.
   - Do not use Funnel (the VPS is already public). Skip Headscale (no Funnel/Serve, extra RAM).
2. **Device agent** (Mac first, Windows second): a small daemon.
   - Watches configured roots: Mac via FSEvents with a persisted event ID; Windows via the USN journal or `watchfiles` plus a nightly rescan.
   - Hashes changed files with BLAKE3 or SHA-256.
   - Extracts text from md/txt/pdf/docx and computes the multilingual MiniLM embedding locally, using the same model and version as the VPS, pinned (see the FastEmbed pooling change).
   - Pushes catalog rows (device, path, size, mtime, hash, title, excerpt, vector) to the hub over the tailnet.
   - Exposes read-only `fetch(path, offset, length)` and `stat(path)` on its tailnet IP, with a path allowlist.
3. **Hub MCP on the VPS:** one small MCP server, exposed through the existing mcp-auth-proxy (or as a second named server behind mcp-proxy).
   - `search_files(query, device?, type?)` runs hybrid FTS5 + sqlite-vec over the catalog.
   - `fetch_file(device, path)` proxies to the device agent over the tailnet. If the device is offline, it returns a clear "offline since T" plus the cached excerpt.
   - `list_devices()` reports device status.
   - Optionally merge or route to Basic Memory's `search_notes` so one connector serves both.
   - Rough cost: well under 100 MB plus SQLite page cache, assuming no embedding happens on the VPS.
4. **Clients:**
   - claude.ai web/mobile → the public hub (OAuth).
   - Claude Code and Codex on the Mac or Windows → the hub over its tailnet hostname (bearer token or Tailscale identity), or the local Basic Memory over stdio.
   - Aside → depends on its MCP support (unknown).
5. **iPhone files:** route them into a Mac-watched folder (iCloud Drive folder on the Mac, Sushitrain/Syncthing, or Working Copy commits to the repo). Don't try to index on the phone.
6. **Later:** evaluate Spacedrive v2 beta (Apache-2.0, MCP server, Iroh P2P, BLAKE3) as a replacement for the custom device agent once Windows and iOS support and remote MCP access are confirmed.

**Why not pure centralized:** copying all files to the VPS means larger privacy exposure, on-VPS embedding RAM (~0.7 GB) and parsing on 1 vCPU, and disk growth. It is fine only for the markdown repo, which this plan already treats as centralized.

**Why not pure P2P:** the iPhone cannot be a peer, and claude.ai still needs a public hub. Replicating all files to all devices is wasteful.

**Main risks:**
- Sleeping laptops make `fetch` unavailable. Mitigate with excerpts and summaries in the catalog and an optional VPS cache for pinned folders.
- Embeddings and excerpts on the VPS are still sensitive data.
- An aggregator with cross-device read access is a prompt-injection exfiltration path. Use read-only tools, allowlists, per-tool consent in clients, and logs.

### Gaps
- No benchmarks exist for the proposed custom hub's latency or RAM. The figures above are estimates.
- Aside's MCP compatibility is unknown.
- The exact free-tier terms of Tailscale should be confirmed on tailscale.com/pricing.
- Whether claude.ai connector traffic to the Seoul VPS would be affected by IPv4-only or egress-range constraints should be tested. Expected fine, since the user's current setup already works with claude.ai.
