import pytest

from controle_paie.cancellation import CancellationToken, TaskCancelledError
from controle_paie.performance_continuation_app import PayrollAppWithPerformanceContinuation


def test_cancellation_token_is_cooperative():
    token = CancellationToken()
    token.raise_if_cancelled()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(TaskCancelledError):
        token.raise_if_cancelled()


def test_page_bounds_clamps_page_and_size():
    page, size, pages, offset = PayrollAppWithPerformanceContinuation._page_bounds(1201, 99, 250)
    assert page == 5
    assert size == 250
    assert pages == 5
    assert offset == 1000


def test_page_bounds_empty_result_has_one_page():
    page, size, pages, offset = PayrollAppWithPerformanceContinuation._page_bounds(0, 3, 10)
    assert page == 1
    assert size == 25
    assert pages == 1
    assert offset == 0
