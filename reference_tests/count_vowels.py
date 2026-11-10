from solution import count_vowels

def test_lowercase():
    assert count_vowels("hello") == 2

def test_uppercase():
    assert count_vowels("AEIOU") == 5

def test_empty():
    assert count_vowels("") == 0

def test_no_vowels():
    assert count_vowels("rhythm") == 0

def test_mixed():
    assert count_vowels("Programming") == 3

def test_repeated_vowels():
    assert count_vowels("banana") == 3
