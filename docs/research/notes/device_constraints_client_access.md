# Device-side constraints and AI-client access paths for a personal cross-device file/memory index (iPhone, Windows, macOS + Claude/ChatGPT/Codex/Aside)

Research date: 2026-10-10. User setup: MacBook (Apple Silicon), iPhone, Windows laptop; Vultr Seoul VPS (1 vCPU/2 GB) running Basic Memory MCP behind mcp-auth-proxy (password-based OAuth, auto-TLS on an sslip.io hostname); notes in a private GitHub markdown repo. "Official" = vendor docs; "community" = forums, blogs, third-party repos. Older items are dated where possible.

## 1. iOS: can an iPhone run a background indexer, and what can Shortcuts and sync apps do?

### Takeaway
No third-party iOS app can keep running in the background to index files. BGProcessingTask runs only when the system decides to. iOS 26's BGContinuedProcessingTask must be started by a user action in the foreground and shows a cancellable Live Activity. File access outside the app's own sandbox works only for folders the user picks once (through a security-scoped bookmark), and Photos are not files. Treat the iPhone as a client and an occasional uploader, not an indexer: (a) query the server index through the Claude iOS app connector, and (b) push content with Shortcuts, Working Copy (git) or a share-sheet upload when the user acts or a Time-of-Day automation fires.

