"""Pure-function unit tests for the OP-5.3 cost & latency aggregates.

``cost_metrics`` / ``latency_metrics`` / ``_latency_stats`` are pure
functions in the harness module (D-059). These tests pin their exact
semantics on constructed inputs — unlike
``test_retrieval_harness_shape.py``, which asserts report shape only.

The misattribution test (``test_recorder_no_misattribution_across_calls``)
proves the read-and-consume contract on :class:`RecordingChatClient`:
when a sequence of answer calls mixes a chat-call contour with a
short-circuit contour (``NO_EVIDENCE`` / empty-query /
``PROVIDER_UNAVAILABLE`` — D-035), a previous response's tokens must not
leak onto a later no-chat-call row.
"""

from __future__ import annotations

import pytest

from memory_rag.core.answers import ChatResponse
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.eval.retrieval.harness import (
    CostMetrics,
    LatencyMetrics,
    PerAnswerResult,
    PerQueryResult,
    RecordingChatClient,
    _latency_stats,
    cost_metrics,
    latency_metrics,
)


def _q_row(*, retrieval_latency_ms: float = 0.0) -> PerQueryResult:
    """Build a ``PerQueryResult`` exercising only the latency field."""
    return PerQueryResult(
        query="q",
        community_id="eval-community",
        expected_chunk_ids=(),
        dense_top_k_ids=(),
        sparse_top_k_ids=(),
        fused_top_k_ids=(),
        first_relevant_rank_in_dense=None,
        first_relevant_rank_in_sparse=None,
        first_relevant_rank_in_fused=None,
        reciprocal_rank_in_fused=0.0,
        recall_at_5=0.0,
        recall_at_10=0.0,
        recall_at_20=0.0,
        retrieval_latency_ms=retrieval_latency_ms,
    )


