from solution import rotate_matrix

def test_square():
    assert rotate_matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [[7, 4, 1], [8, 5, 2], [9, 6, 3]]

def test_wide_rectangle():
    assert rotate_matrix([[1, 2, 3, 4], [5, 6, 7, 8]]) == [[5, 1], [6, 2], [7, 3], [8, 4]]

def test_single_cell():
    assert rotate_matrix([[9]]) == [[9]]

def test_empty():
    assert rotate_matrix([]) == []

def test_input_not_changed():
    grid = [[1, 2], [3, 4]]
    rotate_matrix(grid)
    assert grid == [[1, 2], [3, 4]]