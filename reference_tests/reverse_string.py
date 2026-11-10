from solution import reverse_string

def test_word():
    assert reverse_string("abc") == "cba"

def test_empty():
    assert reverse_string("") == ""

def test_single():
    assert reverse_string("a") == "a"

def test_spaces():
    assert reverse_string("a b") == "b a"
