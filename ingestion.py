import json
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
INPUT = BASE / "data" / "traffic.csv"
OUTPUT = BASE / "data" / "processed_traffic.csv"
META = BASE / "data" / "metadata.json"

REQUIRED = ["DateTime", "Junction", "Vehicles"]

def main():
    df = pd.read_csv(INPUT)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
    df["Junction"] = pd.to_numeric(df["Junction"], errors="coerce")
    df["Vehicles"] = pd.to_numeric(df["Vehicles"], errors="coerce")

    # Remove invalid rows and duplicates.
    df = df.dropna(subset=REQUIRED).drop_duplicates(subset=["DateTime", "Junction"])
    df["Junction"] = df["Junction"].astype(int)
    df["Vehicles"] = df["Vehicles"].astype(int)
    df = df.sort_values(["Junction", "DateTime"]).reset_index(drop=True)

    # Congestion is a project-derived label based only on vehicle volume
    # within each junction. It is NOT a measured traffic-density value.
    q = df.groupby("Junction")["Vehicles"].transform(
        lambda s: s.quantile([0.33, 0.66]).values[0]
        if len(s) else 0
    )
    # Calculate robust per-junction thresholds separately.
    thresholds = df.groupby("Junction")["Vehicles"].quantile([0.33, 0.66]).unstack()
    thresholds.columns = ["low_threshold", "high_threshold"]
    df = df.merge(thresholds, left_on="Junction", right_index=True, how="left")
    df["CongestionLevel"] = "Medium"
    df.loc[df["Vehicles"] <= df["low_threshold"], "CongestionLevel"] = "Low"
    df.loc[df["Vehicles"] >= df["high_threshold"], "CongestionLevel"] = "High"

    # Historical version number: each timestamped state at a junction.
    df["Version"] = df.groupby("Junction").cumcount() + 1
    df["StateID"] = (
        "J" + df["Junction"].astype(str) + "-V" + df["Version"].astype(str)
    )

    df.to_csv(OUTPUT, index=False, date_format="%Y-%m-%d %H:%M:%S")

    metadata = {
        "source_file": "data/traffic.csv",
        "rows_after_cleaning": int(len(df)),
        "columns": list(pd.read_csv(INPUT, nrows=0).columns),
        "junctions": sorted(df["Junction"].unique().tolist()),
        "start_time": str(df["DateTime"].min()),
        "end_time": str(df["DateTime"].max()),
        "notes": [
            "The source dataset contains DateTime, Junction, Vehicles and ID.",
            "CongestionLevel is derived from vehicle-count quantiles within each junction.",
            "No speed, density, accident, weather or GPS fields are present in the source dataset."
        ]
    }
    META.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Processed {len(df):,} rows.")
    print(f"Saved: {OUTPUT}")

if __name__ == "__main__":
    main()
