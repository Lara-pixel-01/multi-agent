---
name: write-tests
description: Use when writing test_solution.py for a Python function. Gives the rules for plain-assert tests and the edge cases to cover.
---
# Skill: write tests

## When to use
Whenever the coder must write test_solution.py.

## Steps
1. Start the file with `from solution import <function name>`.
2. Write one function per case, named test_<what it checks>.
3. Use plain assert statements. Do not import pytest.
4. Cover a normal case, an empty input, a single item, and one tricky edge case from the task.
5. Work out each expected value by hand before writing it.

## Example
from solution import is_even

def test_even():
    assert is_even(4) is True

def test_zero():
    assert is_even(0) is True