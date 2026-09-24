# Text-to-SQL Data Analyst — Detailed Build Plan

## 1. Why this project is a good LangChain teaching vehicle

It forces you to combine almost every layer of the cheatsheet in a way that has real safety stakes (you're letting an LLM generate SQL that touches a real database):

- **Schema introspection** — teaching the agent what tables/columns exist
- **Tools** — SQL execution, schema lookup, query validation
- **Structured output** — for the final natural-language summary + confidence
- **Middleware** — guardrails (read-only enforcement, row limits, human approval for risky queries)
- **LangGraph** — because "generate → validate → execute → retry-on-error → summarize" is a loop, not a single pass — this is the part where `create_agent` alone starts to feel constrained and you'll want a `StateGraph`

---

## 2. Architecture Overview

```
User question (NL)
       │
       ▼
┌─────────────────┐
│  Schema Loader   │  ← introspects DB once, caches as context
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  SQL Generator   │  ← LLM node: NL + schema → SQL (structured output)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  SQL Validator   │  ← static checks: read-only, no DDL/DML, syntax check
└─────────────────┘
       │
   ┌───┴───┐
  valid   invalid
   │        │
   ▼        ▼
┌────────┐ ┌──────────────┐
│Execute │ │ Retry w/ error│──► back to SQL Generator (max N retries)
│ (safe) │ │  feedback     │
└────────┘ └──────────────┘
   │
   ▼
┌─────────────────┐
│ Result Summarizer│  ← LLM node: rows → NL answer + structured summary
└─────────────────┘
   │
   ▼
Answer to user
```

This is a **LangGraph `StateGraph`** with a conditional retry edge — not a single-pass agent. That loop (generate → validate → execute → retry-on-error) is exactly the pattern the cheatsheet flags as "LangChain executes in a single pass, LangGraph adds loops."

---

## 3. Milestones

### Milestone 1 — Safe DB connection + schema introspection
- Connect to a sandboxed Postgres/SQLite DB (use a **read-only DB user**, non-negotiable)
- Write a `SchemaIntrospector` that pulls table names, columns, types, foreign keys, and sample rows
- Cache schema as a compact text block (token budget matters — don't dump 200 tables raw)

### Milestone 2 — SQL generation with structured output
- `ChatPromptTemplate` with schema + few-shot examples of NL→SQL pairs
- `model.with_structured_output(SQLQuery)` where `SQLQuery` is a Pydantic model with `sql: str`, `reasoning: str`, `tables_used: list[str]`
- Test generation quality against a fixed set of questions before wiring execution

### Milestone 3 — Validation layer (this is the safety-critical part)
- Reject anything that isn't a `SELECT` (regex + `sqlparse` AST check — don't trust regex alone)
- Enforce a `LIMIT` clause (inject one if missing)
- Reject queries referencing tables/columns not in the introspected schema (catches hallucinated columns)
- Optional: a second, cheaper LLM call whose only job is "does this SQL match the user's intent" as a sanity check

### Milestone 4 — Execution + retry loop as a LangGraph
- Build the `StateGraph` from the diagram above
- `add_conditional_edges` on the validator node: valid → execute, invalid → back to generator with error context, capped at e.g. 3 retries → graceful failure message
- Use a `checkpointer` so a multi-turn analyst session ("now filter that by region") retains prior query context per `thread_id`

### Milestone 5 — Result summarization
- Structured output: `{"answer": str, "row_count": int, "sql_used": str, "caveats": list[str]}`
- Always surface the actual SQL used — never hide it, this is a debuggability/trust requirement for a data tool

### Milestone 6 — Wrap as an agent-facing tool (optional but recommended)
- Expose the whole graph as a single tool (`query_database(question: str)`) so you can plug it into a broader `create_agent` later (e.g. a Slack bot that also does other things)

### Milestone 7 — Guardrail middleware + observability
- `HumanInTheLoopMiddleware` gate for queries that touch flagged sensitive tables (e.g. `users`, `payments`)
- LangSmith tracing on from day one — you want to see exactly what SQL was generated per trace when things go wrong

---

## 4. Core safety principles (non-negotiable, given this touches a real DB)

1. **DB user must be read-only at the database level** — never rely on the LLM or your validator as the only line of defense. Defense in depth.
2. **Never string-interpolate the LLM's SQL directly if you can avoid it** — for anything beyond `SELECT`, this doesn't apply here since you're blocking non-SELECT entirely, but always execute through a connection whose privileges are already scoped down.
3. **Always cap result rows** (`LIMIT`) both in the query and again in the execution layer, so a bad query can't return 10M rows.
4. **Log every generated query** — this is your audit trail and your eval dataset for improving prompts later.
5. **Timeout every query execution** — a pathological query shouldn't hang the whole graph.

---

## 5. Suggested stack

| Piece | Library |
|---|---|
| DB toolkit | `langchain-community` SQL utilities (`SQLDatabase` wrapper) or raw `sqlalchemy` |
| SQL parsing/validation | `sqlparse` or `sqlglot` (sqlglot is better for AST-level checks) |
| Orchestration | `langgraph` (`StateGraph`) |
| Structured output | Pydantic models + `with_structured_output` |
| Persistence | `langgraph-checkpoint-sqlite` for local dev, Postgres for prod |
| Observability | LangSmith |

---

## 6. Suggested test/eval set (build this early, not last)

Create ~20 fixed NL questions against your sandbox DB with known-correct SQL and expected row counts. Run this set after every prompt change — this is your regression suite and it'll save you from silently degrading accuracy as you iterate on the prompt.

---

Want me to start writing the actual code — schema introspector + Pydantic models + the LangGraph `StateGraph` skeleton first?