from controle_paie.performance_final_app import PayrollAppWithPerformanceFinal


def test_history_bounds_empty():
    page, total_pages, offset = PayrollAppWithPerformanceFinal._history_bounds(0, 1, 100)
    assert page == 1
    assert total_pages == 1
    assert offset == 0


def test_history_bounds_middle_page():
    page, total_pages, offset = PayrollAppWithPerformanceFinal._history_bounds(250, 2, 100)
    assert page == 2
    assert total_pages == 3
    assert offset == 100


def test_history_bounds_clamps_page_and_size():
    page, total_pages, offset = PayrollAppWithPerformanceFinal._history_bounds(1200, 99, 1000)
    assert page == 3
    assert total_pages == 3
    assert offset == 1000
