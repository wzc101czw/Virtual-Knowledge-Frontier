# Release Notes — VKF Storage Core 0.1.0

## Scope

Production-style **storage prototype** only. No LLM, network service, GUI, semantic embeddings, or automatic discovery.

## Delivered

- Transactional local SQLite repository, schema v2 with v1 migration and pre-migration backups.
- Five cognitive-object kinds, object revisions, audit history, restore-as-new-revision.
- Question lifecycle with answer verification, typed semantic relations, two-source CrossInsight constraints.
- Conversation/message storage, idempotent normalized JSON import, candidate staging and review.
- Literal Chinese+English substring search, 1–2 hop graph, manual Frontier suggestions and decisions.
- Health check, safe backup and restore into a new path, readable snapshot export.
- JSON CLI, programmatic API, deterministic sample/demo, feedback questionnaire.

## Important limitations

1. Model-driven extraction is **not yet implemented**; candidates are simulated by explicit CLI calls.
2. FTS5 Trigram is substring retrieval, **not semantic embedding or RAG**.
3. `export-json` cannot be used with `import-json` to restore the entire VKF DB. Use backup/restore-db.
4. Personal content is stored in **unencrypted** local files; control OS permissions and backups.
5. The candidate relation JSON field is reserved for a future controlled relation-approval workflow.
6. All formal graph modifications are user-triggered; there is no autonomous agent writing.

## References

- SQLite official documentation: https://www.sqlite.org/fts5.html
- Python sqlite3 backup and transaction guidance: https://docs.python.org/3/library/sqlite3.html

## Test command

`python -m unittest discover -s tests -v`
