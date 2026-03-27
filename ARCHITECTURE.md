# LogLens — Architecture & Flow

## Overview

LogLens is a Claude-powered agentic system that audits Clockify time logs for a software team.
It detects missing/incomplete log days and poor-quality time entry descriptions, then produces
a color-coded Excel report.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│  - Loads .env                                               │
│  - Prompts user for date range                              │
│  - Calls run_agent() → receives structured JSON             │
│  - Calls build_excel_report() → saves .xlsx                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   agent/runner.py                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │               Claude Agentic Loop                   │   │
│  │                                                     │   │
│  │  1. Send user prompt + system prompt to Claude      │   │
│  │  2. Claude responds with tool_use blocks            │   │
│  │  3. Dispatch each tool call → get result            │   │
│  │  4. Feed results back to Claude                     │   │
│  │  5. Repeat until stop_reason == "end_turn"          │   │
│  │  6. Parse final JSON from Claude's text response    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Tools registered with Claude:                              │
│    • get_all_users                                          │
│    • get_time_entries                                       │
│    • get_projects                                           │
│    • detect_missing_logs                                    │
└──────────┬─────────────────────────────────────────────────┘
           │ dispatches tool calls
           ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│   tools/clockify_tools.py        │   │   tools/analysis_tools.py        │
│                                  │   │                                  │
│  get_all_users()                 │   │  detect_missing_logs()           │
│    → GET /workspaces/{id}/users  │   │    → Iterates weekdays in range  │
│                                  │   │    → Sums hours per date         │
│  get_time_entries()              │   │    → Flags Missing (0h) or       │
│    → GET /user/{id}/time-entries │   │      Incomplete (< MIN_HOURS)    │
│    → Parses ISO 8601 duration    │   │                                  │
│                                  │   └──────────────────────────────────┘
│  get_projects()                  │
│    → GET /workspaces/{id}/       │
│        projects                  │
│                                  │
│  parse_duration()                │
│    → PT2H30M → 2.5 hours         │
└──────────────────────────────────┘
           │ results flow back to Claude
           ▼
┌─────────────────────────────────────────────────────────────┐
│                   agent/prompts.py                          │
│                                                             │
│  SYSTEM_PROMPT instructs Claude to:                         │
│    • Score each description 1–5 (quality rubric)            │
│    • Flag entries with score ≤ 2                            │
│    • Detect copy-pasted descriptions across days            │
│    • Return structured JSON only (no prose)                 │
└─────────────────────────────────────────────────────────────┘
           │ final JSON output
           ▼
┌─────────────────────────────────────────────────────────────┐
│                 report/excel_builder.py                     │
│                                                             │
│  Sheet 1 — Summary                                          │
│    Per-user count: Missing Days | Incomplete Days | Flagged │
│                                                             │
│  Sheet 2 — Missing Logs                          (color)    │
│    User | Date | Day | Hours Logged | Severity             │
│    RED  → Missing (0h logged)                               │
│    AMBER → Incomplete (< MIN_HOURS logged)                  │
│                                                             │
│  Sheet 3 — Poor Descriptions                     (color)    │
│    User | Date | Project | Description | Score | Reason     │
│    RED  → Score 1 (blank)                                   │
│    AMBER → Score 2 (vague / single word)                    │
│                                                             │
│  Saved to: output/loglens_report_YYYY-MM-DD.xlsx            │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow (Step by Step)

```
User runs: python main.py
        │
        ├─ Input: start_date, end_date
        │
        ▼
run_agent(start_date, end_date)
        │
        ├─ Claude calls get_all_users()
        │       └─ Returns: [{id, name, email}, ...]
        │
        ├─ Claude calls get_projects()
        │       └─ Returns: [{id, name}, ...]
        │       └─ Claude builds internal id→name map
        │
        ├─ For each user:
        │   ├─ Claude calls get_time_entries(user_id, start, end)
        │   │       └─ Returns: [{date, description, project_id, hours}, ...]
        │   │
        │   └─ Claude calls detect_missing_logs(user_name, entries, start, end)
        │           └─ Returns: [{user, date, day, hours_logged, severity}, ...]
        │
        ├─ Claude scores every description (1–5) internally
        │       └─ Flags entries where score ≤ 2
        │       └─ Detects duplicate descriptions across days
        │
        └─ Claude returns final JSON:
                {
                  "missing_logs": [...],
                  "poor_descriptions": [...]
                }
        │
        ▼
build_excel_report(data, start_date, end_date)
        │
        └─ Writes output/loglens_report_YYYY-MM-DD.xlsx
```

---

## Component Responsibilities

| File                       | Responsibility                                              |
|----------------------------|-------------------------------------------------------------|
| `main.py`                  | Entry point. Wires env, agent, and report together.         |
| `agent/runner.py`          | Claude agentic loop. Tool dispatch. JSON extraction.        |
| `agent/prompts.py`         | System prompt. Scoring rubric. Output contract.             |
| `tools/clockify_tools.py`  | Clockify REST API wrappers. Duration parsing.               |
| `tools/analysis_tools.py`  | Pure logic: gap detection, weekday filtering, severity.     |
| `report/excel_builder.py`  | Excel workbook construction. Color coding. File save.       |
| `.env`                     | Secrets and configuration (never commit this file).         |

---

## Configuration

| Variable              | Purpose                                     | Default |
|-----------------------|---------------------------------------------|---------|
| `CLOCKIFY_API_KEY`    | Authenticates all Clockify REST calls       | —       |
| `CLOCKIFY_WORKSPACE_ID` | Scopes all API calls to your workspace    | —       |
| `ANTHROPIC_API_KEY`   | Authenticates Claude API calls              | —       |
| `MIN_HOURS_PER_DAY`   | Threshold below which a day is "Incomplete" | `8`     |

---

## Description Quality Scoring Rubric

| Score | Condition                                              |
|-------|--------------------------------------------------------|
| 1     | Blank or empty                                         |
| 2     | Single word (e.g. "meeting") or under 10 words, vague  |
| 3     | Mentions activity but no project/outcome context       |
| 4     | Clear description of work done                         |
| 5     | Explains what, why, and outcome                        |

Entries with score ≤ 2 are flagged in the report.
Identical descriptions reused across multiple days by the same user are also flagged.
