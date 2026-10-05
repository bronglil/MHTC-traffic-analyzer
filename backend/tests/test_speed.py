"""Processing-speed presets (app/pipeline/speed.py).

Their effect on counts is covered by the ground-truth clips: dual_carriageway.json
and overhead_road.json run the crossing rule at the strides the presets choose.
"""

import pytest

from app.pipeline.speed import SPEEDS, plan


def test_accurate_keeps_the_chosen_settings():
    p = plan("accurate", 30, frame_stride=1, image_size=1280, sliced=True)
    assert (p.frame_stride, p.image_size, p.sliced, p.tracker) == (1, 1280, True, "bytetrack")


@pytest.mark.parametrize("fps,expected", [(25, [1, 2, 2, 4]), (30, [1, 2, 3, 5]), (60, [1, 4, 6, 10])])
def test_presets_target_analysed_frames_per_second_of_video(fps, expected):
    assert [plan(s, fps).frame_stride for s in SPEEDS] == expected


def test_faster_presets_drop_slicing_and_cap_resolution():
    assert plan("balanced", 30, image_size=1280, sliced=True).sliced
    fast = plan("fast", 30, image_size=1280, sliced=True)
    assert (fast.image_size, fast.sliced) == (960, False)
    assert plan("fastest", 30, image_size=1920, sliced=True).image_size == 640


def test_low_analysed_rates_switch_to_the_time_lapse_tracker():
    assert plan("fast", 30).tracker == "bytetrack"  # 10 fps
    assert plan("fastest", 30).tracker == "timelapse"  # 6 fps: boxes stop overlapping
    assert plan("fastest", 30, tracker="botsort").tracker == "timelapse"


def test_presets_never_slow_down_a_stride_the_user_chose():
    assert plan("balanced", 30, frame_stride=6).frame_stride == 6


def test_time_lapse_footage_is_never_skipped():
    p = plan("fastest", 30, tracker="timelapse", timelapse=True)
    assert (p.frame_stride, p.tracker) == (1, "timelapse")


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        plan("warp", 30)