### Cited Findings
**Background execution (official)**
- `BGProcessingTaskRequest` is "A request to launch your app in the background to execute a processing task that can take minutes to complete". It has the flags `requiresExternalPower` ("requires a device connected to power") and `requiresNetworkConnectivity`. Available since iOS 13. The docs give no runtime guarantee or schedule. — [Apple: BGProcessingTaskRequest](https://developer.apple.com/documentation/backgroundtasks/bgprocessingtaskrequest)
- `BGContinuedProcessingTask` (iOS/iPadOS 26.0+) is "A task that starts in the foreground and can continue running in the background as needed". Apple's description continues: "The system displays the progress of this task in a Live Activity and a person can cancel it". It must report progress via `ProgressReporting`. Apple also warns that "The system can terminate a continuous background task abruptly … under resource constraints", and that tasks showing little progress are killed first. — [Apple: BGContinuedProcessingTask](https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtask)
- Community: BGContinuedProcessingTask "must be submitted as a result of a user action". The scheduling cap is "max 1 refresh task + 10 processing tasks". Developers report `expirationHandler` firing unpredictably on real devices, depending on CPU, memory or battery. — [Apple Developer Forums thread 805554](https://developer.apple.com/forums/thread/805554); [DEV: WWDC25 iOS 26 background APIs](https://dev.to/arshtechpro/wwdc-2025-ios-26-background-apis-explained-bgcontinuedprocessingtask-changes-everything-9b5) (secondary)

**File access (official)**
- Since iOS 13, an app can show `UIDocumentPickerViewController(forOpeningContentTypes: [.folder])` so the user picks a directory from any file provider, iCloud Drive included. The app gets a security-scoped URL and must call `startAccessingSecurityScopedResource()` and use `NSFileCoordinator`. It can keep access across launches by saving a bookmark. — [Apple: Providing access to directories](https://developer.apple.com/documentation/uikit/providing-access-to-directories)
- The app then appears in "Settings > Privacy > Files and Folders" and "users can revoke or restore permission for each app at any time". Apple says apps "must be ready to handle failures" because `startAccessingSecurityScopedResource()` can fail. — [same source](https://developer.apple.com/documentation/uikit/providing-access-to-directories)

**Sync apps (vendor FAQ, community)**
- Möbius Sync, the paid iOS Syncthing client: "no iOS app can run continuously in the background". It connects only while the app is open, briefly after, and when iOS triggers it. iOS scheduling "is not predictable"; it "may take 24 hours to start to sync" and then gives "a total of 1-2h of sync activity per day once stable". iOS apps "cannot access each others' files". Photos and videos "are not stored as files under iOS", so they cannot be synced directly. — [Möbius Sync FAQ](https://mobiussync.com/faq/)
- Working Copy (iOS git client): has Shortcuts actions "for most operations" and a "Sync Repository" action that automations can trigger. "Sync in Background" keeps Auto-Sync checking for local and remote changes. Clone, fetch, pull and push keep running in the background, with progress shown as Live Activities. Auto-Sync needs the Pro unlock. — [App Store: Working Copy](https://apps.apple.com/app/id896694807)

**Shortcuts automations (official + community)**
- These triggers can run without asking: Time of Day, Alarm, Sleep, Arrive, Leave, CarPlay, Email, Message, Transaction, Wi-Fi, Bluetooth, Apple Watch Workout, NFC, App, Airplane Mode, Do Not Disturb, Low Power Mode, Battery Level, Charger, Sound Recognition. "Before I Commute" cannot. Individual actions may still need to be set to run automatically. — [Apple Shortcuts User Guide (search snippet of apd602971e63)](https://support.apple.com/guide/shortcuts/apd602971e63/ios). The page I fetched was only the table of contents, but it confirms the guide now covers iOS 27 and iOS 26.
- Apple's iOS 26 intro page: "when an event occurs you'll receive a notification asking you to run the automation. You can also edit a personal automation to run without asking." — [Apple: Intro to personal automation (iOS 26)](https://support.apple.com/en-ca/guide/shortcuts/apd690170742/9.0/ios/26)
- Community reports (older, 2019–2020): Time-of-Day + "Get Contents of URL" with "Ask Before Running" off works, but may not run if the phone has not been picked up for hours. Many actions error out while the phone is locked. — [Apple Developer Forums 665845](https://developer.apple.com/forums/thread/665845); [Automators forum](https://talk.automators.fm/t/want-time-based-confirmation-free-shortcut-to-run/6572)

**Spotlight / Apple Intelligence (official)**
- `IndexedEntity` (iOS 18+) lets an app put its own App Intents entities into Spotlight's semantic index, so Apple Intelligence and Siri can find them. This lets an app write into the index. — [Apple: IndexedEntity](https://developer.apple.com/documentation/appintents/indexedentity); [WWDC24 session 10134](https://developer.apple.com/videos/play/wwdc2024/10134)

### Inferences
- An iPhone "indexer" would be at best a user-triggered `BGContinuedProcessingTask`, or a `BGProcessingTask` that runs while charging overnight. It could only scan folders the user picked in the document picker, and could see Photos only through a separate PhotoKit permission (not researched here). Building this as a custom app is a lot of work for an individual and gives unreliable results.
- Better low-effort uploader paths:
  - A Time-of-Day or Charger-trigger Shortcut that sends "Get Contents of URL" POSTs of selected files or text to the VPS.
  - A share-sheet Shortcut ("send to index").
  - Working Copy keeping a clone of the GitHub notes repo and pushing on Shortcut triggers, so the server indexes from GitHub.
  
  All of these are best-effort, not guaranteed to run.
- The iPhone needs no local index for reading: the Claude iOS app can query the server index through the remote connector (section 4).
- I found no public API that lets a third-party agent query the system Spotlight / Apple Intelligence semantic index on iOS. IndexedEntity is write-only from the app's side. Treat the iPhone's on-device semantic index as unreachable for this design.

### Gaps
- No primary source on the actual runtime budget of BGProcessingTask, which Apple does not publish.
- Not researched: a-Shell, Nextcloud iOS (auto-upload limits), the Khoj iOS app, PhotoKit background limits.
- Whether a Shortcuts automation can read an iCloud Drive folder ("Get Contents of Folder") while the phone is locked on iOS 26/27: only old community reports found.

## 2. Windows: best way to run a background indexer, detect changes, reuse existing indexes, avoid OneDrive hydration, Claude Code gotchas, Recall

### Takeaway
On Windows the strongest option is to reuse voidtools Everything rather than build a new filename index. It keeps a near-instant filename/metadata index from the NTFS change journal, can be queried through `es.exe -json`, its SDK, or its HTTP server (which has no TLS), and community MCP servers for it already exist. For content (full-text or embeddings), a small native agent that reads the USN journal or uses `ReadDirectoryChangesW` and pushes changed files to the VPS is the standard approach. The agent must skip OneDrive placeholders, which carry the `RECALL_ON_*` attributes, or reading them will download them. Recall has no API that lets a third-party app read its snapshots.

### Cited Findings
**Change detection (official)**
- `FindFirstChangeNotification` / `ReadDirectoryChangesW` "requires that an application be running at all times", and with many files its overhead "might also cause the operating system's performance to decrease". NTFS instead keeps a USN change journal that is updated "When any change is made to a file or directory in a volume". — [Microsoft Learn: Change Journals](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals)

**Reusing voidtools Everything (official vendor docs)**
- ES (`es.exe`) needs "Everything must be installed and running". It talks to Everything over IPC; exit code 8 means the Everything IPC window was not found. It supports `-json`, `-export-csv`, `-n`, `-path`, `-sort dm`, and queries such as `dm:today`. Some options need Everything 1.5: `-add-columns`, and the journal options `-journal` and `-from-journal-pos`. — [voidtools: ES command line](https://www.voidtools.com/support/everything/command_line_interface/)
- Everything's HTTP server is enabled under Tools > Options > HTTP Server. It accepts `json=1` and `search` / `offset` / `count` / `path` / `sort` parameters. It offers only optional HTTP Basic auth, it "does not support TLS", and credentials can be recovered by anyone watching an unencrypted connection. You can bind it to `127.0.0.1`. — [voidtools: HTTP server](https://www.voidtools.com/support/everything/http/)
- Community MCP: `mamertofabian/mcp-everything-search` uses the Everything SDK on Windows (it needs the Everything service running and `EVERYTHING_SDK_PATH`), Spotlight on macOS and `locate` on Linux. Several forks exist. — [Glama: mcp-everything-search](https://glama.ai/mcp/servers/@mamertofabian/mcp-everything-search); [Playbooks listing](https://playbooks.com/mcp/mamertofabian-everything-search)

**Reusing the Windows Search index (official / older)**
- The Windows Search OLE DB provider uses `provider=Search.CollatorDSO.1;EXTENDED PROPERTIES="Application=Windows"`. `SystemIndex` is the only queryable table. It is read-only (SELECT and GROUP BY). It can be called from PowerShell via ADODB. Sources are older (2012–2019) but the API is unchanged. — [Microsoft Scripting Guys blog (2012)](https://devblogs.microsoft.com/scripting/build-a-query-to-search-the-windows-index-from-powershell/); [Petri how-to](https://petri.com/how-to-query-the-windows-search-index-using-sql-and-powershell/)

**OneDrive Files On-Demand placeholders (official)**
- `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x00400000) means the file "is not fully present locally"; reading it "will cause at least some of the file/directory content to be fetched from a remote store".
- `FILE_ATTRIBUTE_RECALL_ON_OPEN` (0x00040000) means the item "has no physical representation on the local system"; opening it fetches data.
- `PINNED` / `UNPINNED` signal whether the user wants the file kept locally.

  — [Microsoft Learn: File Attribute Constants (2025-09)](https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants)

**Claude Code on Windows (official, current)**
- Runs natively on Windows 10 1809+ or under WSL. Git for Windows is optional: without it, Claude Code uses the PowerShell tool; with it, Git Bash backs the Bash tool. Set `CLAUDE_CODE_GIT_BASH_PATH` if Git Bash is not found. Sandboxing works only on WSL 2, not on native Windows. Install with `irm https://claude.ai/install.ps1 | iex` or `winget install Anthropic.ClaudeCode` (WinGet does not auto-update). — [Claude Code docs: Advanced setup](https://code.claude.com/docs/en/setup)
- Hooks run in Git Bash by default on Windows and fall back to PowerShell. Set `"shell": "powershell"` per hook to force PowerShell. Exec form cannot spawn the `.cmd`/`.bat` shims from npm (use `node script.js` or shell form). Quote `"${CLAUDE_PROJECT_DIR}"` for paths with spaces. `async: true` works on Windows. `SessionStart`, `PostToolUse` and `FileChanged` are the events that could trigger re-indexing. — [Claude Code docs: Hooks](https://code.claude.com/docs/en/hooks)
- For stdio MCP servers using `npx` on Windows, wrap the command: `claude mcp add --transport stdio example -- cmd /c npx -y …`. — [Claude Code docs: MCP](https://code.claude.com/docs/en/mcp)

**Copilot+ Recall (official)**
- Recall stores screen snapshots locally. Its developer surface is limited to:
  - the UserActivity API, which lets apps provide deep links for "relaunch" from Recall;
  - blocking capture with `SetWindowDisplayAffinity(WDA_MONITOR)`.

  It needs a Copilot+ PC (Qualcomm, Intel or AMD; Arm64EC not supported). GA was April 25, 2025. Admins can turn it off with `DisableAIDataAnalysis`. — [Microsoft Learn: Recall overview (updated 2026-02-03)](https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/recall/)

### Inferences
- Recommended Windows design:
  - Everything stays the filename/metadata index (it is already the fastest).
  - A small native agent runs as a per-user Task Scheduler task at logon, or as a service. It:
    - reads Everything (`es -json dm:>last-run`, or Everything 1.5's `-from-journal-pos`) or the USN journal to find changes;
    - skips anything with `RECALL_ON_DATA_ACCESS` / `RECALL_ON_OPEN` / `OFFLINE`;
    - uploads text or extracted chunks to the VPS over HTTPS (or over Tailscale).
  - A per-user task is probably simpler than a service, because a service runs in session 0 under a different account and may not see the user's OneDrive mapping. This is an inference; I found no source for it.
- Do not expose Everything's HTTP server beyond localhost or Tailscale, since it has no TLS.
- Recall cannot be a data source for this index: no documented read or query API.
- Native Windows vs WSL: the indexer should be native, so it can see NTFS and the USN journal directly and avoid crossing the `/mnt/c` boundary. Claude Code works either way; WSL 2 adds sandboxing.

### Gaps
- No primary source compared Task Scheduler and a Windows service for a per-user indexer, or how either interacts with OneDrive's per-user Cloud Files provider.
- USN journal reads need volume handle access, and I did not confirm the exact privilege requirement (admin vs. user) from Microsoft docs.
- I did not confirm whether Everything indexes OneDrive placeholders by default, or whether Everything 1.5 has left alpha/beta as of October 2026.

## 3. macOS: Spotlight reuse, FSEvents, iCloud dataless files, TCC for background agents, sleep

### Takeaway
On the Mac, reuse Spotlight (`mdfind`, which has a `-live` mode) for discovery and FSEvents for change detection. Check the `SF_DATALESS` flag so iCloud "Optimize Mac Storage" files are not downloaded. Expect TCC (privacy permission) friction: a launchd LaunchAgent that touches `~/Documents`, `~/Desktop` or iCloud Drive triggers TCC prompts or silent denials. You need a stable, signed binary path granted Full Disk Access or the specific folder permissions; versioned binary paths lose the grant on every update. Apple Silicon Macs cannot reliably be woken over the network and kept awake.

### Cited Findings
- `mdfind` "consults the central metadata store and returns a list of files that match the given metadata query". Options: `-onlyin dir`, `-name`, `-count`, `-0`, and `-live`, which gives live updates as matches change. `-interpret` makes a query behave like Spotlight-menu input, e.g. `kMDItemTextContent = search* cdw`. — local `man mdfind` on macOS (Darwin 25.2), read 2026-10-10 (primary, on-device)
- Dataless files: since macOS Sonoma, iCloud Drive runs on FileProvider. With "Optimise Mac Storage" on, evicted files become dataless. Detect them via `stat`/`getattrlist`: `SF_DATALESS` is set in `st_flags`. The reported size is the full downloaded size even though the data is not local. — [Eclectic Light: Sonoma changed iCloud Drive radically (2023-10)](https://eclecticlight.co/2023/10/25/macos-sonoma-has-changed-icloud-drive-radically/); [Eclectic Light: How iCloud Drive works in Sonoma (2024-03)](https://eclecticlight.co/2024/03/18/how-icloud-drive-works-in-macos-sonoma/); [Apple Developer Forums 763378](https://developer.apple.com/forums/thread/763378)
- TCC protects `~/Documents`, `~/Downloads`, `~/Desktop`, `~/Pictures` and others. A launchd plist whose program lives in a protected folder may be silently blocked; the fix is to move it (e.g. to `~/bin`) or grant Full Disk Access to the executable. — [InventiveHQ KB (secondary)](https://inventivehq.com/knowledge-base/macos/how-to-manage-launchagents-launchdaemons-macos); [Apple Developer Forums 132851: launch daemon can't read Desktop](https://developer.apple.com/forums/thread/132851); [Apple Developer Forums 661178: FDA from launchd daemon](https://developer.apple.com/forums/thread/661178)
- Community bug reports about Claude Code itself:
  - FDA/TCC prompts come back on every auto-update because each version lives at a new binary path.
  - Background-spawned child processes are blocked from `~/Documents` "despite FDA grant" ("Failed to create Attribution Chain").

  — [claudeissues #74234](https://claudeissues.com/issue/74234-macos-full-disk-access-tcc-prompts-reappear-on-every-auto-update-per-version-bin); [claudeissues #59065](https://claudeissues.com/issue/59065-bug-bg-pty-host-children-blocked-by-macos-tcc-on-documents-despite-fda-grant-fai) (community issue mirror)
- A 2026 article reports Apple announcing limits on Full Disk Access for AI agents. I could not fetch it (connection error), so this is unverified. — [pasqualepillitteri.it (unverified)](https://pasqualepillitteri.it/de/news/20345/apple-full-disk-access-ki-agenten-macos)
- Apple Silicon sleep, from a user report (Jan 2025) with no Apple engineer reply:
  - WoL wakes the Mac into "darkwake" for only about 30–60 seconds, and repeated packets don't extend it.
  - SMB browsing or an SSH session plus `caffeinate` keeps it awake.

  — [Apple Developer Forums 771999](https://developer.apple.com/forums/thread/771999). A secondary source says classic Power Nap was removed on M-series and third-party WoL is unreliable while sleeping. — [TidBITS Talk: WoL with Apple silicon](https://talk.tidbits.com/t/wake-on-lan-with-apple-silicon/33183)

### Inferences
- A Mac LaunchAgent indexer should:
  - live at a fixed path outside protected folders, e.g. `~/Library/Application Support/<tool>/bin` or `/usr/local/bin`;
  - be granted Full Disk Access once, in System Settings by the user;
  - skip `SF_DATALESS` files, or index only their metadata (name, size, mtime) from `mdls`/`stat` without reading content.
- Spotlight already indexes text of many formats, but `mdfind` returns only paths, not content or embeddings. Use it to find candidates, then read and chunk the local files yourself.
- Do not design anything that needs the server to pull from a sleeping MacBook. Push from the Mac whenever it is awake (on wake, at intervals, or on FSEvents) instead.

### Gaps
- I did not fetch Apple's FSEvents docs; FSEvents is a well-known macOS API, but I have no citation in these notes.
- The 2026 report of Apple restricting Full Disk Access for AI agents is unverified; check Apple's WWDC26 / macOS 27 notes.
- I did not verify whether Spotlight's `kMDItemTextContent` is queryable for iCloud dataless files without triggering a download.

## 4. How each AI client can reach the index: claude.ai / Claude iOS, ChatGPT, Codex, Claude Code, Aside, and their limits

### Takeaway
One public remote MCP endpoint (Streamable HTTP + OAuth with DCR or CIMD), which is what the user's Basic Memory + mcp-auth-proxy already provides, reaches almost every client:

- **claude.ai web, Claude Desktop, Claude iOS and Claude Code**: add once on claude.ai; it syncs to mobile and is auto-imported into Claude Code. Free plan: 1 custom connector.
- **Codex CLI / app / IDE**: `config.toml` with `url` and `codex mcp login`.
- **Aside**: added custom MCP servers with OAuth in July–August 2026.
- **ChatGPT**: developer mode, web only, with plan limits that its own docs contradict.

Size and timeout limits differ by client: claude.ai about 150k characters and 240 s per call; Claude Code 25k tokens; Codex 60 s default tool timeout. Server tools should return short, paginated results.

### Cited Findings
**Claude: claude.ai web, Desktop, mobile, Cowork (official)**
- Custom connectors (remote MCP) are available on "Free, Pro, Max, Team, and Enterprise plans", but "Free users are limited to one custom connector". Team/Enterprise need Owner configuration. The server must be "reachable over the public internet from Anthropic's IP ranges". Local MCP servers in `claude_desktop_config.json` "aren't available in Cowork or claude.ai". Auth options in the add dialog: OAuth ("Use Claude's published identity (Recommended)", "Register automatically", "Use your own OAuth client"), fixed credentials, or no sign-in. — [Claude Help: Get started with custom connectors](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp)
- Claude connects to your server "from claude.ai, Claude Desktop, Claude mobile, Cowork, and Claude Code, and the same connector infrastructure backs all of them".
  - Transport: use Streamable HTTP. Legacy HTTP+SSE is still supported but "being deprecated".
  - OAuth: follows the 2025-03-26, 2025-06-18 and 2025-11-25 auth specs. DCR is supported. Redirect URI: `https://claude.ai/api/mcp/auth_callback` (hosted apps), plus a loopback redirect on any port for Claude Code.
  - Supported features: tools, prompts, resources, text and image results.
  - Not supported: resource subscriptions, sampling.

  — [Claude docs: Build an MCP server for Claude](https://claude.com/docs/connectors/building)
- Limits table, verbatim:

  | Limit | claude.ai and Desktop | Claude Code |
  | - | - | - |
  | Maximum tool result size | ~150,000 characters | 25,000 tokens (`MAX_MCP_OUTPUT_TOKENS`) |
  | Tool call timeout | 240 seconds per tool call | `MCP_TOOL_TIMEOUT` |

  — [same](https://claude.com/docs/connectors/building). Conflict: a third-party page cites a 300-second timeout for claude.ai/Desktop. — [MintMCP: Claude client issues](https://www.mintmcp.com/docs/mcp-client-issues-claude). Prefer Anthropic's 240 s.
- Auth details:
  - A 401 with `WWW-Authenticate: Bearer resource_metadata=…` is required; a header on a 200 is ignored.
  - Only the first `authorization_servers` entry is used.
  - Discovery, registration and token endpoints get 10 s; refresh gets 30 s.
  - Claude refreshes proactively up to 5 minutes before expiry and expects `invalid_grant` on dead refresh tokens.
  - PKCE S256 is required.
  - `client_credentials` (machine-to-machine) is not supported.
  - Static header credentials are "Beta, for a limited set of organizations" and entered by an org Owner, so they are not a dependable option for a personal Pro/Max account.
  - Anthropic egress IPs: `160.79.104.0/21`.

  — [Claude docs: Authentication for connectors](https://claude.com/docs/connectors/building/authentication)
- Community known issues (unofficial):
  - Tools whose serialized `inputSchema` exceeds 16 KiB are silently dropped.
  - Custom connectors sometimes lose tools or collapse to exactly 256 tools across all connectors.

  — [claudeissues #77296](https://claudeissues.com/issue/77296-bug-claude-ai-connector-ingestion-silently-drops-any-tool-with-inputschema-16-38); [MintMCP](https://www.mintmcp.com/docs/mcp-client-issues-claude)
- Mobile: Claude iOS/Android have supported remote MCP since July 2025. Servers added on claude.ai sync to the mobile app. Community guides from 2025 say servers cannot be added from the mobile app itself, which is older info. — [DEV: Remote MCP on Claude iOS/Android](https://dev.to/zhizhiarv/how-to-set-up-remote-mcp-on-claude-iosandroid-mobile-apps-3ce3) (secondary, 2025)

**Claude Code (official)**
- Add with `claude mcp add --transport http <name> <url>`, optionally with `--header "Authorization: Bearer …"`. OAuth goes through `/mcp` or `claude mcp login <name>`.
- Scopes: local (`~/.claude.json`), project (`.mcp.json`), user (`~/.claude.json`).
- Output: warning at 10k tokens, default max 25k, raised with `MAX_MCP_OUTPUT_TOKENS`. Oversized results are saved to a file and replaced by the file path.
- Idle timeout: 5 min for HTTP servers.
- Connectors added on claude.ai "are automatically available in Claude Code". Turn this off with `disableClaudeAiConnectors: true` or `ENABLE_CLAUDEAI_MCP_SERVERS=false`.

— [Claude Code docs: MCP](https://code.claude.com/docs/en/mcp)

**OpenAI Codex (official)**
- Config lives in `~/.codex/config.toml`, or project `.codex/config.toml` for trusted projects, under `[mcp_servers.<name>]`. HTTP servers take `url`, `bearer_token_env_var` and `http_headers`; OAuth goes through `codex mcp login <name>`. Defaults: `startup_timeout_sec` 10, `tool_timeout_sec` 60. "The ChatGPT desktop app, Codex CLI, and IDE extension support MCP servers and share MCP configuration for the same Codex host." — [OpenAI: Codex MCP (learn.chatgpt.com)](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

**ChatGPT (official but conflicting)**
- September 2025, OpenAI Developers: "full support for MCP tools in ChatGPT. In developer mode, developers can create connectors and use them in chat for write actions (not just search/fetch)". At that time this was for Plus and Pro on web. — [OpenAI Developers on X](https://x.com/OpenAIDevs/status/1965807401745207708)
- OpenAI Help Center article "Developer mode and MCP apps in ChatGPT", from search snippets only (the page returned 403): "Developer mode is currently in beta for Plus and Pro web users"; "full MCP is only available to Business and Enterprise/Edu users currently"; "Pro users can connect MCPs with read/fetch permissions in developer mode"; "Custom apps aren't available on mobile". — [OpenAI Help 12584461](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- A third-party 2026 summary notes the contradiction and lists:
  - Free: no MCP.
  - Plus: own MCP server via developer mode; write support unclear.
  - Pro: read/fetch per Help Center.
  - Business/Enterprise/Edu: full MCP, beta.
  - Web only; agent mode does not use custom MCP apps.
  - Transports: SSE or Streamable HTTP; auth: OAuth, none, or mixed.

  — [Coworker.ai: ChatGPT MCP 2026](https://coworker.ai/blog/chatgpt-mcp) (secondary)
- Current Apps SDK doc: go to "ChatGPT Plugins" → "Add custom MCP server", and either enter a public URL including the `/mcp` path or choose **Tunnel**. — [OpenAI Apps SDK: Connect from ChatGPT](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt)
- Secure MCP Tunnel: an open-source Go `tunnel-client` runs on your side, makes outbound connections only, and long-polls OpenAI. It works with ChatGPT custom connectors, Codex and the Responses API. It needs a Platform org `tunnel_id`, a runtime API key, and a tunnel role granted by an org owner or RBAC admin. — [OpenAI: Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

**Aside (official changelog + local CLI)**
- Aside as an MCP server: `aside mcp` (stdio) exposes the tools `exec` (browser agent on logged-in sites) and `repl` (Playwright-style JavaScript, 120 s timeout). Config: `{"command":"aside","args":["mcp"]}`. — [Aside docs: CLI, MCP, REPL](https://docs.aside.com/help/developers); local `aside mcp --help` (CLI v1.26.1008.1938)
- Aside as an MCP client:
  - v1.26.711.1147 (2026-07-11): "Adds MCP settings, a server setup dialog, session tools, and authenticated HTTP connectors."
  - v1.26.813.1554 (2026-08-13): "Detects when a custom MCP server needs authorization, starts OAuth before a tool call fails, and provides an authorization retry action."
  - v1.26.806.238 (2026-08-06): "Caches each server's tool list across reconnects."

  — [Aside changelog: Components](https://docs.aside.com/changelog/components)
- The local CLI has no `mcp add` command (`aside --help`, `aside settings --help`). Custom servers appear to be configured only in the app's MCP settings UI. — local CLI help, 2026-10-10

### Inferences
- The user's existing endpoint (Streamable HTTP, password-based OAuth via mcp-auth-proxy, public TLS) already fits claude.ai/iOS/Claude Code, Codex and Aside. The one thing to verify is that mcp-auth-proxy:
  - exposes a DCR `registration_endpoint` or CIMD;
  - returns 401 + `resource_metadata`;
  - accepts the `https://claude.ai/api/mcp/auth_callback` redirect plus port-agnostic loopback redirects for Claude Code and Codex;
  - answers token requests within 10 s on the 1 vCPU VPS.
- Optionally firewall the VPS so the MCP port is reachable only from `160.79.104.0/21` (Anthropic), the user's Tailscale tailnet, and OpenAI and Aside egress (not researched). This conflicts with Codex and Aside running on the user's own machines, which reach the server from the user's own IPs or Tailscale.
- Design tools for the strictest client:
  - keep results under about 25k tokens (Claude Code) and about 150k characters (claude.ai);
  - finish within 60 s (Codex default) and 240 s (claude.ai);
  - return snippets with IDs, and offer a separate `fetch(id)` tool, instead of whole files.
- Claude Code auto-imports claude.ai connectors. If the user also adds the same server locally with `claude mcp add`, it will show up twice. Pick one.
- ChatGPT is the weakest client: web only, plan-dependent, and documentation that contradicts itself. Treat it as optional.

### Gaps
- No primary source on response-size or timeout limits for ChatGPT developer-mode MCP or for Aside's MCP client.
- No Aside documentation on which transports and auth flows its custom MCP client supports (DCR? static headers?), or whether its cloud/remote hosts can reach the user's server. I inferred from the changelog only.
- I could not load the OpenAI Help Center article directly (403), so ChatGPT plan details as of October 2026 rest on search snippets and a secondary summary.
- Whether custom connectors can now be added directly in the Claude iOS app in 2026: the 2025 info says no; no 2026 confirmation.

## 5. Remote access to on-device content from the server: Tailscale, Serve/Funnel, Taildrive, waking sleeping laptops

### Takeaway
Tailscale can link the VPS, Mac, Windows PC and iPhone, but it cannot wake a sleeping device by itself. The iPhone cannot share files over Taildrive, and no iOS app can serve files in the background. Taildrive (WebDAV share from macOS/Windows/Linux) is still alpha. So a pull model, where the server fetches from devices on demand, works only for always-on desktops. For a MacBook, Windows laptop and iPhone, a push model is required: each device sends changes to the VPS while it is awake. Optionally, a live "search my laptop right now" tool can be exposed over Tailscale when the laptop happens to be online.

### Cited Findings
- iOS VPN On Demand rules per interface (Wi-Fi, cellular, Ethernet): "Always" / "Never" / "Do Nothing". — [Tailscale KB 1291: VPN On Demand](https://tailscale.com/kb/1291/ios-vpn-on-demand)
- Battery cost of an always-on iOS connection, from community anecdotes only (not measurements): about 1–3% battery; another user reports 5% over 10 days with VPN On Demand. — [SplitMetrics app page aggregating reviews](https://splitmetrics.com/apps/tailscale/id1470499037) (low-quality source)
- Taildrive "is currently in alpha".
  - Sharing works only from macOS, Windows, Linux and Synology; iOS and Android can access shares but cannot share.
  - Access is over WebDAV at `100.100.100.100:8080`.
  - It needs the `drive:share` / `drive:access` node attributes plus grants in the tailnet policy.

  — [Tailscale KB 1369: Taildrive](https://tailscale.com/kb/1369/taildrive)
- Funnel exposes a local service to the public internet.
  - It "can only listen on ports 443, 8443, and 10000".
  - It terminates TLS on the device and has "non-configurable bandwidth limits".
  - It "only works on platforms that can run the Tailscale CLI" (on macOS, the open-source variants for some features).
  - It is beta and available on all plans.

  — [Tailscale KB 1223: Funnel](https://tailscale.com/kb/1223/funnel)
- Tailscale "cannot physically turn on a device that is asleep or powered off—not by itself". WoL needs an always-on helper on the same LAN (e.g. a Pi or router running UpSnap) reached over the tailnet. — [Tailscale blog: Wake-on-LAN with UpSnap (2025-08-19)](https://tailscale.com/blog/wake-on-lan-tailscale-upsnap)
- Apple Silicon WoL gives darkwake of about 30–60 s; an SSH session plus `caffeinate` keeps the Mac awake (user report, Jan 2025). — [Apple Developer Forums 771999](https://developer.apple.com/forums/thread/771999)

### Inferences
- Recommended topology:
  - The VPS joins the tailnet.
  - Mac and Windows agents push to the VPS over the tailnet, or over public HTTPS with a device token.
  - The public MCP endpoint stays only on the VPS, because claude.ai and the Claude iOS app need a public URL reachable from Anthropic IPs.
  - Funnel on a laptop is unnecessary and fragile: it disappears when the laptop sleeps.
- The user has no always-on home LAN device (only the VPS, which is remote), so WoL is not practical. Design for "the index reflects each device's state as of its last push", and show a per-device `last_seen` value in tool results.
- The iPhone needs Tailscale only if the uploader posts to a tailnet-only endpoint. Using the public HTTPS endpoint with a token avoids an always-on VPN and its battery cost.
- If the user ever needs ChatGPT to reach a tailnet-only or on-device MCP without a public URL, OpenAI's Secure MCP Tunnel (outbound-only) is a documented option. It needs an OpenAI Platform org with tunnel roles.

### Gaps
- No primary Tailscale figures on iOS battery impact; only anecdotal reports.
- I did not verify whether Tailscale on Windows or macOS can keep a laptop reachable during Modern Standby or darkwake.
- Not researched: Tailscale Serve (tailnet-only HTTPS) and the specifics of exposing an agent's local API.
