# Big Data Time Machine — Polished Verified Version

This version uses the supplied traffic dataset and includes the historical modification/audit-log feature.

## Run on Windows
1. Open CMD/PowerShell in this folder.
2. If this is a fresh machine, install dependencies once: `pip install -r requirements.txt`
3. If `data/processed_traffic.csv` already exists, run `python app.py`.
4. Open `http://127.0.0.1:5000`.

## Modification demonstration
1. Select a Junction and a timestamp.
2. Click **Travel Back**.
3. In **Modify Historical Traffic**, enter a new Vehicles value and/or Congestion level.
4. Enter a reason.
5. Click **Save Modification**.
6. Click **Travel Back** again using the same timestamp.
7. The changed historical state and its audit log will appear.

The audit log is stored in `data/modification_log.csv`. A backup of the active processed dataset is created before each edit.

### Important
Do not run `python ingestion.py` after making manual historical modifications unless you intentionally want to rebuild `processed_traffic.csv` from the original `traffic.csv`; ingestion regenerates the processed dataset.

## Features
- Dataset overview
- Historical time travel
- Junction traffic trend
- Unusual vehicle-change detection
- Historical traffic modification
- Modification audit log
- CSV export
- Responsive dark analytics UI
### Updated unusual-activity behavior
- Automatic anomalies are detected from consecutive traffic records using a 50% change threshold.
- A manual `Vehicles` modification is also flagged as unusual when the old-to-new value changes by 50% or more.
- Example: 14 → 70 is a 400% increase and appears in Unusual Activities with source `Historical Modification`.
- The header status now shows `TIME TRAVEL READY` instead of `MODIFICATION ENABLED`.

To deploy the site 
https://big-data-time-machine.onrender.com/
