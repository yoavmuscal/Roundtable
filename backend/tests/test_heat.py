from collections import Counter
from math import sqrt

import pytest

from backend.app.geometry import Point, distance
from backend.app.heat import HeatMap
from backend.app.hexmap import Axial, HexGrid


def test_hex_neighbor_spacing_vertices_extent_and_duplicates() -> None:
    grid = HexGrid(1.8, 0.9, 0.10, 0.8)
    assert 200 <= len(grid.cells) <= 400
    assert len(grid.cells) == len(set(grid.cells))
    cell = grid.nearest(Point(-0.45, -0.45))
    neighbor_centers = [grid.axial_to_point(coord) for coord in grid.neighbors(cell.coord) if coord in grid.cells]
    assert neighbor_centers
    for center in neighbor_centers:
        assert distance(center, cell.center) == pytest.approx(sqrt(3) * grid.size_m)
    vertices = cell.vertices(grid.size_m)
    top = vertices[0]
    assert top.x == pytest.approx(cell.center.x)
    assert top.y < cell.center.y
    assert not any(0 < item.center.x < 1.8 and 0 < item.center.y < 0.9 for item in grid.cells.values())


def test_one_talker_owns_every_visible_hex() -> None:
    heat = HeatMap(HexGrid(1.8, 0.9))
    heat.deposit(0, "p1", Point(0.9, -0.45), 10, 1.0)
    frame = heat.frame(10)
    assert frame
    assert {hex_["owner"] for hex_ in frame} == {"p1"}


def test_two_equal_talkers_split_at_midpoint() -> None:
    heat = HeatMap(HexGrid(1.8, 0.9))
    heat.deposit(0, "p1", Point(0.45, -0.45), 10, 1.0)
    heat.deposit(0, "p2", Point(1.35, -0.45), 10, 1.0)
    frame = heat.frame(10)
    owners = {item["axial"]["q"]: item["owner"] for item in frame}
    left = [item for item in frame if grid_x(item) < 0.9]
    right = [item for item in frame if grid_x(item) > 0.9]
    assert left and right
    assert {item["owner"] for item in left} == {"p1"}
    assert {item["owner"] for item in right} == {"p2"}


def test_60s_window_forgets_old_heat() -> None:
    heat = HeatMap(HexGrid(1.8, 0.9))
    heat.deposit(0, "p1", Point(0.45, -0.45), 1, 1.0)
    assert heat.frame(1, "60s")
    assert heat.frame(61.1, "60s") == []


def test_reach_cap_fairness() -> None:
    heat = HeatMap(HexGrid(1.8, 0.9))
    for person, x, seconds in (("p1", 0.35, 45), ("p2", 0.90, 31), ("p3", 1.45, 25)):
        heat.deposit(0, person, Point(x, -0.45), seconds, 1.0)
    frame = heat.frame(60)
    counts = Counter(item["owner"] for item in frame)
    assert counts["p1"] > counts["p2"]
    assert counts["p3"] <= counts["p2"] * 1.15
    peak = {}
    for item in frame:
        peak[item["owner"]] = max(peak.get(item["owner"], 0), item["intensity"])
    assert peak["p1"] >= peak["p2"] >= peak["p3"]


def grid_x(item: dict) -> float:
    q = item["axial"]["q"]
    r = item["axial"]["r"]
    return sqrt(3) * 0.1 * (q + r / 2)
