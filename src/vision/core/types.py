from dataclasses import dataclass
from enum import IntEnum


class RotationAngle(IntEnum):
    NONE = 0
    CLOCKWISE_90 = 90
    COUNTER_CLOCKWISE_90 = -90
    ROTATE_180 = 180


@dataclass
class RotationResult:
    angle: RotationAngle
    confidence: float
    original_angle: float
    applied_rotation: bool
