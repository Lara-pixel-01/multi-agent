from solution import roman_to_int

def test_simple():
    assert roman_to_int("III") == 3

def test_subtractive():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9

def test_mixed():
    assert roman_to_int("LVIII") == 58

def test_long():
    assert roman_to_int("MCMXCIV") == 1994