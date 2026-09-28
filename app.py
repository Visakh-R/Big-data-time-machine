from pathlib import Path
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
TRAFFIC = DATA / "processed_traffic.csv"
BACKUP = DATA / "processed_traffic_before_modification.csv"
EVENTS = DATA / "events.csv"
MODLOG = DATA / "modification_log.csv"

app = Flask(__name__)

def load_traffic():
    if not TRAFFIC.exists():
        raise FileNotFoundError("processed_traffic.csv not found. Run ingestion.py first.")
    df = pd.read_csv(TRAFFIC, parse_dates=["DateTime"])
    return df.sort_values(["Junction", "DateTime"]).reset_index(drop=True)

def save_traffic(df):
    # Keep the active historical dataset in one CSV. A backup is created before each edit.
    if TRAFFIC.exists():
        import shutil
        shutil.copy2(TRAFFIC, BACKUP)
    df.sort_values(["Junction", "DateTime"]).to_csv(
        TRAFFIC, index=False, date_format="%Y-%m-%d %H:%M:%S"
    )

def load_events():
    if not EVENTS.exists():
        return pd.DataFrame(columns=["DateTime", "Junction", "EventType", "Description"])
    return pd.read_csv(EVENTS, parse_dates=["DateTime"])

def load_modlog():
    if not MODLOG.exists():
        return pd.DataFrame(columns=[
            "ModificationTime", "HistoricalDateTime", "Junction",
            "Field", "OldValue", "NewValue", "Reason"
        ])
    return pd.read_csv(MODLOG)

def append_modification(hist_dt, junction, field, old, new, reason):
    log = load_modlog()
    entry = pd.DataFrame([{
        "ModificationTime": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "HistoricalDateTime": pd.Timestamp(hist_dt).strftime("%Y-%m-%d %H:%M:%S"),
        "Junction": int(junction),
        "Field": field,
        "OldValue": old,
        "NewValue": new,
        "Reason": reason or "Manual historical data modification"
    }])
    pd.concat([log, entry], ignore_index=True).to_csv(MODLOG, index=False)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/locations")
def locations():
    df = load_traffic()
    return jsonify(sorted(df["Junction"].astype(int).unique().tolist()))

@app.route("/api/historical")
def historical():
    junction = request.args.get("junction", type=int)
    dt = request.args.get("datetime")
    if junction is None or not dt:
        return jsonify({"error": "junction and datetime are required"}), 400

    target = pd.to_datetime(dt, errors="coerce")
    if pd.isna(target):
        return jsonify({"error": "Invalid datetime"}), 400

    df = load_traffic()
    subset = df[(df["Junction"] == junction) & (df["DateTime"] <= target)]
    if subset.empty:
        return jsonify({"error": "No historical state exists at or before that time"}), 404

    row = subset.iloc[-1]
    logs = load_modlog()
    state_time = pd.Timestamp(row["DateTime"]).strftime("%Y-%m-%d %H:%M:%S")
    if not logs.empty:
        log_times = pd.to_datetime(logs["HistoricalDateTime"], errors="coerce")
        state_logs = logs[(logs["Junction"].astype(int) == junction) & (log_times == pd.Timestamp(row["DateTime"]))]
    else:
        state_logs = logs

    return jsonify({
        "junction": int(row["Junction"]),
        "requested_time": str(target),
        "actual_state_time": str(row["DateTime"]),
        "vehicles": int(row["Vehicles"]),
        "congestion_level": row["CongestionLevel"],
        "version": int(row["Version"]),
        "state_id": row["StateID"],
        "modifications": state_logs.fillna("").to_dict("records")
    })

