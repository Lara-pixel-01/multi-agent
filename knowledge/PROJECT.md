# Project conventions
- Language: Python 3.12, standard library only.
- Files: solution.py holds the function, test_solution.py holds the tests.
- Tests: plain assert statements inside functions named test_something. No pytest imports.
- Every test file covers a normal case, an empty input, a single item, and one tricky edge case.
- The sandbox runs the tests with pytest, offline, with 512 MB of memory.
- A task passes only when every test passes.