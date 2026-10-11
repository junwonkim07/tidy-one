# Client logos: sources and licenses

These are the logos in the "Works with" list (`i18n/clients.json`). Each file is
one `<path fill="currentColor">` in a 24×24 `viewBox`, with no width or height,
so the page can tint it with the Sage palette. Only the markup was changed
(title and role removed, fill set). The path data is unchanged.

All marks come from **Simple Icons 16.34.0**
(<https://github.com/simple-icons/simple-icons>, fetched from
`https://cdn.jsdelivr.net/npm/simple-icons@16.34.0/icons/<slug>.svg`). Simple
Icons releases its icon data under **CC0 1.0**. Every file below is CC0 1.0.

**Trademarks.** Every name and logo here belongs to its owner. CC0 covers the
SVG data, not trademark rights. tidy-one uses the marks only to say which
clients can connect to its MCP server. tidy-one is not affiliated with these
companies, and they do not endorse it. The page says the same in its
disclaimer ("not affiliated with or endorsed by").

| File | Brand | Simple Icons slug | Upstream source (per Simple Icons) | License | Brand guidelines |
| - | - | - | - | - | - |
| `claude.svg` | Claude (Anthropic) | `claude` | https://claude.ai | CC0 1.0 (Simple Icons) | none listed |
| `claudecode.svg` | Claude Code (Anthropic) | `claudecode` | https://code.claude.com | CC0 1.0 (Simple Icons) | none listed |
| `cursor.svg` | Cursor (Anysphere) | `cursor` | https://cursor.com/brand | CC0 1.0 (Simple Icons) | https://cursor.com/brand |
| `googlegemini.svg` | Gemini CLI (Google Gemini mark) | `googlegemini` | https://gemini.google.com | CC0 1.0 (Simple Icons) | none listed |
| `jetbrains.svg` | JetBrains | `jetbrains` | https://www.jetbrains.com/company/brand/logos/ | CC0 1.0 (Simple Icons) | https://www.jetbrains.com/company/brand/ |
| `zedindustries.svg` | Zed (Zed Industries) | `zedindustries` | https://github.com/zed-industries/zed/blob/ccc939124fa2f366b3029926447fd0a0c46a85c7/assets/icons/logo_96.svg | CC0 1.0 (Simple Icons) | none listed |
| `cline.svg` | Cline | `cline` | https://cline.bot/assets/branding/logos/cline-wordmark-black.svg | CC0 1.0 (Simple Icons) | none listed |
| `warp.svg` | Warp | `warp` | https://warp.dev | CC0 1.0 (Simple Icons) | none listed |
| `raycast.svg` | Raycast | `raycast` | https://www.raycast.com/press | CC0 1.0 (Simple Icons) | https://www.raycast.com/press |
| `perplexity.svg` | Perplexity | `perplexity` | https://www.perplexity.ai | CC0 1.0 (Simple Icons) | none listed |
| `trae.svg` | TRAE | `trae` | https://www.trae.ai | CC0 1.0 (Simple Icons) | none listed |
| `opencode.svg` | OpenCode | `opencode` | https://github.com/anomalyco/opencode/blob/1251a870cb384543c150c4a72fb101b55eec971b/packages/identity/mark.svg | CC0 1.0 (Simple Icons) | none listed |
| `lmstudio.svg` | LM Studio | `lmstudio` | https://files.lmstudio.ai/lmstudio_icon2.svg | CC0 1.0 (Simple Icons) | none listed |

## Clients shown as a text wordmark (no logo file)

No logo was traced or drawn for these. Each one appears as its name in text.

| Client | Why there is no logo |
| - | - |
| ChatGPT | Not in Simple Icons. OpenAI's brand guidelines (https://openai.com/brand/) ask third parties to request permission before using its logos. |
| Codex | Same as ChatGPT (OpenAI). |
| GitHub Copilot | GitHub retired the standalone Copilot logo: "Beginning in 2025, GitHub Copilot no longer has a standalone logo that heros the Copilot icon" (https://brand.github.com/brand-identity/copilot, also https://brand.github.com/foundations/logo, where github.com/logos now redirects). It points to "GitHub Copilot" product lockups instead, and the same guidelines forbid recolouring GitHub logos, which a tinted mark on this page would do. |
| Kiro | Not in Simple Icons, and kiro.dev publishes no press or brand kit (`/brand` and `/press` return 404). |
| goose | Not in Simple Icons. The project publishes no brand kit, and the logo PNGs in its Apache-2.0 repository come with no trademark grant (Apache-2.0 §6). |
| Aside | Not in Simple Icons. aside.com publishes no press or brand kit. |

Also left out: VS Code and Visual Studio, whose own MCP support goes through
GitHub Copilot. The VS Code brand guidelines (https://code.visualstudio.com/brand)
say "Using our icons to associate your offerings with Microsoft or its brands
in any way" is not OK, so that icon is not used. The GitHub Copilot entry
covers these editors.

## Evidence of MCP support (checked 2026-10-11)

URLs are the final pages after redirects. The Perplexity pages answer automated
requests with 403 (Cloudflare), so they can only be checked in a browser.

| Client | Primary source |
| - | - |
| Claude (web, Desktop, mobile) | https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp |
| Claude Code | https://code.claude.com/docs/en/mcp |
| ChatGPT | https://developers.openai.com/plugins/deploy/connect-chatgpt |
| Codex | https://learn.chatgpt.com/docs/extend/mcp?surface=cli (developers.openai.com/codex/mcp redirects here) |
| Cursor | https://cursor.com/docs/mcp |
| GitHub Copilot (VS Code, Visual Studio, JetBrains, Xcode, Eclipse) | https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/customize-copilot/extend-copilot-with-tools-and-context/extend-copilot-chat-with-mcp |
| Gemini CLI | https://geminicli.com/docs/tools/mcp-server/ |
| JetBrains AI Assistant | https://www.jetbrains.com/help/ai-assistant/mcp.html |
| Zed | https://zed.dev/docs/ai/mcp |
| Cline | https://docs.cline.bot/mcp/mcp-overview |
| Kiro | https://kiro.dev/docs/mcp/ |
| Warp | https://docs.warp.dev/agents/capabilities/mcp/ |
| Raycast | https://manual.raycast.com/ai/model-context-protocol |
| Perplexity | https://www.perplexity.ai/changelog/what-we-shipped---march-13-2026 ("Bring Your Own Connector"; help article: https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors) |
| TRAE | https://docs.trae.ai/ide/add-mcp-servers |
| OpenCode | https://opencode.ai/docs/mcp-servers/ |
| goose | https://goose-docs.ai/docs/getting-started/using-extensions/ |
| LM Studio | https://lmstudio.ai/docs/app/mcp |
| Aside | https://docs.aside.com/changelog/components (v1.26.711.1147: MCP settings and authenticated HTTP connectors; v1.26.723.2306: OAuth for custom MCP servers) |
