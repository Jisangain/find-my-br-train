import sys, datetime
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from functions.redis_tracker import RedisTrainTracker, BD_TZ

t = RedisTrainTracker()
t.set_train_data({
    "tid_to_stations": {
        # Day train: 10:30 -> 14:00
        "781": [["Dhaka", 1, "10:30"], ["Bimanbandar", 1, "10:57"],
                 ["ghorashal", -1, -1], ["Narsingdi", 1, "11:39"], ["Bhairab", 1, "14:00"]],
        # Overnight train: 23:00 -> 05:30 (crosses midnight)
        "999": [["A", 1, "23:00"], ["B", 1, "01:00"], ["C", 1, "05:30"]],
        # No schedule data
        "555": [["X", 1, "--:--"], ["Y", 1, None]],
    }
})

def ts(hh, mm, day=15):
    """Unix timestamp for given BD wall-clock time."""
    return int(datetime.datetime(2026, 7, day, hh, mm, tzinfo=BD_TZ).timestamp())

cases = [
    # (train, hh, mm, expect_active, label)
    ("781", 6, 0,  False, "4.5h before departure -> reject"),
    ("781", 10, 5, True,  "25 min before departure -> accept"),
    ("781", 10, 0, True,  "exactly 30 min before -> accept"),
    ("781", 9, 55, False, "35 min before -> reject"),
    ("781", 12, 0, True,  "mid-journey -> accept"),
    ("781", 15, 0, True,  "1h after arrival (delay allowance) -> accept"),
    ("781", 21, 0, True,  "7h after departure, within duration+8h -> accept"),
    ("781", 23, 30, False, "13h after departure, >30m before next dep -> reject"),
    ("999", 0, 30, True,  "overnight train after midnight -> accept"),
    ("999", 4, 0,  True,  "overnight train near arrival -> accept"),
    ("999", 12, 0, True,  "overnight train at noon, within duration+8h -> accept"),
    ("999", 14, 0, False, "overnight train at 14:00, outside window -> reject"),
    ("999", 22, 40, True, "20 min before overnight departure -> accept"),
    ("555", 12, 0, True,  "no schedule data -> never gated"),
    ("nope", 12, 0, True, "unknown train -> never gated"),
]

failures = 0
for train, hh, mm, expect, label in cases:
    active, reason = t._is_journey_active(train, ts(hh, mm))
    status = "OK " if active == expect else "FAIL"
    if active != expect:
        failures += 1
    print(f"{status} {label}: active={active} {('- ' + reason) if reason else ''}")

# Scheduled position sanity
sp = t._calculate_scheduled_position("781", ts(11, 18))
print(f"scheduled position 781 @11:18 = {sp} (expect ~1.5 between stop 1 and 2)")
sp0 = t._calculate_scheduled_position("781", ts(9, 0))
print(f"scheduled position 781 @09:00 = {sp0} (expect 0.0 before start)")

sys.exit(1 if failures else 0)