@app.route("/api/modify", methods=["POST"])
def modify():
    payload = request.get_json(silent=True) or {}
    junction = payload.get("junction")
    dt = payload.get("datetime")
    reason = payload.get("reason", "").strip()
    vehicles = payload.get("vehicles")
    congestion = payload.get("congestion_level")

    if junction is None or not dt:
        return jsonify({"error": "junction and datetime are required"}), 400

    target = pd.to_datetime(dt, errors="coerce")
    if pd.isna(target):
        return jsonify({"error": "Invalid datetime"}), 400

    df = load_traffic()
    mask = (df["Junction"].astype(int) == int(junction)) & (df["DateTime"] == target)
    if not mask.any():
        return jsonify({"error": "No exact historical record exists for that junction and time"}), 404

    idx = df.index[mask][0]
    changes = []

    if vehicles not in (None, ""):
        try:
            new_vehicles = int(vehicles)
            if new_vehicles < 0:
                raise ValueError
        except Exception:
            return jsonify({"error": "Vehicles must be a non-negative whole number"}), 400
        old = int(df.at[idx, "Vehicles"])
        if old != new_vehicles:
            df.at[idx, "Vehicles"] = new_vehicles
            changes.append(("Vehicles", old, new_vehicles))

    if congestion:
        congestion = str(congestion).title()
        if congestion not in {"Low", "Medium", "High"}:
            return jsonify({"error": "Congestion must be Low, Medium or High"}), 400
        old = str(df.at[idx, "CongestionLevel"])
        if old != congestion:
            df.at[idx, "CongestionLevel"] = congestion
            changes.append(("CongestionLevel", old, congestion))

    if not changes:
        return jsonify({"error": "No change was made. Enter a new value for Vehicles or choose a different Congestion level."}), 400

    save_traffic(df)
    for field, old, new in changes:
        append_modification(target, int(junction), field, old, new, reason)

    return jsonify({
        "message": "Historical state modified and logged.",
        "changes": [{"field": f, "old": o, "new": n} for f, o, n in changes]
    })

@app.route("/api/modifications")
def modifications():
    junction = request.args.get("junction", type=int)
    dt = request.args.get("datetime")
    logs = load_modlog()
    if logs.empty:
        return jsonify([])
    if junction is not None:
        logs = logs[logs["Junction"].astype(int) == junction]
    if dt:
        target = pd.to_datetime(dt, errors="coerce")
        if not pd.isna(target):
            log_times = pd.to_datetime(logs["HistoricalDateTime"], errors="coerce")
            logs = logs[log_times == target]
    return jsonify(logs.fillna("").to_dict("records"))

