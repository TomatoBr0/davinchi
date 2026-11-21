#!/usr/bin/env python3
"""Import Da Vinci phone dataset.json exports into the offline slicer SQLite DB.

Only motion-bearing `strokes` and explicitly traced `trace` samples are imported.
Photo-only rows have no observed stroke sequence and are reported as skipped.
"""
from __future__ import annotations
import app
import argparse, json, sqlite3, sys, zipfile
from pathlib import Path


def read_export(path: Path) -> dict:
    if path.is_dir():
        raw = (path / "dataset.json").read_bytes()
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            try: raw = zf.read("dataset.json")
            except KeyError: raise ValueError("ZIP has no root dataset.json")
    else:
        raw = path.read_bytes()
    try: data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e: raise ValueError(f"Invalid dataset.json: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        raise ValueError("Expected dataset.json object with a samples array")
    return data


def normalize(row: dict) -> dict:
    if not isinstance(row, dict): raise ValueError("sample must be an object")
    label = row.get("label")
    if not isinstance(label, str) or not label.strip(): raise ValueError("missing exact label")
    kind = row.get("kind")
    if kind not in ("strokes", "trace"): raise ValueError("not a motion sample")
    src_strokes = row.get("strokes")
    if not isinstance(src_strokes, list) or not src_strokes: raise ValueError("no strokes")
    strokes = []
    for stroke in src_strokes:  # list order is the captured pen-down order; keep every lift boundary
        if not isinstance(stroke, dict) or not isinstance(stroke.get("points"), list) or not stroke["points"]:
            raise ValueError("invalid or empty stroke")
        points = []
        for p in stroke["points"]:
            if not isinstance(p, dict) or not isinstance(p.get("x"),(int,float)) or not isinstance(p.get("y"),(int,float)):
                raise ValueError("point missing coordinates")
            # Preserve coordinates and relative point times. Target schema accepts x/y/t/pressure.
            points.append({"x":p["x"], "y":p["y"], "t":p.get("t",0), "pressure":p.get("pressure") if isinstance(p.get("pressure"),(int,float)) else .5})
        strokes.append(points)
    return {"text":label.strip(), "before":row.get("before") if isinstance(row.get("before"),str) else "",
            "after":row.get("after") if isinstance(row.get("after"),str) else "", "strokes":strokes}


def import_export(export_path: Path, db_path: Path) -> dict:
    data = read_export(export_path)
    app.Store(db_path)
    db = sqlite3.connect(db_path)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS phone_imports (
            source_id TEXT PRIMARY KEY, target_id INTEGER NOT NULL)""")
        inserted=skipped=already=0
        for i,row in enumerate(data["samples"]):
            sid = row.get("id") if isinstance(row,dict) else None
            if sid is None: raise ValueError(f"missing source ID at row {i}")
            sid=str(sid)
            if db.execute("SELECT 1 FROM phone_imports WHERE source_id=?",(sid,)).fetchone():
                already+=1; continue
            if not isinstance(row,dict) or row.get("kind") not in ("strokes","trace"):
                skipped+=1; continue
            try:
                width,height=row.get("width"),row.get("height")
                if not isinstance(width,(int,float)) or width <= 0 or not isinstance(height,(int,float)) or height <= 0:
                    raise ValueError("missing valid canvas width/height")
                item=normalize(row)
                for stroke in item["strokes"]:
                    for point in stroke:
                        if point["x"] > width or point["y"] > height:
                            raise ValueError("point lies outside declared source canvas")
                item=app.validate_sample(item)
            except ValueError as e:
                # Never infer a prompt/label from adjacent rows; reject malformed motion rows.
                raise ValueError(f"sample {sid}: {e}") from e
            created=row.get("created_at")
            cur=db.execute("INSERT INTO samples(text,before_text,after_text,strokes_json,created_at) VALUES(?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))",
                (item["text"],item["before"],item["after"],json.dumps(item["strokes"],separators=(",",":")),created if isinstance(created,str) else None))
            db.execute("INSERT INTO phone_imports(source_id,target_id) VALUES(?,?)",(sid,cur.lastrowid))
            inserted+=1
        db.commit()
        return {"inserted":inserted,"already_imported":already,"skipped_non_motion":skipped}
    except Exception:
        db.rollback(); raise
    finally: db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("export",type=Path,help="phone export ZIP, extracted folder, or dataset.json")
    p.add_argument("--db",type=Path,required=True,help="target Davinchi SQLite database path")
    a=p.parse_args()
    try: print(json.dumps(import_export(a.export,a.db),sort_keys=True))
    except Exception as e: print(f"Import failed: {e}",file=sys.stderr); return 1
    return 0
if __name__=="__main__": raise SystemExit(main())
