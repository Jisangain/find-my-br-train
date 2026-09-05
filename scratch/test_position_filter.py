# scratch/test_position_filter.py
#
# Exercises the plausibility filter (functions/position_filter.py, wired into
# RedisTrainTracker.push/_update_cached_position). Uses a synthetic train id
# (never a real one - this runs against the same shared Redis db as
# production, like the other scratch/ tests) but with real Bangladesh station
# coordinates (borrowed from train 746, Tarakandi -> Dhaka) so the distances
# involved are physically meaningful instead of made up.

import sys
import os
import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from functions.redis_tracker import RedisTrainTracker, BD_TZ

TRAIN_ID = "test_filter_746"  # synthetic - must never collide with a real train id

# Schedule times are anchored to "now" (minus a fixed offset) rather than a
# hardcoded calendar date: push() compares ping timestamps against the real
# wall clock (max_valid_age, future-timestamp rejection), so a fixed past
# date would silently look like ancient/expired data whenever this test runs
# more than ~10 hours after that date. ANCHOR sits 6h30m before the real
# "now", so every offset used below (0..360 minutes) lands safely in the
# past and well within the 10-hour validity window.
NOW = datetime.datetime.now(tz=BD_TZ)
ANCHOR = NOW - datetime.timedelta(hours=6, minutes=30)


def ts(offset_minutes):
    """Unix timestamp `offset_minutes` after ANCHOR."""
    return int((ANCHOR + datetime.timedelta(minutes=offset_minutes)).timestamp())


def hhmm(offset_minutes):
    """'HH:MM' schedule string `offset_minutes` after ANCHOR, BD wall-clock."""
    return (ANCHOR + datetime.timedelta(minutes=offset_minutes)).strftime("%H:%M")


# Real inter-station schedule gaps for train 746 (Tarakandi 02:00 -> Dhaka
# 08:00), expressed as minute-offsets from departure so they can be laid
# down relative to ANCHOR instead of fixed clock times.
_OFFSETS = [0, 18, 71, 95, 108, 123, 150, 198, 222, 255, 297, 323, 360]
_NAMES = [
    "Tarakandi", "Sarishabari", "Jamalpur_Town", "Narundi", "Piyarpur",
    "Bidyaganj", "Mymensingh", "Gafargaon", "Kaoraid", "Sreepur",
    "Joydebpur", "Biman_Bandar", "Dhaka",
]
STATIONS = [[name, 1, hhmm(off)] for name, off in zip(_NAMES, _OFFSETS)]
SID_TO_SLOC = {
    "Tarakandi": [24.6857189, 89.8243306],
    "Sarishabari": [24.7608313, 89.8400644],
    "Jamalpur_Town": [24.914805733900828, 89.9546869774768],
    "Narundi": [24.8650076, 90.1199339],
    "Piyarpur": [24.8790798, 90.1966031],
    "Bidyaganj": [24.824226537574447, 90.25939552885043],
    "Mymensingh": [24.7532728, 90.4101031],
    "Gafargaon": [24.4536308, 90.5478513],
    "Kaoraid": [24.3083152, 90.5124472],
    "Sreepur": [24.1989858, 90.4795567],
    "Joydebpur": [23.9980388, 90.420312],
    "Biman_Bandar": [23.8520672672048, 90.40806533450319],
    "Dhaka": [23.73424596143561, 90.4264201316412],
}
# Cumulative km at each stop above (Tarakandi=0 ... Dhaka=198.5), for
# reference while reading the assertions below:
#   0 Tarakandi 0.0        4 Piyarpur 54.6      8 Kaoraid 133.2
#   1 Sarishabari 8.5      5 Bidyaganj 63.4      9 Sreepur 145.8
#   2 Jamalpur_Town 29.2   6 Mymensingh 80.6    10 Joydebpur 169.0
#   3 Narundi 46.7         7 Gafargaon 116.7    11 Biman_Bandar 185.2
#                                               12 Dhaka 198.5