@app.route("/api/trend")
def trend():
    junction = request.args.get("junction", type=int)
    if junction is None:
        return jsonify({"error": "junction is required"}), 400
    df = load_traffic()
    subset = df[df["Junction"] == junction].copy()
    if subset.empty:
        return jsonify([])
    if len(subset) > 1000:
        subset = subset.iloc[::max(1, len(subset)//1000)]
    return jsonify([
        {"time": str(r.DateTime), "vehicles": int(r.Vehicles), "congestion": r.CongestionLevel}
        for r in subset.itertuples()
    ])

@app.route("/api/compare")
def compare():
    junction = request.args.get("junction", type=int)
    t1 = request.args.get("time1")
    t2 = request.args.get("time2")
    if junction is None or not t1 or not t2:
        return jsonify({"error": "junction, time1 and time2 are required"}), 400
    df = load_traffic()
    def state_at(target):
        target = pd.to_datetime(target, errors="coerce")
        if pd.isna(target):
            return None
        s = df[(df["Junction"] == junction) & (df["DateTime"] <= target)]
        if s.empty:
            return None
        r = s.iloc[-1]
        return {
            "time": str(r.DateTime), "vehicles": int(r.Vehicles),
            "congestion_level": r.CongestionLevel,
            "version": int(r.Version), "state_id": r.StateID
        }
    return jsonify({"first": state_at(t1), "second": state_at(t2)})

@app.route("/api/anomalies")
def anomalies():
    """Return automatic anomalies plus significant manual vehicle modifications."""
    junction = request.args.get("junction", type=int)
    df = load_traffic()
    if junction is not None:
        df = df[df["Junction"] == junction]
    df = df.copy()
    df["previous"] = df.groupby("Junction")["Vehicles"].shift(1)
    df["change_pct"] = (df["Vehicles"] - df["previous"]) / df["previous"] * 100

    records = []
    auto = df[df["change_pct"].abs() >= 50]
    for r in auto.itertuples():
        records.append({
            "time": pd.Timestamp(r.DateTime).strftime("%Y-%m-%d %H:%M:%S"),
            "junction": int(r.Junction), "vehicles": int(r.Vehicles),
            "change_pct": None if pd.isna(r.change_pct) else round(float(r.change_pct), 2),
            "source": "Automatic Traffic Change", "old_value": None,
            "new_value": None, "reason": ""
        })

    # A manual change is also unusual when it changes Vehicles by 50% or more,
    # even if the old value was not the immediately previous chronological value.
    logs = load_modlog()
    if not logs.empty:
        logs["JunctionNum"] = pd.to_numeric(logs["Junction"], errors="coerce")
        logs["OldValueNum"] = pd.to_numeric(logs["OldValue"], errors="coerce")
        logs["NewValueNum"] = pd.to_numeric(logs["NewValue"], errors="coerce")
        logs["HistoricalDateTimeParsed"] = pd.to_datetime(logs["HistoricalDateTime"], errors="coerce")
        modified = logs[
            (logs["Field"] == "Vehicles") & logs["JunctionNum"].notna()
            & logs["HistoricalDateTimeParsed"].notna()
            & logs["OldValueNum"].notna() & logs["NewValueNum"].notna()
        ]
        if junction is not None:
            modified = modified[modified["JunctionNum"].astype(int) == int(junction)]

        for r in modified.itertuples():
            old, new = float(r.OldValueNum), float(r.NewValueNum)
            if old == 0:
                change_pct = None
                unusual = new != 0
            else:
                change_pct = ((new - old) / old) * 100
                unusual = abs(change_pct) >= 50
            if unusual:
                records.append({
                    "time": r.HistoricalDateTimeParsed.strftime("%Y-%m-%d %H:%M:%S"),
                    "junction": int(r.JunctionNum), "vehicles": int(new),
                    "change_pct": None if change_pct is None else round(change_pct, 2),
                    "source": "Historical Modification", "old_value": int(old),
                    "new_value": int(new), "reason": str(r.Reason)
                })

    records.sort(key=lambda x: (x["time"], x["junction"]), reverse=True)
    unique, seen = [], set()
    for item in records:
        key = (item["time"], item["junction"], item["source"], item["new_value"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return jsonify(unique[:50])


@app.route("/api/events")
def events():
    df = load_events()
    if df.empty:
        return jsonify([])
    return jsonify([
        {"time": str(r.DateTime), "junction": int(r.Junction),
         "event_type": r.EventType, "description": r.Description}
        for r in df.itertuples()
    ])

@app.route("/api/summary")
def summary():
    df = load_traffic()
    return jsonify({
        "rows": int(len(df)), "junctions": int(df["Junction"].nunique()),
        "start": str(df["DateTime"].min()), "end": str(df["DateTime"].max()),
        "max_vehicles": int(df["Vehicles"].max()),
        "avg_vehicles": round(float(df["Vehicles"].mean()), 2),
        "modifications": int(len(load_modlog()))
    })

@app.route("/api/export")
def export():
    return send_file(TRAFFIC, as_attachment=True, download_name="processed_traffic.csv")

@app.route("/api/export-log")
def export_log():
    return send_file(MODLOG, as_attachment=True, download_name="modification_log.csv")

if __name__ == "__main__":
    print("============================================================")
    print(" BIG DATA TIME MACHINE - VERIFIED MODIFICATION VERSION")
    print(" Modification feature: ENABLED")
    print(" Open: http://127.0.0.1:5000")
    print(" Look for: MODIFY HISTORICAL TRAFFIC")
    print("============================================================")
    app.run(debug=False, use_reloader=False)
