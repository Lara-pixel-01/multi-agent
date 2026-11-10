TASKS = [
    {"name": "is_even", "difficulty": "SIMPLE",
     "task": "Write a function is_even(n) that returns True if the integer n is even, otherwise False."},
    {"name": "reverse_string", "difficulty": "SIMPLE",
     "task": "Write a function reverse_string(s) that returns the string reversed."},
    {"name": "count_vowels", "difficulty": "SIMPLE",
     "task": "Write a function count_vowels(s) that returns how many vowels (a, e, i, o, u, in upper or lower case) are in the string s."},
    {"name": "clamp", "difficulty": "SIMPLE",
     "task": "Write a function clamp(value, low, high) that returns value limited to the range from low to high. If value is below low return low, if it is above high return high."},
    {"name": "roman_to_int", "difficulty": "HARD",
     "task": "Write a function roman_to_int(s) that converts a Roman numeral string such as MCMXCIV to an integer. Handle subtractive pairs such as IV and IX."},
    {"name": "merge_intervals", "difficulty": "HARD",
     "task": "Write a function merge_intervals(intervals) that takes a list of [start, end] pairs and returns the merged list sorted by start. Overlapping intervals merge. Touching intervals such as [1, 2] and [2, 3] also merge. Do not change the input list. An empty input returns an empty list."},
    {"name": "rotate_matrix", "difficulty": "HARD",
     "task": "Write a function rotate_matrix(grid) that rotates a 2D list of numbers 90 degrees clockwise and returns a new list. The grid may be rectangular, not only square. An empty grid returns an empty list. Do not change the input grid."},
    {"name": "is_balanced", "difficulty": "HARD",
     "task": "Write a function is_balanced(s) that returns True if the brackets (), [] and {} in the string s are balanced and correctly nested, otherwise False. Ignore all other characters. An empty string is balanced."},
    {"name": "top_k_frequent", "difficulty": "HARD",
     "task": "Write a function top_k_frequent(words, k) that returns a list of the k most frequent words. Sort by count from highest to lowest and break ties alphabetically. If k is larger than the number of distinct words, return all of them. Do not change the input list."},
    {"name": "find_pair", "difficulty": "HARD",
     "task": "Write a function find_pair(nums, target) that returns the pair [i, j] with i < j where nums[i] + nums[j] == target. If several pairs work, return the one with the smallest i, and for that i the smallest j. If no pair works, return None."},
]

for t in TASKS:
    t["ref"] = f"reference_tests/{t['name']}.py"
