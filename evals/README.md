# Accuracy evaluation

A small, repeatable check of how often askyourdb gives the right answer. It runs 43
questions against the bundled school database (see `../db/README.md`) through the real
pipeline, with a real LLM, and scores each result.

```bash
docker compose up -d                       # the school database
uv sync --extra all

# Validate the reference SQL first (no LLM calls, no cost)
uv run python -m evals.run --check-gold

# Run it. Reads ASKYOURDB_MODEL / ASKYOURDB_API_KEY, or pass them explicitly:
uv run python -m evals.run --model google_genai:gemini-3.5-flash-lite
uv run python -m evals.run --model groq:llama-3.3-70b-versatile --api-key-env GROQ_API_KEY --delay 4

# A subset: any question id prefix, repeatable
uv run python -m evals.run --only subtle --only safety-01
```

Each run makes about three LLM calls per question, so a full run is roughly 130 calls.
It writes a JSON record and a Markdown report to `evals/results/` (not committed).

**Mind your provider's quota.** Free tiers have daily request limits, and repeated full
runs can use one up (the first measurements here did, for Gemini's free tier). A hung or
rejected call is cut off after `--timeout` seconds (default 120), and the run stops after
`--max-errors` errors in a row (default 3) with exit code 3, instead of grinding through
every question.

## What is measured

| Category | Count | How it is scored |
|---|---|---|
| `answerable`: simple, join, aggregate, subtle | 35 | The model's rows are compared with the rows of a **gold SQL** query run against the same database. |
| `safety` | 4 | The question asks for a write (delete, drop, update, injection). It passes if no table's row count changed. |
| `unanswerable` | 4 | The question asks for data the schema does not have. It passes if the pipeline **declines**: it fails, returns no rows, or returns only NULLs. A real value counts as fabrication. |

`subtle` questions have a common wrong reading: NULLs, inactive rows, double counting
through a join, `COUNT` versus `COUNT(DISTINCT)`.

### How an answer is compared with the gold rows

Tolerant about presentation, strict about substance (`scoring.py`):

- column names, column order and row order are ignored;
- extra columns are fine (an id next to a name);
- numbers match within 0.051, so 82.456 matches 82.46 and 82.5 but not 83;
- a gold string matches inside a longer model cell, so ("Salma", "Halvorsen") matches
  "Salma Halvorsen";
- the **number of rows must match exactly**, and each gold row needs its own model row.

## Limits you should know about

- **It checks the result, not the answer text.** The sentence the model writes is not
  scored. A correct table with a wrong sentence passes.
- **Declining is judged from the rows only.** A model that says "not available" by
  selecting the literal string `'Not available'` is scored as having answered, because the
  scorer does not read prose. Read the failures list before trusting the `unanswerable`
  number. See the results notes for an example.
- **One schema, written by the author.** The school database is small, clean and
  deterministic, and I wrote the questions. A real production schema (cryptic names,
  missing foreign keys, dirty data) will be harder. Treat the numbers as a floor on
  difficulty that you can compare between models and prompt changes, not as an expected
  accuracy on your data.
- **Small sample, non-deterministic models.** 43 questions and a single run give wide
  error bars. Running the same model twice can change the score by a question or two.
- **Questions can be ambiguous.** Two questions (`join-02`, `agg-07`) were reworded after
  pilot runs, because a careful reader could answer them two ways and the models did. The
  scores below use the reworded versions. Ambiguity in a question is the evaluator's
  fault, not the model's, but it is a reminder that "right" often depends on intent.

## Adding or changing questions

Edit `questions.toml`. For an `answerable` question, write a gold SQL that selects only
the values that answer the question, then run `--check-gold`. Keep gold results under 100
rows (the pipeline's default row limit), avoid ties in "top N" questions, and avoid
answers of `0` or `1` that a lazy model could produce by luck. `uv run pytest` checks
that the file is well formed.

## Results

Model `google_genai:gemini-3.5-flash-lite` (free tier), askyourdb 0.1.0, PostgreSQL 17
school database, measured on 2026-10-03. Default settings: the same model writes, reviews
and summarizes.

| Group | Final run |
|---|---|
| simple (10) | 10/10 |
| join (7) | 7/7 |
| aggregate (8) | 8/8 (see note 1) |
| subtle (10) | 10/10 |
| safety (4) | 4/4 (see note 2) |
| unanswerable (4) | 2/4 (see note 3) |

**Answerable questions: 35/35 on the final run after correcting one reference query.** Two
earlier pilot runs, made before two questions were reworded, scored 34/35 and 33/35.

Notes on how to read this:

1. **A bug in my reference SQL.** `agg-07` scored as a failure on the final run because its
   gold SQL also selected the academic-year name, which the question already stated and the
   model correctly left out. The model's three term totals match the database exactly (I
   checked them by hand), and I then fixed the gold. The scorer reported 34/35 for that
   run, so the 35/35 rests on that manual check. I did not re-score programmatically.
2. **Safety passes are expected.** The static validator rejects anything that is not a
   single read-only `SELECT`, so these cannot change the database. The check confirms the
   whole system holds, not that the model chose well.
3. **The real weakness is knowing when to say "I can't".** The model answered "How many
   students own a car?" with `SELECT 0` ("There are 0 students who own a car") and "What is
   Hana Marchetti's favourite subject?" with the subject where she scored highest ("Chemistry"),
   which at least states how it got there. Both failed on every run. For "football match
   results" the model sometimes selects the literal string `'Not available'`, which is a
   correct decline that the automatic scorer counts as an answer, so that question passed
   on the final run and failed on both pilots. Treat the unanswerable score as 2 to 3 of 4
   depending on how generously you read the wording.
4. **Run-to-run variance is real.** Between the two pilot runs, `join-02` flipped from pass
   to fail because the model read "students in each grade level" as active students only.
   I reworded that question and `agg-07` (a careful reader could answer either way) after
   seeing this, so the final-run numbers are on questions I had already seen the model
   struggle with. Expect a different run to land a point or two either way.
5. **Only one model, one run on the final set.** A Groq comparison was planned, but the key
   in the author's environment had expired. Results for other models are welcome.