def _a_row(
    *,
    answer_latency_ms: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    fallback: FallbackMode = FallbackMode.NONE,
    answerable: bool = True,
) -> PerAnswerResult:
    """Build a ``PerAnswerResult`` exercising only the cost / latency fields."""
    return PerAnswerResult(
        query="q",
        community_id="eval-community",
        answerable=answerable,
        fallback_mode=fallback.value,
        context_chunk_count=0,
        grounded=True,
        answer_latency_ms=answer_latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


# ----------------------------------------------------------- cost_metrics


def test_cost_metrics_empty_report_is_zero() -> None:
    """Empty input returns a zero-valued ``CostMetrics`` — the empty-report → 0
    contract pinned by the packet."""
    assert cost_metrics([]) == CostMetrics(
        total_prompt_tokens=0,
        total_completion_tokens=0,
        total_tokens=0,
        answer_calls_with_tokens=0,
        mean_total_tokens_per_call=0.0,
    )


def test_cost_metrics_sums_match_total_tokens() -> None:
    rows = [
        _a_row(prompt_tokens=10, completion_tokens=4),
        _a_row(prompt_tokens=20, completion_tokens=8),
    ]
    m = cost_metrics(rows)
    assert m.total_prompt_tokens == 30
    assert m.total_completion_tokens == 12
    assert m.total_tokens == 42
    assert m.total_tokens == m.total_prompt_tokens + m.total_completion_tokens


def test_cost_metrics_mean_excludes_zero_token_rows_from_denominator() -> None:
    """No-chat-call contours record zero tokens by design (D-035): they must
    not pull the per-call mean downward. With three rows carrying
    (10, 20, 0) total tokens, the mean is 30 / 2 = 15.0 over the two
    non-zero rows; ``answer_calls_with_tokens`` is 2, not 3."""
    rows = [
        _a_row(prompt_tokens=10, completion_tokens=0),
        _a_row(prompt_tokens=15, completion_tokens=5),
        _a_row(prompt_tokens=0, completion_tokens=0, fallback=FallbackMode.NO_EVIDENCE),
    ]
    m = cost_metrics(rows)
    assert m.total_tokens == 30
    assert m.answer_calls_with_tokens == 2
    assert m.mean_total_tokens_per_call == pytest.approx(15.0)


def test_cost_metrics_all_zero_token_rows_mean_is_zero() -> None:
    """Div-by-zero guard: when no row recorded tokens (e.g., every call
    short-circuited), the mean is ``0.0`` instead of raising."""
    rows = [
        _a_row(fallback=FallbackMode.NO_EVIDENCE),
        _a_row(fallback=FallbackMode.PROVIDER_UNAVAILABLE, answerable=False),
    ]
    m = cost_metrics(rows)
    assert m.total_tokens == 0
    assert m.answer_calls_with_tokens == 0
    assert m.mean_total_tokens_per_call == 0.0


# -------------------------------------------------------- latency_metrics


def test_latency_metrics_empty_inputs_are_zero() -> None:
    assert latency_metrics([], []) == LatencyMetrics(
        mean_retrieval_ms=0.0,
        p50_retrieval_ms=0.0,
        max_retrieval_ms=0.0,
        mean_answer_ms=0.0,
        p50_answer_ms=0.0,
        max_answer_ms=0.0,
    )


def test_latency_stats_pins_mean_p50_max() -> None:
    """``_latency_stats`` returns ``(mean, p50, max)`` from a fixed list."""
    mean, p50, mx = _latency_stats([10.0, 20.0, 30.0])
    assert mean == pytest.approx(20.0)
    assert p50 == pytest.approx(20.0)
    assert mx == pytest.approx(30.0)


def test_latency_stats_even_length_median_averages_middle_two() -> None:
    """Stdlib ``statistics.median`` averages the two middles on even length."""
    _, p50, _ = _latency_stats([1.0, 2.0, 3.0, 4.0])
    assert p50 == pytest.approx(2.5)


def test_latency_stats_empty_is_all_zero() -> None:
    assert _latency_stats([]) == (0.0, 0.0, 0.0)


def test_latency_metrics_pairs_match_input_rows() -> None:
    q_rows = [_q_row(retrieval_latency_ms=v) for v in (1.0, 3.0, 5.0)]
    a_rows = [_a_row(answer_latency_ms=v) for v in (100.0, 200.0, 300.0)]
    m = latency_metrics(q_rows, a_rows)
    assert m.mean_retrieval_ms == pytest.approx(3.0)
    assert m.p50_retrieval_ms == pytest.approx(3.0)
    assert m.max_retrieval_ms == pytest.approx(5.0)
    assert m.mean_answer_ms == pytest.approx(200.0)
    assert m.p50_answer_ms == pytest.approx(200.0)
    assert m.max_answer_ms == pytest.approx(300.0)


def test_latency_metrics_mixed_empty_halves_dont_crash() -> None:
    """If one half has rows and the other is empty, the empty half reports
    all zeros — useful for unit-tested partial reports."""
    m = latency_metrics([_q_row(retrieval_latency_ms=7.5)], [])
    assert m.mean_retrieval_ms == pytest.approx(7.5)
    assert m.max_retrieval_ms == pytest.approx(7.5)
    assert m.mean_answer_ms == 0.0
    assert m.max_answer_ms == 0.0


# ----------------------------------------------------- RecordingChatClient
#
# The shim is a single-call / single-consumer slot (D-059). The next two
# tests pin that contract; ``test_recorder_no_misattribution_across_calls``
# is the user-required guardrail against token leakage across mixed
# chat-call / no-chat-call contours.


class _FakeChatClient:
    """Minimal ``ChatClient`` Protocol implementation for unit tests.

    Each ``complete`` call returns the next pre-canned ``ChatResponse`` from
    a list — used to simulate distinct provider responses with distinct
    token counts so the recorder's per-call slot semantics are observable.
    """

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    @property
    def model_name(self) -> str:
        return "fake"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        response = self._responses[self._idx]
        self._idx += 1
        return response


def _response(prompt_tokens: int, completion_tokens: int) -> ChatResponse:
    return ChatResponse(
        raw_text="{}",
        model_name="fake",
        token_counts={"prompt": prompt_tokens, "completion": completion_tokens},
        latency_ms=1,
    )


_EMPTY_PROMPT = AnswerPrompt(prompt_version="v1", system_text="", user_text="", cited_chunk_ids=())


def test_recorder_consume_after_complete_returns_response_and_clears() -> None:
    recorder = RecordingChatClient(_FakeChatClient([_response(10, 3)]))
    # No call yet → slot empty.
    assert recorder.consume_last() is None
    # One complete() → slot holds the response.
    response = recorder.complete(_EMPTY_PROMPT)
    assert response.token_counts == {"prompt": 10, "completion": 3}
    captured = recorder.consume_last()
    assert captured is response
    # Second consume after one complete → slot is empty again.
    assert recorder.consume_last() is None


def test_recorder_no_misattribution_across_calls() -> None:
    """The contract that makes the per-row tokens safe across mixed contours.

    Setup: two answer-path "calls". The first invokes the chat client and
    is consumed by the harness; the second simulates a short-circuit
    contour (``NO_EVIDENCE`` / empty-query / ``PROVIDER_UNAVAILABLE``)
    that does **not** invoke the chat client. The recorder must return
    ``None`` on the second consume — the first response's tokens must not
    leak onto the second row.
    """
    recorder = RecordingChatClient(_FakeChatClient([_response(17, 4), _response(99, 99)]))

    # First "answer call" — chat is invoked.
    recorder.complete(_EMPTY_PROMPT)
    first = recorder.consume_last()
    assert first is not None
    assert first.token_counts == {"prompt": 17, "completion": 4}

    # Second "answer call" — short-circuits, chat client NOT invoked.
    # The recorder's slot is empty (cleared by the prior consume), so the
    # harness sees ``None`` and the row gets zero tokens.
    second = recorder.consume_last()
    assert second is None

    # Sanity: the fake client's next pre-canned response is still queued; the
    # recorder's slot is only ever set when ``complete`` is actually called.
    recorder.complete(_EMPTY_PROMPT)
    third = recorder.consume_last()
    assert third is not None
    assert third.token_counts == {"prompt": 99, "completion": 99}