def run_test():
    print("🧪 Running position-filter plausibility tests...")

    tracker = RedisTrainTracker(host="localhost", port=6379, db=0)
    if not tracker.health_check():
        print("❌ Error: Redis is not running or not accessible.")
        sys.exit(1)

    tracker.set_train_data({
        "tid_to_stations": {TRAIN_ID: STATIONS},
        "sid_to_sloc": SID_TO_SLOC,
    })

    def clean():
        keys = tracker.redis.keys(f"train:{TRAIN_ID}:*")
        if keys:
            tracker.redis.delete(*keys)
        tracker.redis.srem("active_trains", TRAIN_ID)
        tracker.redis.srem("all_trains_with_history", TRAIN_ID)

    failures = 0

    def check(label, condition):
        nonlocal failures
        status = "OK  " if condition else "FAIL"
        if not condition:
            failures += 1
        print(f"{status} {label}")

    # --- 1. First-ever ping: no reference yet, must be accepted regardless
    #         of being completely alone. ---
    clean()
    ok, msg = tracker.push(TRAIN_ID, "userA", 5.0, ts(180), is_bot=False)
    check(f"first-ever ping accepted with nothing to compare against ({msg})", ok)

    pos = tracker.get_train_position(TRAIN_ID)
    check(
        f"cached position ~5.0 (got {pos['position'] if pos else None})",
        pos is not None and abs(pos["position"] - 5.0) < 0.01,
    )

    # --- 2. GPS jitter / a different bogie reporting a nearby-but-not-
    #         identical position 60s later: must be accepted. ---
    ok, msg = tracker.push(TRAIN_ID, "userB", 5.05, ts(181), is_bot=False)
    check(f"small jitter (~0.6km) accepted ({msg})", ok)

    # --- 3. A wild jump 2 minutes after the first ping (~128km, no train
    #         does that in 2 minutes): must be rejected for a user AND for
    #         an authenticated bot - no bypass. ---
    for uid, is_bot in [("userFake", False), ("botFake", True)]:
        ok, msg = tracker.push(TRAIN_ID, uid, 11.5, ts(182), is_bot=is_bot)
        label = "bot" if is_bot else "user"
        check(f"~128km/2min jump rejected for {label}, no bot bypass ({msg})", not ok)

    # --- 4. Consensus clustering: two more users agree closely with the
    #         first, one lone outlier reports a position far away but late
    #         enough that it's individually speed-plausible on its own. The
    #         aggregate should follow the 3-user cluster, not the outlier -
    #         while still counting all 4 as active reporters. ---
    clean()
    tracker.push(TRAIN_ID, "userA", 5.0, ts(180), is_bot=False)
    tracker.push(TRAIN_ID, "userB", 5.02, ts(181), is_bot=False)
    tracker.push(TRAIN_ID, "userC", 4.98, ts(182), is_bot=False)
    # 45 minutes later, ~61.5km away - fast, but not impossible, so this
    # passes the individual teleport check and gets stored.
    ok, msg = tracker.push(TRAIN_ID, "userOutlier", 7.5, ts(225), is_bot=False)
    check(f"fast-but-individually-plausible outlier is accepted and stored ({msg})", ok)

    pos = tracker.get_train_position(TRAIN_ID)
    check(
        f"aggregate follows the 3-user cluster (~5.0), not the lone outlier at 7.5 "
        f"(got {pos['position'] if pos else None})",
        pos is not None and abs(pos["position"] - 5.0) < 0.5,
    )
    check(
        f"active_user count still reports all 4 reporters, not just the winning cluster "
        f"(got {pos.get('active_user') if pos else None})",
        pos is not None and pos.get("active_user") == 4,
    )

    # --- 5. Heavy delay tolerance: a train that has barely moved in 5 real
    #         hours (badly delayed) must keep validating small, genuine
    #         updates near its last real position - regardless of how far
    #         ahead the *static* timetable thinks it should be by now. A
    #         fake ping claiming to be near where the timetable would put an
    #         on-time train must still be rejected, even though it would
    #         have passed the old schedule-only ceiling check. ---
    clean()
    tracker.push(TRAIN_ID, "userA", 0.5, ts(10), is_bot=False)
    ok, msg = tracker.push(TRAIN_ID, "userB", 0.6, ts(310), is_bot=False)
    check(f"tiny real movement after a 5h delay still accepted ({msg})", ok)

    ok, msg = tracker.push(TRAIN_ID, "userFake2", 10.5, ts(311), is_bot=False)
    check(
        f"fake 'on schedule' position (~180km away) rejected via the teleport "
        f"check despite being within the loose schedule ceiling ({msg})",
        not ok,
    )

    clean()
    print(f"\n{'✅ All checks passed' if failures == 0 else f'❌ {failures} check(s) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run_test()
