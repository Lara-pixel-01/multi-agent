from solution import top_k_frequent

def test_basic():
    assert top_k_frequent(["a", "b", "a", "c", "b", "a"], 2) == ["a", "b"]

def test_tie_alphabetical():
    assert top_k_frequent(["b", "a", "b", "a", "c"], 2) == ["a", "b"]

def test_k_too_large():
    assert top_k_frequent(["x", "y"], 5) == ["x", "y"]

def test_empty():
    assert top_k_frequent([], 3) == []

def test_k_zero():
    assert top_k_frequent(["a"], 0) == []

def test_input_not_changed():
    words = ["b", "a", "b"]
    top_k_frequent(words, 1)
    assert words == ["b", "a", "b"]
