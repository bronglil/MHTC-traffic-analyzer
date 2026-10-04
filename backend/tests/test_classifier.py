import numpy as np
import pytest

from app.pipeline.classifier import CropClassifierRefiner, PassThroughRefiner, SizeHeuristicRefiner, create_refiner
from app.pipeline.types import TrackedObject
from app.vehicles import to_vehicle_type

H = 400


def box(tid, size, y=300, vtype="car", conf=0.9, x=100):
    """Square box of side `size` whose bottom edge is at row `y`."""
    return TrackedObject(tid, x, y - size, x + size, y, conf, vtype)


@pytest.mark.parametrize(
    "name,expected",
    [("car", "car"), ("LGV1", "lgv1"), ("lgv_2", "lgv2"), ("Large Van", "lgv2"), ("small-van", "lgv1"),
     ("van", "van"), ("HGV", "truck"), ("OGV2", "truck"), ("Coach", "bus"), ("motorbike", "motorcycle"),
     ("Pedal Cycle", "bicycle"), ("person", None), ("airplane", None)],
)
def test_class_aliases(name, expected):
    assert to_vehicle_type(name) == expected


def calibrated(**kw) -> SizeHeuristicRefiner:
    r = SizeHeuristicRefiner(H, min_calibration_samples=10, **kw)
    # Perspective: cars are 40px tall near row 300 and 20px near row 100.
    cars = [box(1000 + i, 40, 300) for i in range(10)] + [box(2000 + i, 20, 100) for i in range(10)]
    img = np.zeros((H, 600, 3), np.uint8)
    r.refine(cars, img)
    return r


def test_perspective_model():
    r = calibrated()
    assert r.expected_car_size(300 / H) == pytest.approx(40, abs=1)
    assert r.expected_car_size(100 / H) == pytest.approx(20, abs=1)
    assert r.expected_car_size(200 / H) == pytest.approx(30, abs=1)


@pytest.mark.parametrize(
    "vtype,size,y,expected",
    [
        ("van", 44, 300, "lgv1"),     # ~1.1x a car at this row -> small van
        ("van", 60, 300, "lgv2"),     # 1.5x -> large van
        ("van", 30, 100, "lgv2"),     # same 1.5x ratio further away
        ("truck", 56, 300, "lgv2"),   # COCO often calls big vans "truck"
        ("truck", 90, 300, "truck"),  # genuinely large -> HGV
        ("car", 42, 300, "car"),
        ("car", 60, 300, "lgv2"),     # far too big to be a car
        ("bus", 30, 300, "bus"),      # non-refinable classes untouched
    ],
)
def test_size_rules(vtype, size, y, expected):
    r = calibrated()
    out = r.refine([box(1, size, y, vtype, conf=0.4)], np.zeros((H, 600, 3), np.uint8))
    assert out[0].vehicle_type == expected


def test_uncalibrated_van_uses_default():
    r = SizeHeuristicRefiner(H, unsplit_van_default="lgv2")
    out = r.refine([box(1, 50, vtype="van", conf=0.4), box(2, 40, vtype="car", conf=0.3)], np.zeros((H, 600, 3)))
    assert [o.vehicle_type for o in out] == ["lgv2", "car"]


def test_track_median_resists_outliers():
    r = calibrated()
    img = np.zeros((H, 600, 3), np.uint8)
    sizes = [44, 45, 43, 80, 44, 46]  # one bad box (e.g. merged with a neighbour)
    types = [r.refine([box(7, s, vtype="van", conf=0.4)], img)[0].vehicle_type for s in sizes]
    assert types[-1] == "lgv1"


def test_passthrough_resolves_unsplit_van():
    out = PassThroughRefiner("lgv1").refine([box(1, 40, vtype="van"), box(2, 40, vtype="bus")], None)
    assert [o.vehicle_type for o in out] == ["lgv1", "bus"]


def test_crop_classifier_votes_per_track():
    names = ["car", "lgv1", "lgv2", "truck", "background"]
    calls = []

    def predict(crops):
        calls.append(len(crops))
        # bright crops look like LGV2, dark ones like a car
        return np.array([[0.1, 0.1, 0.7, 0.1, 0.0] if c.mean() > 100 else [0.8, 0.1, 0.05, 0.05, 0.0]
                         for c in crops])

    clf = CropClassifierRefiner(predict_fn=predict, class_names=names, every_n=1, max_samples=3, min_crop_size=10)
    img = np.zeros((H, 600, 3), np.uint8)
    img[200:300, 300:400] = 255
    van = TrackedObject(1, 300, 200, 400, 300, 0.9, "car")      # detector says car; crop is bright
    car = TrackedObject(2, 10, 10, 60, 60, 0.9, "car")
    bus = TrackedObject(3, 100, 100, 200, 200, 0.9, "bus")      # not refinable: never sent to the classifier
    tiny = TrackedObject(4, 500, 10, 505, 15, 0.9, "car")       # too small to classify
    for _ in range(5):
        out = clf.refine([van, car, bus, tiny], img)
    assert [o.vehicle_type for o in out] == ["lgv2", "car", "bus", "car"]
    assert sum(calls) == 6  # max_samples=3 crops for each of the two classifiable tracks


def test_create_refiner_modes():
    assert isinstance(create_refiner("detector", H), PassThroughRefiner)
    assert isinstance(create_refiner("size", H), SizeHeuristicRefiner)
    with pytest.raises(ValueError):
        create_refiner("classifier", H)
    with pytest.raises(ValueError):
        create_refiner("magic", H)
