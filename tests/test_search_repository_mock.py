"""SearchRepository tests against ``MockDiaryStore`` (Slice 3.3 / D-025).

Mock semantics:

- ``sparse_candidates`` ranks by lowercased whitespace token overlap.
- ``dense_candidates`` ranks by cosine distance over the deterministic
  ``MockEmbeddingClient`` vectors, but only chunks whose text is
  effectively identical to the query qualify (distance threshold 0.5).
  See ``storage.mock.store`` for the rationale.

Both legs respect family scope (I-7) and only return chunks in
``ready`` state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import RouteKind
from diary_rag.storage.mock import MockDiaryStore

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
_DATE = date(2026, 5, 11)


def _seed(
    store: MockDiaryStore,
    *,
    cid: str,
    text: str,
    family_id: str = "fam-A",
    status: EmbeddingStatus = EmbeddingStatus.READY,
    embed_with: MockEmbeddingClient | None = None,
) -> EventChunk:
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
            entry_date=_DATE,
            entry_text=text,
            created_at=_NOW,
        )
    )
    chunk = EventChunk(
        chunk_id=cid,
        diary_entry_id=eid,
        source_message_id=sid,
        family_id=family_id,
        author_user_id="u1",
        entry_date=_DATE,
        event_index=0,
        chunk_text=text,
        created_at=_NOW,
    )
    store.save_event_chunks([chunk])

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
    return chunk


def test_sparse_orders_by_token_overlap() -> None:
    store = MockDiaryStore()
    _seed(store, cid="c1", text="Tried a new book today")
    _seed(store, cid="c2", text="Read another novel chapter")
    _seed(store, cid="c3", text="Walked the dog")

    hits = store.sparse_candidates("fam-A", "book chapter", limit=10)

    assert [h.chunk_id for h in hits[:2]] == ["c1", "c2"]
    assert "c3" not in {h.chunk_id for h in hits}


def test_sparse_returns_empty_for_disjoint_query() -> None:
    store = MockDiaryStore()
    _seed(store, cid="c1", text="Walked the dog")

    assert store.sparse_candidates("fam-A", "snowstorm", limit=10) == []


def test_sparse_family_scope_isolates() -> None:
    store = MockDiaryStore()
    _seed(store, cid="cA", text="Family A book", family_id="fam-A")
    _seed(store, cid="cB", text="Family B book", family_id="fam-B")

    assert [h.chunk_id for h in store.sparse_candidates("fam-A", "book", 10)] == ["cA"]
    assert [h.chunk_id for h in store.sparse_candidates("fam-B", "book", 10)] == ["cB"]
    assert store.sparse_candidates("fam-C", "book", 10) == []


def test_sparse_skips_non_ready_chunks_is_not_required() -> None:
    """Sparse is text-only, so it ignores embedding status (matches Postgres FTS)."""
    store = MockDiaryStore()
    _seed(store, cid="c1", text="Tried a new book", status=EmbeddingStatus.PENDING)

    hits = store.sparse_candidates("fam-A", "book", 10)
    assert [h.chunk_id for h in hits] == ["c1"]


def test_dense_matches_only_identical_text() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", embed_with=client)
    _seed(store, cid="c2", text="Read a book", embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    hits = store.dense_candidates("fam-A", query, client.model_name, limit=10)

    assert [h.chunk_id for h in hits] == ["c1"]


def test_dense_excludes_unready_chunks() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", status=EmbeddingStatus.FAILED)

    query = client.embed(["Walked the dog"])[0]
    assert store.dense_candidates("fam-A", query, client.model_name, 10) == []


def test_dense_family_scope_isolates() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    _seed(store, cid="cA", text="Walked the dog", family_id="fam-A", embed_with=client)
    _seed(store, cid="cB", text="Walked the dog", family_id="fam-B", embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    hits_a = store.dense_candidates("fam-A", query, client.model_name, 10)
    hits_b = store.dense_candidates("fam-B", query, client.model_name, 10)

    assert [h.chunk_id for h in hits_a] == ["cA"]
    assert [h.chunk_id for h in hits_b] == ["cB"]


def test_dense_uses_model_name_filter() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    _seed(store, cid="c1", text="Walked the dog", embed_with=client)

    query = client.embed(["Walked the dog"])[0]
    assert store.dense_candidates("fam-A", query, "other-model", 10) == []


def test_both_legs_require_family_id() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()

    with pytest.raises(ValueError, match="family_id"):
        store.dense_candidates("", client.embed(["x"])[0], client.model_name, 5)
    with pytest.raises(ValueError, match="family_id"):
        store.sparse_candidates("", "x", 5)


def test_both_legs_clamp_on_limit() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    for i in range(5):
        _seed(store, cid=f"c{i}", text=f"keyword {i}", embed_with=client)

    sparse = store.sparse_candidates("fam-A", "keyword", limit=3)
    assert len(sparse) == 3

    dense = store.dense_candidates("fam-A", client.embed(["keyword 2"])[0], client.model_name, 3)
    assert len(dense) <= 3
