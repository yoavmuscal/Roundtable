from __future__ import annotations

from math import hypot
from typing import Iterable

from .contract import CalibrationPayload, CalibrationResult, Point, Size


def polygon_area(points: Iterable[Point]) -> float:
    values = list(points)
    area = 0.0
    for index, a in enumerate(values):
        b = values[(index + 1) % len(values)]
        area += a["x"] * b["y"] - b["x"] * a["y"]
    return area / 2


def is_convex(points: list[Point]) -> bool:
    sign = 0
    for index, a in enumerate(points):
        b = points[(index + 1) % len(points)]
        c = points[(index + 2) % len(points)]
        cross = (b["x"] - a["x"]) * (c["y"] - b["y"]) - (b["y"] - a["y"]) * (c["x"] - b["x"])
        if abs(cross) < 1e-9:
            continue
        current = 1 if cross > 0 else -1
        if sign and current != sign:
            return False
        sign = current
    return True


def solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    n = len(values)
    rows = [row[:] + [values[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise ValueError("Degenerate calibration")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        for c in range(column, n + 1):
            rows[column][c] /= divisor
        for row in range(n):
            if row == column:
                continue
            factor = rows[row][column]
            for c in range(column, n + 1):
                rows[row][c] -= factor * rows[column][c]
    return [rows[index][n] for index in range(n)]


def homography(source: list[Point], target: list[Point]) -> list[float]:
    matrix: list[list[float]] = []
    values: list[float] = []
    for src, dst in zip(source, target, strict=True):
        x, y = src["x"], src["y"]
        u, v = dst["x"], dst["y"]
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)
    return [*solve_linear(matrix, values), 1.0]


def apply_homography(h: list[float], point: Point) -> Point:
    denominator = h[6] * point["x"] + h[7] * point["y"] + h[8]
    return {
        "x": (h[0] * point["x"] + h[1] * point["y"] + h[2]) / denominator,
        "y": (h[3] * point["x"] + h[4] * point["y"] + h[5]) / denominator,
    }


def table_grid(size: Size, step: float = 0.25) -> list[list[Point]]:
    lines: list[list[Point]] = []
    x = 0.0
    while x <= size["width"] + 1e-9:
        lines.append([{"x": x, "y": 0.0}, {"x": x, "y": size["height"]}])
        x += step
    y = 0.0
    while y <= size["height"] + 1e-9:
        lines.append([{"x": 0.0, "y": y}, {"x": size["width"], "y": y}])
        y += step
    return lines


def validate_calibration(payload: CalibrationPayload) -> CalibrationResult:
    corners = payload["corners"]
    if len(corners) != 4:
        return {"ok": False, "message": "Click all four corners before running checks."}
    if not is_convex(corners):
        return {"ok": False, "message": "The corner outline crosses over itself. Use far-left, far-right, near-right, near-left."}
    if abs(polygon_area(corners)) < 0.015:
        return {"ok": False, "message": "The four corners need to enclose more of the table."}
    far_left, far_right, near_right, near_left = corners
    if far_left["x"] >= far_right["x"] or near_left["x"] >= near_right["x"]:
        return {"ok": False, "message": "The left corners must be left of the right corners."}
    if far_left["y"] >= near_left["y"] or far_right["y"] >= near_right["y"]:
        return {"ok": False, "message": "The far corners must be above the near corners."}

    size = payload["tableSize"]
    table_corners = [
        {"x": 0.0, "y": 0.0},
        {"x": size["width"], "y": 0.0},
        {"x": size["width"], "y": size["height"]},
        {"x": 0.0, "y": size["height"]},
    ]
    try:
        table_to_image = homography(table_corners, corners)
        true_center = apply_homography(
            table_to_image, {"x": size["width"] / 2, "y": size["height"] / 2}
        )
        center_error = hypot(
            payload["center"]["x"] - true_center["x"], payload["center"]["y"] - true_center["y"]
        )
        image_grid = [
            [apply_homography(table_to_image, point) for point in line] for line in table_grid(size)
        ]
    except ValueError:
        return {"ok": False, "message": "Those corner clicks are too close to a straight line."}

    if center_error > 0.05:
        return {
            "ok": False,
            "message": "Check B failed: click the taped center, not the naive image midpoint.",
            "centerError": center_error,
            "gridLines": image_grid,
        }
    return {
        "ok": True,
        "message": "Calibration passed. Grid, center, and seat order all look consistent.",
        "centerError": center_error,
        "gridLines": image_grid,
    }
