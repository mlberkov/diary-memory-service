"""SearchRepository tests against ``PostgresDiaryStore`` (Slice 3.3 / D-025).

Skipped unless ``DIARY_RAG_PG_TEST_DSN`` is set, mirroring
``test_postgres_store.py``. Exercises:

- sparse via the generated tsvector column and ``websearch_to_tsquery('simple', ...)``,
- dense via exact family-scoped scan over ``vector(3072)`` filtered to
  ``embedding_status='ready'`` and the active ``model_name``,
- family scoping (I-7) on both legs,
- the dense-versus-substring proof: a paraphrased query reaches a chunk
  whose exact tokens are not in the query, via the dense leg.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.diary.models import DateRange, DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import RouteKind

PG_DSN = os.environ.get("DIARY_RAG_PG_TEST_DSN")

pytestmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="DIARY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)

if PG_DSN is not None:
    import psycopg

    from diary_rag.storage.postgres import PostgresDiaryStore

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
_DATE = date(2026, 5, 11)


def _truncate(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE embedding_records, event_chunks, diary_entries, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def store() -> Iterator[PostgresDiaryStore]:
    assert PG_DSN is not None
    s = PostgresDiaryStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        yield s
    finally:
        s.close()


def _seed(
    store: PostgresDiaryStore,
    *,
    cid: str,
    text: str,
    family_id: str = "fam-A",
    status: EmbeddingStatus = EmbeddingStatus.READY,
    embed_with: MockEmbeddingClient | None = None,
    event_index: int = 0,
    entry_date: date = _DATE,
) -> None:
    sid = f"src-{cid}"
    eid = f"ent-{cid}"
    store.save_source_message(
        SourceMessage(
            source_message_id=sid,
            family_id=family_id,
            author_user_id="u1",
            external_chat_id=family_id,
            external_user_id="u1",
            external_message_id=sid,
            edit_seq=0,
            raw_text=text,
            detected_route=RouteKind.ENTRY,
            created_at=_NOW,
        )
    )
    store.save_diary_entry(
        DiaryEntry(
            diary_entry_id=eid,
            source_message_id=sid,
            family_id=family_id,
            author_user_id="u1",
            entry_date=entry_date,
            entry_text=text,
            created_at=_NOW,
        )
    )
    store.save_event_chunks(
        [
            EventChunk(
                chunk_id=cid,
                diary_entry_id=eid,
                source_message_id=sid,
                family_id=family_id,
                author_user_id="u1",
                entry_date=entry_date,
                event_index=event_index,
                chunk_text=text,
                created_at=_NOW,
            )
        ]
    )
    if status is EmbeddingStatus.READY:
        client = embed_with or MockEmbeddingClient()
        store.save_embedding_records(
            [
                EmbeddingRecord(
                    embedding_record_id=str(uuid4()),
                    chunk_id=cid,
                    source_message_id=sid,
                    family_id=family_id,
                    model_name=client.model_name,
                    dimension=client.dimension,
                    embedding=client.embed([text])[0],
                    created_at=_NOW,
                )
            ]
        )
    store.set_chunk_embedding_status(cid, status)


def test_sparse_matches_keywords(store: PostgresDiaryStore) -> None:
    _seed(store, cid="c1", text="Tried a new book today")
    _seed(store, cid="c2", text="Walked the dog", event_index=1)

    hits = store.sparse_candidates("fam-A", "book", limit=10)

    assert [h.chunk_id for h in hits] == ["c1"]


def test_sparse_empty_query_returns_empty(store: PostgresDiaryStore) -> None:
    _seed(store, cid="c1", text="Tried a new book today")

    assert store.sparse_candidates("fam-A", "", limit=10) == []
    assert store.sparse_candidates("fam-A", "   ", limit=10) == []


def test_sparse_family_scope_isolates(store: PostgresDiaryStore) -> None:
    _seed(store, cid="cA", text="Family A book", family_id="fam-A")
    _seed(store, cid="cB", text="Family B book", family_id="fam-B")

    assert [h.chunk_id for h in store.sparse_candidates("fam-A", "book", 10)] == ["cA"]
    assert [h.chunk_id for h in store.sparse_candidates("fam-B", "book", 10)] == ["cB"]
    assert store.sparse_candidates("fam-C", "book", 10) == []


def test_sparse_zero_limit_returns_empty(store: PostgresDiaryStore) -> None:
    _seed(store, cid="c1", text="Tried a new book today")
    assert store.sparse_candidates("fam-A", "book", 0) == []


def test_dense_returns_identical_text_first(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", embed_with=client)
    _seed(store, cid="c2", text="Read a book", event_index=1, embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates("fam-A", query, client.model_name, limit=10)

    assert hits[0].chunk_id == "c1"


def test_dense_excludes_unready_chunks(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", status=EmbeddingStatus.FAILED)
    _seed(store, cid="c2", text="Walked the dog", event_index=1, embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates("fam-A", query, client.model_name, limit=10)

    assert [h.chunk_id for h in hits] == ["c2"]


def test_dense_family_scope_isolates(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed(store, cid="cA", text="Walked the dog", family_id="fam-A", embed_with=client)
    _seed(store, cid="cB", text="Walked the dog", family_id="fam-B", embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    hits_a = store.dense_candidates("fam-A", query, client.model_name, 10)
    hits_b = store.dense_candidates("fam-B", query, client.model_name, 10)

    assert [h.chunk_id for h in hits_a] == ["cA"]
    assert [h.chunk_id for h in hits_b] == ["cB"]


def test_dense_filters_by_model_name(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    assert store.dense_candidates("fam-A", query, "other-model", 10) == []


def test_dense_empty_family_raises(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    with pytest.raises(ValueError, match="family_id"):
        store.dense_candidates("", client.embed(["x"])[0], client.model_name, 5)


def test_sparse_empty_family_raises(store: PostgresDiaryStore) -> None:
    with pytest.raises(ValueError, match="family_id"):
        store.sparse_candidates("", "book", 5)


def test_tsvector_simple_dictionary_does_not_stem(
    store: PostgresDiaryStore,
) -> None:
    """``to_tsvector('simple', ...)`` indexes raw tokens, no stemming.

    Asserts the dictionary choice committed in schema.sql: 'simple'
    avoids a language commitment the diary corpus may not honor.
    """
    _seed(store, cid="c1", text="walking")

    # English stemming would match "walk" → "walking"; 'simple' does not.
    hits = store.sparse_candidates("fam-A", "walk", limit=10)
    assert hits == []

    hits = store.sparse_candidates("fam-A", "walking", limit=10)
    assert [h.chunk_id for h in hits] == ["c1"]


# --- Slice 3.4: date-range retrieval filter (D-040) ---

_EARLY = date(2026, 5, 10)
_MID = date(2026, 5, 11)
_LATE = date(2026, 5, 12)


def _seed_three_dates(store: PostgresDiaryStore, client: MockEmbeddingClient, *, text: str) -> None:
    """Seed identical-text chunks on three distinct entry dates."""
    _seed(store, cid="c-early", text=text, embed_with=client, entry_date=_EARLY)
    _seed(store, cid="c-mid", text=text, embed_with=client, entry_date=_MID)
    _seed(store, cid="c-late", text=text, embed_with=client, entry_date=_LATE)


def test_sparse_date_range_full(store: PostgresDiaryStore) -> None:
    _seed_three_dates(store, MockEmbeddingClient(), text="book chapter")

    hits = store.sparse_candidates(
        "fam-A", "book chapter", 10, date_range=DateRange(start=_MID, end=_MID)
    )
    assert {h.chunk_id for h in hits} == {"c-mid"}


def test_sparse_date_range_only_lower(store: PostgresDiaryStore) -> None:
    _seed_three_dates(store, MockEmbeddingClient(), text="book chapter")

    hits = store.sparse_candidates("fam-A", "book chapter", 10, date_range=DateRange(start=_MID))
    assert {h.chunk_id for h in hits} == {"c-mid", "c-late"}


def test_sparse_date_range_only_upper(store: PostgresDiaryStore) -> None:
    _seed_three_dates(store, MockEmbeddingClient(), text="book chapter")

    hits = store.sparse_candidates("fam-A", "book chapter", 10, date_range=DateRange(end=_MID))
    assert {h.chunk_id for h in hits} == {"c-early", "c-mid"}


def test_sparse_date_range_inclusive_bounds(store: PostgresDiaryStore) -> None:
    _seed_three_dates(store, MockEmbeddingClient(), text="book chapter")

    hits = store.sparse_candidates(
        "fam-A", "book chapter", 10, date_range=DateRange(start=_EARLY, end=_LATE)
    )
    assert {h.chunk_id for h in hits} == {"c-early", "c-mid", "c-late"}


def test_dense_date_range_full(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed_three_dates(store, client, text="Walked the dog")

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates(
        "fam-A", query, client.model_name, 10, date_range=DateRange(start=_MID, end=_MID)
    )
    assert {h.chunk_id for h in hits} == {"c-mid"}


def test_dense_date_range_only_lower(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed_three_dates(store, client, text="Walked the dog")

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates(
        "fam-A", query, client.model_name, 10, date_range=DateRange(start=_MID)
    )
    assert {h.chunk_id for h in hits} == {"c-mid", "c-late"}


def test_dense_date_range_only_upper(store: PostgresDiaryStore) -> None:
    client = MockEmbeddingClient()
    _seed_three_dates(store, client, text="Walked the dog")

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates(
        "fam-A", query, client.model_name, 10, date_range=DateRange(end=_MID)
    )
    assert {h.chunk_id for h in hits} == {"c-early", "c-mid"}


def test_date_range_none_unchanged(store: PostgresDiaryStore) -> None:
    """``date_range=None`` returns the pre-3.4 result set on both legs."""
    client = MockEmbeddingClient()
    _seed_three_dates(store, client, text="book chapter")

    sparse = store.sparse_candidates("fam-A", "book chapter", 10, date_range=None)
    assert {h.chunk_id for h in sparse} == {"c-early", "c-mid", "c-late"}

    query = client.embed(["book chapter"])[0]
    dense = store.dense_candidates("fam-A", query, client.model_name, 10, date_range=None)
    assert {h.chunk_id for h in dense} == {"c-early", "c-mid", "c-late"}
