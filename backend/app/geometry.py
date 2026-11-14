"""Small pure-Python geometry and homography helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


def distance(a: Point, b: Point) -> float:
    return hypot(a.x - b.x, a.y - b.y)


def cross(origin: Point, a: Point, b: Point) -> float:
    return (a.x - origin.x) * (b.y - origin.y) - (a.y - origin.y) * (b.x - origin.x)


def signed_area(points: Sequence[Point]) -> float:
    return 0.5 * sum(
        points[i].x * points[(i + 1) % len(points)].y
        - points[(i + 1) % len(points)].x * points[i].y
        for i in range(len(points))
    )


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    n = len(values)
    augmented = [row[:] + [value] for row, value in zip(matrix, values)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][n] for row in range(n)]


class Homography:
    """Project points between two planes using a 3x3 homography."""

    def __init__(self, coefficients: Sequence[float]) -> None:
        if len(coefficients) != 9:
            raise ValueError("a homography has nine coefficients")
        self.h = tuple(float(value) for value in coefficients)

    @classmethod
    def from_correspondences(
        cls, source: Sequence[Point], destination: Sequence[Point]
    ) -> "Homography":
        if len(source) != 4 or len(destination) != 4:
            raise ValueError("exactly four point correspondences are required")
        matrix: list[list[float]] = []
        values: list[float] = []
        for src, dst in zip(source, destination):
            matrix.append(
                [src.x, src.y, 1.0, 0.0, 0.0, 0.0, -dst.x * src.x, -dst.x * src.y]
            )
            values.append(dst.x)
            matrix.append(
                [0.0, 0.0, 0.0, src.x, src.y, 1.0, -dst.y * src.x, -dst.y * src.y]
            )
            values.append(dst.y)
        return cls((*_solve_linear(matrix, values), 1.0))

    def project(self, point: Point) -> Point:
        h = self.h
        denominator = h[6] * point.x + h[7] * point.y + h[8]
        if abs(denominator) < 1e-12:
            raise ValueError("point lies on the homography horizon")
        return Point(
            (h[0] * point.x + h[1] * point.y + h[2]) / denominator,
            (h[3] * point.x + h[4] * point.y + h[5]) / denominator,
        )

    def inverse(self) -> "Homography":
        h = self.h
        cofactors = [
            h[4] * h[8] - h[5] * h[7],
            h[5] * h[6] - h[3] * h[8],
            h[3] * h[7] - h[4] * h[6],
            h[2] * h[7] - h[1] * h[8],
            h[0] * h[8] - h[2] * h[6],
            h[1] * h[6] - h[0] * h[7],
            h[1] * h[5] - h[2] * h[4],
            h[2] * h[3] - h[0] * h[5],
            h[0] * h[4] - h[1] * h[3],
        ]
        determinant = h[0] * cofactors[0] + h[1] * cofactors[1] + h[2] * cofactors[2]
        if abs(determinant) < 1e-12:
            raise ValueError("homography is singular")
        adjugate = [
            cofactors[0],
            cofactors[3],
            cofactors[6],
            cofactors[1],
            cofactors[4],
            cofactors[7],
            cofactors[2],
            cofactors[5],
            cofactors[8],
        ]
        return Homography([value / determinant for value in adjugate])


def closest_point_on_segment(point: Point, a: Point, b: Point) -> Point:
    dx = b.x - a.x
    dy = b.y - a.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return a
    t = clamp(((point.x - a.x) * dx + (point.y - a.y) * dy) / length_squared, 0.0, 1.0)
    return Point(a.x + t * dx, a.y + t * dy)


def closest_point_on_polygon(point: Point, polygon: Sequence[Point]) -> Point:
    return min(
        (
            closest_point_on_segment(point, polygon[i], polygon[(i + 1) % len(polygon)])
            for i in range(len(polygon))
        ),
        key=lambda candidate: distance(candidate, point),
    )


def polygon_edges(points: Sequence[Point]) -> Iterable[tuple[Point, Point]]:
    for index, point in enumerate(points):
        yield point, points[(index + 1) % len(points)]
