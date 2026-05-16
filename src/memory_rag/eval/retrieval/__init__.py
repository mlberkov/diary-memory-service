"""Retrieval-quality inspection harness against the D-025 baseline (D-038).

Two modes share one metric shape:

- ``mock`` — offline, deterministic, runs under ``make check`` as a
  pure-shape sanity check; no quality thresholds.
- ``postgres`` — operator-run, env-gated by ``MEMORY_RAG_PG_TEST_DSN``,
  exercises the real ``SearchRepository`` legs (Postgres dense exact-scan
  + FTS ``simple``) plus service-layer RRF.

Inspection, not gate. See ``docs/RUNBOOK.md`` "Retrieval-quality
inspection harness (D-038)" and ``docs/decision-log.md`` D-038.
"""
