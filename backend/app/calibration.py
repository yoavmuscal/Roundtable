"""Camera-to-table calibration, validation, grid checks, and seat projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Sequence

from .geometry import (
    Homography,
    Point,
    clamp,
    closest_point_on_polygon,
    cross,
    distance,
    polygon_edges,
    signed_area,
)


class CalibrationError(ValueError):
    """A plain-English calibration rejection suitable for display."""


@dataclass(frozen=True, slots=True)
class TableSize:
    width_m: float
    height_m: float

    def validate(self) -> None:
        if self.width_m <= 0.2 or self.height_m <= 0.2:
            raise CalibrationError("Enter the real table width and depth in meters.")


@dataclass(slots=True)
class Calibration:
    corners: tuple[Point, Point, Point, Point]
    table_size: TableSize
    center_click: Point | None = None
    image_to_table_h: Homography = field(init=False, repr=False)
    table_to_image_h: Homography = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.table_size.validate()
        validate_corners(self.corners)
        self.image_to_table_h = Homography.from_correspondences(
            self.corners, self.table_corners
        )
        self.table_to_image_h = self.image_to_table_h.inverse()

    @property
    def table_corners(self) -> tuple[Point, Point, Point, Point]:
        return (
            Point(0.0, 0.0),
            Point(self.table_size.width_m, 0.0),
            Point(self.table_size.width_m, self.table_size.height_m),
            Point(0.0, self.table_size.height_m),
        )

    def image_to_table(self, point: Point) -> Point:
        return self.image_to_table_h.project(point)

    def table_to_image(self, point: Point) -> Point:
        return self.table_to_image_h.project(point)

    def center_error(self, center_click: Point | None = None) -> float:
        click = center_click or self.center_click
        if click is None:
            raise CalibrationError("Click the taped table center to finish Check B.")
        projected_center = self.table_to_image(
            Point(self.table_size.width_m / 2.0, self.table_size.height_m / 2.0)
        )
        diagonal = distance(self.corners[0], self.corners[2])
        return distance(projected_center, click) / diagonal

    def grid_lines(self, spacing_m: float = 0.25) -> list[list[dict[str, float]]]:
        lines: list[list[Point]] = []
        x = 0.0
        while x <= self.table_size.width_m + 1e-9:
            lines.append(
                [self.table_to_image(Point(x, 0.0)), self.table_to_image(Point(x, self.table_size.height_m))]
            )
            x += spacing_m
        y = 0.0
        while y <= self.table_size.height_m + 1e-9:
            lines.append(
                [self.table_to_image(Point(0.0, y)), self.table_to_image(Point(self.table_size.width_m, y))]
            )
            y += spacing_m
        return [[point.as_dict() for point in line] for line in lines]

    def result(self) -> dict[str, object]:
        return {
            "ok": True,
            "centerError": self.center_error() if self.center_click else None,
            "grid": self.grid_lines(),
            "corners": [corner.as_dict() for corner in self.corners],
            "tableSize": {
                "widthM": self.table_size.width_m,
                "heightM": self.table_size.height_m,
            },
        }

    def project_seat(self, shoulder: Point, reach_m: float = 0.45) -> Point:
        """Project a person to a seat marker just outside the nearest table edge."""
        hit = _first_downward_table_hit(shoulder, self.corners)
        if hit is None:
            hit = closest_point_on_polygon(shoulder, self.corners)
        table_hit = self.image_to_table(hit)
        width = self.table_size.width_m
        height = self.table_size.height_m
        clamped = Point(clamp(table_hit.x, 0.0, width), clamp(table_hit.y, 0.0, height))
        edge_distances = (
            (abs(clamped.y), Point(clamped.x, -reach_m)),
            (abs(height - clamped.y), Point(clamped.x, height + reach_m)),
            (abs(clamped.x), Point(-reach_m, clamped.y)),
            (abs(width - clamped.x), Point(width + reach_m, clamped.y)),
        )
        return min(edge_distances, key=lambda item: item[0])[1]


def _first_downward_table_hit(origin: Point, polygon: Sequence[Point]) -> Point | None:
    hits: list[Point] = []
    for a, b in polygon_edges(polygon):
        dx = b.x - a.x
        if abs(dx) < 1e-12:
            continue
        t = (origin.x - a.x) / dx
        if not -1e-9 <= t <= 1.0 + 1e-9:
            continue
        y = a.y + t * (b.y - a.y)
        if y >= origin.y - 1e-9:
            hits.append(Point(origin.x, y))
    return min(hits, key=lambda point: point.y, default=None)


def validate_corners(corners: Sequence[Point]) -> None:
    if len(corners) != 4:
        raise CalibrationError("Click all four table corners.")
    for corner in corners:
        if not (0.0 <= corner.x <= 1.0 and 0.0 <= corner.y <= 1.0):
            raise CalibrationError("Corner clicks must stay inside the camera image.")
    crosses = [
        cross(corners[index], corners[(index + 1) % 4], corners[(index + 2) % 4])
        for index in range(4)
    ]
    if any(abs(value) < 1e-5 for value in crosses):
        if abs(signed_area(corners)) < 0.01:
            raise CalibrationError("Those corners cover almost no area; click the four taped corners.")
        raise CalibrationError("Three corners are nearly in a straight line; click each taped corner.")
    if not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        raise CalibrationError("The corner order is crossed. Click far-left, far-right, near-right, then near-left.")
    if abs(signed_area(corners)) < 0.01:
        raise CalibrationError("Those corners cover almost no area; click the four taped corners.")
    far_left, far_right, near_right, near_left = corners
    if far_left.x >= far_right.x or near_left.x >= near_right.x:
        raise CalibrationError("Left and right corners are reversed; use the labeled corner order.")
    if (far_left.y + far_right.y) >= (near_left.y + near_right.y):
        raise CalibrationError("The far edge must appear above the near edge in the camera image.")


def calibration_from_payload(payload: dict[str, object]) -> Calibration:
    try:
        raw_corners = payload["corners"]  # type: ignore[index]
        raw_size = payload["tableSize"]  # type: ignore[index]
        raw_center = payload.get("centerClick")
        corners = tuple(Point(float(item["x"]), float(item["y"])) for item in raw_corners)  # type: ignore[union-attr]
        size = TableSize(float(raw_size["widthM"]), float(raw_size["heightM"]))  # type: ignore[index]
        center = None
        if raw_center is not None:
            center = Point(float(raw_center["x"]), float(raw_center["y"]))  # type: ignore[index]
        return Calibration(corners=corners, table_size=size, center_click=center)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CalibrationError):
            raise
        raise CalibrationError("Calibration payload is incomplete or invalid.") from exc
