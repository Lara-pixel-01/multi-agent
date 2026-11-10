# Lessons from earlier runs
- A function that sorted or edited its input in place failed the "input not changed" test twice. Copy the input first, for example with sorted() or a list copy.
- Intervals that touch, such as [1, 2] and [2, 3], must merge. Intervals with a gap, such as [0, 2] and [3, 6], must not merge.
- A self-written test once expected a wrong merge result. Check expected values by hand before trusting them.
- Test files that use pytest decorators without importing pytest crash before any test runs. Use plain asserts inside test_ functions.
- Top-level assert statements outside a test function crash during collection. Put them inside functions.
- Rule: Generated files must contain only valid Python: close every quote and bracket, and leave out markdown fences and divider lines such as ---.
- Rule: Check the function's output against each expected value and every rule in the task.
- Rule: Follow the file format exactly: two files, each starting with a 'FILE: name.py' line.
- Rule: Put every assert inside a function whose name starts with test_.

- Rule: Read the full test error and fix its cause before changing anything else.
