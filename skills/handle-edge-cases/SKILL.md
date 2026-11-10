---
name: handle-edge-cases
description: Use when a task works on lists, strings, or numbers. A checklist of inputs that often break solutions.
---
# Skill: handle edge cases

## When to use
Before writing any function that takes a list, a string, or numbers.

## Checklist
- Empty input (empty list, empty string).
- One item only.
- Repeated items.
- Negative numbers and zero.
- The input must not be changed: work on a copy.
- Return a new object, not the same one.

## Rule
If the task says what to return for an edge case, follow it exactly.