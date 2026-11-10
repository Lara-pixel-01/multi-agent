from solution import find_pair

def test_basic():
    assert find_pair([2, 7, 11, 15], 9) == [0, 1]

def test_not_first_elements():
    assert find_pair([3, 2, 4], 6) == [1, 2]

def test_smallest_i_then_j():
    assert find_pair([1, 5, 1, 5], 6) == [0, 1]

def test_no_pair():
    assert find_pair([1, 2, 3], 10) is None

def test_empty():
    assert find_pair([], 1) is None

def test_same_values():
    assert find_pair([3, 3], 6) == [0, 1]

def test_negatives():
    assert find_pair([-1, -2, -3, -4, -5], -8) == [2, 4]

def test_smallest_i_wins_over_earliest_finish():
    assert find_pair([1, 2, 4, 5], 6) == [0, 3]
