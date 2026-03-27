# Tilicho agent (Clockify + LLM reports)

This repo wires **[clockify-mcp](https://github.com/inakianduaga/clockify-mcp)** for Cursor and a **small Python pipeline** for scheduled runs: pull Clockify time entries, send them to an LLM with a fixed prompt, write **Markdown and Word** reports under `reports/`.

## Prerequisites

- **Node.js 20+** (for a **local** MCP build) *or* **Docker Desktop** (to run the published image instead).
- **Python 3.11+** recommended (3.14 works if dependencies install cleanly).
- **Clockify API key**: Clockify → Profile → API → Generate.
- **LLM API key** (e.g. OpenAI or any OpenAI-compatible endpoint).

## 1. Clockify MCP (Cursor)

Project config is `.cursor/mcp.json`. It is set up to run a **local clone** at `clockify-mcp/` with Node (no Docker required for that path).

### Local clone (current setup)

1. Build the server (repeat after `git pull` in `clockify-mcp/`):

   ```powershell
   cd g:\tilicho\agent\clockify-mcp
   npm install
   npm run build
   ```

2. Set environment variable **`CLOCKIFY_API_KEY`** (user or system), then **restart Cursor**.

3. The MCP entry uses `"${workspaceFolder}/clockify-mcp/build/index.js"`. If Cursor does not expand `workspaceFolder`, edit `.cursor/mcp.json` and set the first `args` entry to the **full path** to `build/index.js` on your machine.

**Optional:** from `clockify-mcp/`, run `npm run inspector` to debug the MCP with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector).

### Docker instead of local build

Use the image [`ghcr.io/inakianduaga/clockify-mcp:latest`](https://github.com/inakianduaga/clockify-mcp/pkgs/container/clockify-mcp): `docker pull ...` and replace the `clockify-mcp` block in `.cursor/mcp.json` with the `docker run ...` form from the [upstream README](https://github.com/inakianduaga/clockify-mcp/blob/main/README.md).

MCP tools include `listProjects`, `getTimeEntries`, `listUsers`, `getUserTimeEntries`, and `getSummaryReport` (see upstream docs).

## 2. Python pipeline (cron / CLI)

Used for **automation** (same Clockify data as the MCP server, via the public REST API).

```powershell
cd g:\tilicho\agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env: CLOCKIFY_API_KEY, OPENAI_API_KEY, optional OPENAI_BASE_URL / OPENAI_MODEL
```

**Pilot run** (no LLM call; checks Clockify fetch only):

```powershell
.\.venv\Scripts\python -m src.run_pipeline --start 2025-03-01 --end 2025-03-31 --user-email you@company.com --dry-run
```

**Full report** (writes `reports/*.md` and `reports/*.docx`):

```powershell
.\.venv\Scripts\python -m src.run_pipeline --start 2025-03-01 --end 2025-03-31 --user-email you@company.com
```

Optional `.env` keys:

- `CLOCKIFY_WORKSPACE_ID` — if omitted, the first workspace is used.
- `CLOCKIFY_USER_ID` — if set, `--user-email` is optional.
- `CLOCKIFY_USER_EMAIL` — default email if you omit `--user-email`.

## 3. Prompt and output shape

Edit `prompts/analysis_system.md` to match **Rajesh / Kiran** requirements and your agreed **report sections**. The LLM is instructed to follow that structure so outputs stay consistent for review.

## 4. What is intentionally not included

- **Postgres**: no DB layer until you have a concrete persistence need.
- **LangChain**: not added by default; add only if a workflow truly needs it.
