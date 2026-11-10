from solution import merge_intervals

def test_unsorted_input():
    assert merge_intervals([[3, 6], [0, 2], [4, 5]]) == [[0, 2], [3, 6]]

def test_overlapping():
    assert merge_intervals([[1, 3], [2, 4], [5, 6]]) == [[1, 4], [5, 6]]

def test_touching():
    assert merge_intervals([[1, 2], [2, 3]]) == [[1, 3]]

def test_nested():
    assert merge_intervals([[1, 10], [2, 3], [4, 5]]) == [[1, 10]]

def test_empty():
    assert merge_intervals([]) == []

def test_input_not_changed():
    data = [[5, 6], [1, 3], [2, 4]]
    original = [[5, 6], [1, 3], [2, 4]]
    merge_intervals(data)
    assert data == original