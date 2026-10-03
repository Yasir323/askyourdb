# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/Yasir323/askyourdb/security/advisories/new)
on this repository. Include the version, what you did, and what you expected to happen.
You can expect an acknowledgement within a few days.

## Supported versions

Only the latest released version receives fixes.

## What to know before you use askyourdb

askyourdb sends your question and your database schema to the LLM provider you configure,
and runs the SQL the model writes. Treat it accordingly:

- **Use a read-only database account.** The static validator accepts a single read-only
  statement and enforces a row limit, but it is a safety net and not a security boundary.
  The database account's permissions are the real boundary.
- **Limit what the account can see.** Grant access only to the tables and columns you are
  comfortable sending to a third-party model. Query results and the schema leave your
  machine.
- **Protect your keys.** Keep API keys and DSNs in environment variables or a local config
  file that is not committed. `.env` and `askyourdb.toml` are in `.gitignore` for this reason.
- **Review the SQL.** The tool always prints the SQL it ran. Read it before you act on an
  answer, since models can be wrong.

Reports about bypassing the validator (running a write, multiple statements, or reading
past the row limit) are in scope and especially welcome.
