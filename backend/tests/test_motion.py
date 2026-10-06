"""Black-and-white difference along the vehicle base."""

import numpy as np

from app.pipeline.motion import base_changed, to_gray
from app.pipeline.types import TrackedObject


def _car(x1, y):
    return TrackedObject(1, x1, y - 20, x1 + 40, y, 0.9, "car")


def test_a_moved_vehicle_changes_the_grey_frame():
    before = np.zeros((80, 120, 3), np.uint8)
    after = before.copy()
    cv2_rect(after, 30, 40, 70, 60)
    assert base_changed(to_gray(before), to_gray(after), _car(30, 60))


def test_a_still_vehicle_does_not():
    img = np.zeros((80, 120, 3), np.uint8)
    cv2_rect(img, 30, 40, 70, 60)
    gray = to_gray(img)
    assert not base_changed(gray, gray.copy(), _car(30, 60))


def test_straight_down_the_road_still_counts_as_movement():
    """The middle of the box stays the same colour; the edges are what change."""
    before = np.full((80, 80, 3), 40, np.uint8)
    after = before.copy()
    before[10:40, 20:50] = 200
    after[17:47, 20:50] = 200
    car = TrackedObject(1, 20, 17, 50, 47, 0.9, "car")
    assert base_changed(to_gray(before), to_gray(after), car, anchor="center")


def cv2_rect(img, x1, y1, x2, y2):
    img[y1:y2, x1:x2] = (255, 255, 255)
