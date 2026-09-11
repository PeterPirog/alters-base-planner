from pathlib import Path

from alters_base_planner.base import _read_grid_csv, builtin_base, load_base_csv


def test_builtin_tiers_are_loaded_from_separate_csv_files() -> None:
    expected = {
        1: (22, 12, "base-size1.csv"),
        2: (26, 14, "base-size2.csv"),
        3: (30, 16, "base-size3.csv"),
        4: (34, 18, "base-size4.csv"),
    }
    for tier, (width, height, source) in expected.items():
        base = builtin_base(tier)
        assert (base.width, base.height) == (width, height)
        assert base.source == source
        assert base.verified is True
        assert base.blocked_cells
        assert base.blocked_cells <= base.allowed_cells


def test_builtin_core_coordinates_match_validated_spatial_analysis() -> None:
    expected_core = {
        1: frozenset((x, y) for y in (6, 7) for x in range(8, 12)),
        2: frozenset((x, y) for y in (7, 8) for x in range(10, 14)),
        3: frozenset((x, y) for y in (8, 9) for x in range(12, 16)),
        4: frozenset((x, y) for y in (9, 10) for x in range(14, 18)),
    }
    for tier, blocked in expected_core.items():
        base = builtin_base(tier)
        assert base.blocked_cells == blocked
        assert len(base.blocked_cells) == 8


def test_base_i_row_width_profile_matches_reference_matrix() -> None:
    base = builtin_base(1)
    row_widths = [sum((x, y) in base.allowed_cells for x in range(base.width)) for y in range(base.height)]
    assert row_widths == [14, 18, 20, 22, 22, 22, 22, 22, 22, 20, 18, 14]


def test_csv_dimensions_are_inferred_from_rows_and_columns(tmp_path: Path) -> None:
    path = tmp_path / "custom.csv"
    path.write_text(
        "y,0,1,2,3\n"
        "0,0,1,1,0\n"
        "1,1,1,X,1\n"
        "2,0,1,1,0\n",
        encoding="utf-8",
    )

    width, height, allowed, blocked = _read_grid_csv(path)
    assert (width, height) == (4, 3)
    assert (2, 1) in blocked
    assert (2, 1) in allowed
    assert (0, 0) not in allowed

    base = load_base_csv(path, tier=9, organics_capacity=999, verified=True)
    assert base.width == 4
    assert base.height == 3
    assert base.organics_capacity == 999
    assert base.verified is True


def test_csv_zero_cells_are_outside_base_and_x_cells_are_blocked() -> None:
    base = builtin_base(1)
    assert (0, 0) not in base.allowed_cells
    assert base.blocked_cells
    assert not (base.blocked_cells & base.buildable_cells)
