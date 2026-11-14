import pytest

from backend.app.calibration import Calibration, CalibrationError, TableSize
from backend.app.geometry import Point, distance


CORNERS = (
    Point(0.22, 0.70),
    Point(0.78, 0.70),
    Point(0.97, 0.98),
    Point(0.03, 0.98),
)
SIZE = TableSize(1.8, 0.9)


def test_corners_round_trip() -> None:
    calibration = Calibration(CORNERS, SIZE)
    for corner in CORNERS:
        round_trip = calibration.table_to_image(calibration.image_to_table(corner))
        assert distance(corner, round_trip) < 1e-6


def test_rejects_collinear_crossed_and_mirrored_clicks() -> None:
    with pytest.raises(CalibrationError, match="straight line|almost no area"):
        Calibration((Point(0.1, 0.5), Point(0.2, 0.5), Point(0.3, 0.5), Point(0.4, 0.5)), SIZE)
    with pytest.raises(CalibrationError, match="crossed|reversed|order"):
        Calibration((CORNERS[0], CORNERS[2], CORNERS[1], CORNERS[3]), SIZE)
    with pytest.raises(CalibrationError, match="reversed"):
        Calibration((CORNERS[1], CORNERS[0], CORNERS[3], CORNERS[2]), SIZE)


def test_center_check_distinguishes_true_center_from_naive_midpoint() -> None:
    perspective_corners = (
        Point(0.25, 0.68),
        Point(0.75, 0.68),
        Point(0.98, 1.0),
        Point(0.02, 1.0),
    )
    true_center_image = Calibration(perspective_corners, SIZE).table_to_image(Point(0.9, 0.45))
    calibration = Calibration(perspective_corners, SIZE, center_click=true_center_image)
    assert calibration.center_error() < 0.05

    naive_midpoint = Point(
        sum(point.x for point in perspective_corners) / 4.0,
        sum(point.y for point in perspective_corners) / 4.0,
    )
    naive = Calibration(perspective_corners, SIZE, center_click=naive_midpoint)
    assert naive.center_error() > 0.05


def test_grid_lines_stay_in_camera_frame() -> None:
    calibration = Calibration(CORNERS, SIZE)
    lines = calibration.grid_lines()
    assert len(lines) >= 10
    for line in lines:
        for point in line:
            assert 0.0 <= point["x"] <= 1.0
            assert 0.0 <= point["y"] <= 1.0


def test_far_side_seat_lands_045m_beyond_far_edge_and_preserves_order() -> None:
    calibration = Calibration(CORNERS, SIZE)
    left = calibration.project_seat(Point(0.35, 0.50))
    middle = calibration.project_seat(Point(0.50, 0.48))
    right = calibration.project_seat(Point(0.65, 0.50))
    assert left.y == pytest.approx(-0.45)
    assert middle.y == pytest.approx(-0.45)
    assert right.y == pytest.approx(-0.45)
    assert left.x < middle.x < right.x


def test_beyond_corner_projects_to_short_end_and_missed_ray_uses_outline() -> None:
    calibration = Calibration(CORNERS, SIZE)
    right_end = calibration.project_seat(Point(0.995, 0.80))
    assert right_end.x == pytest.approx(SIZE.width_m + 0.45)
    outside = calibration.project_seat(Point(0.995, 0.10))
    assert outside.x >= SIZE.width_m or outside.y <= 0.0
