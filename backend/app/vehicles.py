"""Vehicle type catalogue and detector-class mapping.

Detectors emit their own class names (e.g. COCO's ``car``, ``truck``). The rest
of the system only deals in canonical ``VehicleType`` values, so swapping in a
custom-trained model only requires its class names to appear in
``CLASS_NAME_ALIASES``.

Light goods vehicles (vans, <= 3.5 t gross weight) are split in two:

* ``lgv1`` - small, car-derived vans (e.g. Ford Transit Connect, VW Caddy,
  Citroën Berlingo, Vauxhall Combo).
* ``lgv2`` - larger panel / Luton / dropside vans up to 3.5 t (e.g. Ford Transit,
  Mercedes Sprinter, VW Crafter, Renault Master).

``van`` is accepted as an *unsplit* intermediate class (e.g. from a model that
only knows "van"); the classification stage resolves it to ``lgv1``/``lgv2``.
"""

from __future__ import annotations

from enum import Enum


class VehicleType(str, Enum):
    CAR = "car"
    LGV1 = "lgv1"
    LGV2 = "lgv2"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"


ALL_VEHICLE_TYPES: list[str] = [v.value for v in VehicleType]

VEHICLE_LABELS: dict[str, str] = {
    "car": "Car",
    "lgv1": "LGV1 (small van)",
    "lgv2": "LGV2 (large van)",
    "truck": "Truck / HGV",
    "bus": "Bus / Coach",
    "motorcycle": "Motorcycle",
    "bicycle": "Bicycle",
}

# Intermediate class: a van whose LGV1/LGV2 split is still to be decided.
UNSPLIT_VAN = "van"

# Detector / classifier class name (lower-cased, spaces/underscores ignored)
# -> canonical type (or the unsplit "van").
CLASS_NAME_ALIASES: dict[str, str] = {
    "car": "car",
    "taxi": "car",
    "suv": "car",
    "pickup": "car",
    "van": UNSPLIT_VAN,
    "lgv": UNSPLIT_VAN,
    "lgv1": "lgv1",
    "smallvan": "lgv1",
    "cardrivenvan": "lgv1",
    "cardrivedvan": "lgv1",
    "minivan": "lgv1",
    "lgv2": "lgv2",
    "largevan": "lgv2",
    "panelvan": "lgv2",
    "lutonvan": "lgv2",
    "truck": "truck",
    "lorry": "truck",
    "hgv": "truck",
    "ogv": "truck",
    "ogv1": "truck",
    "ogv2": "truck",
    "bus": "bus",
    "coach": "bus",
    "psv": "bus",
    "motorcycle": "motorcycle",
    "motorbike": "motorcycle",
    "mc": "motorcycle",
    "bicycle": "bicycle",
    "bike": "bicycle",
    "pedalcycle": "bicycle",
    "pc": "bicycle",
}


def to_vehicle_type(class_name: str) -> str | None:
    key = class_name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return CLASS_NAME_ALIASES.get(key)
