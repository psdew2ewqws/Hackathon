"""Synthetic detector counts generator — shape, schema, realism sanity."""

from __future__ import annotations

from datetime import date

import pyarrow.parquet as pq

from traffic_intel_sandbox.synth.detector_counts import SCHEMA, generate


def test_generate_shape(tmp_path, profiles_yml):
    out_dir = tmp_path / "counts"
    written = generate(
        profiles_path=profiles_yml,
        out_dir=out_dir,
        days=3,
        start_date=date(2026, 4, 1),
        intersection_id="TEST1",
        seed=7,
    )
    assert len(written) == 3
    for path in written:
        table = pq.read_table(path)
        assert table.schema.equals(SCHEMA), f"schema drift in {path.name}"
        assert table.num_rows == 22 * 96, f"{path.name}: expected 22*96 rows, got {table.num_rows}"
        # No nulls anywhere
        for col in table.column_names:
            assert table.column(col).null_count == 0, f"{path.name}: nulls in {col}"


def test_determinism(tmp_path, profiles_yml):
    a = generate(profiles_yml, tmp_path / "a", days=1, start_date=date(2026, 4, 1),
                 intersection_id="X", seed=42)
    b = generate(profiles_yml, tmp_path / "b", days=1, start_date=date(2026, 4, 1),
                 intersection_id="X", seed=42)
    ta, tb = pq.read_table(a[0]), pq.read_table(b[0])
    assert ta.to_pandas().equals(tb.to_pandas()), "same seed must yield identical counts"


def test_weekday_more_than_weekend(tmp_path, profiles_yml):
    # Pick a known weekday (Tue) and the following Sat
    tue = date(2026, 4, 7)    # Tuesday
    sat = date(2026, 4, 11)   # Saturday
    written = generate(profiles_yml, tmp_path / "mix", days=5,
                       start_date=tue, intersection_id="X", seed=3)
    by_day = {p.name.split("_")[1].split(".")[0]: pq.read_table(p).to_pandas() for p in written}
    tue_total = by_day[tue.isoformat()]["vehicle_count"].sum()
    sat_total = by_day[sat.isoformat()]["vehicle_count"].sum()
    # Config says weekday 1.0 vs weekend 0.55, so a healthy gap is expected.
    assert tue_total > sat_total, f"weekday ({tue_total}) should exceed weekend ({sat_total})"


def test_am_and_pm_peaks_present(tmp_path, profiles_yml):
    written = generate(profiles_yml, tmp_path / "p", days=1,
                       start_date=date(2026, 4, 7), intersection_id="X", seed=9)
    df = pq.read_table(written[0]).to_pandas()
    # Aggregate across detectors per bin, find peaks in AM (06-10) and PM (16-19).
    by_hour = df.copy()
    by_hour["hour"] = by_hour["timestamp"].dt.hour
    hourly = by_hour.groupby("hour")["vehicle_count"].sum()
    am_max_hour = hourly.loc[6:10].idxmax()
    pm_max_hour = hourly.loc[16:19].idxmax()
    assert 7 <= am_max_hour <= 9, f"AM peak fell at hour {am_max_hour}"
    assert 17 <= pm_max_hour <= 18, f"PM peak fell at hour {pm_max_hour}"
