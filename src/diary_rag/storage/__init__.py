"""Storage layer.

PostgreSQL is the durable system of record (Invariant I-2). The `mock`
subpackage provides in-memory stand-ins so Phase 1 slices can run
end-to-end without a database.
"""
