from solution import is_balanced

def test_simple_pair():
    assert is_balanced("()") is True

def test_nested():
    assert is_balanced("([]{})") is True

def test_wrong_type():
    assert is_balanced("(]") is False

def test_wrong_order():
    assert is_balanced("([)]") is False

def test_empty():
    assert is_balanced("") is True

def test_unclosed():
    assert is_balanced("((") is False

def test_other_characters():
    assert is_balanced("a(b)c") is True

def test_only_closing():
    assert is_balanced("}") is False
