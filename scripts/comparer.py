#!/usr/bin/env python3
import argparse
import os
import json
import pandas as pd
import requests
from collections import Counter
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from datetime import datetime
from tqdm import tqdm

# --- Disable insecure request warnings ---
disable_warnings(InsecureRequestWarning)

# --- Constants ---
CACHE_FILE = "vintage_metadata_cache.json"
DEFAULT_API_BASE = "https://api.testing.vivino.com/vintages/"
DEFAULT_GITHUB_BASE = "https://raw.githubusercontent.com/p47r1ckp3t3rs3n/vivino-test-images/main/images/"

# --- Logger ---
def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}")

# --- Fetch metadata from API ---
def fetch_vintage_metadata(vintage_id, api_base):
    try:
        url = f"{api_base}{int(vintage_id)}"
        log(f"🔄 Fetching metadata for vintage ID {vintage_id}...")
        r = requests.get(url, timeout=5, verify=False)
        r.raise_for_status()
        data = r.json()

        location = data.get("image", {}).get("location", "")
        if location.startswith("//"):
            location = location.lstrip("/")

        return {
            "wine_id": str(data.get("wine", {}).get("id")),
            "wine_name": data.get("wine", {}).get("name", ""),
            "year": str(data.get("year", "")),
            "winery_id": str(data.get("wine", {}).get("winery", {}).get("id")),
            "winery_name": data.get("wine", {}).get("winery", {}).get("name", ""),
            "image_location": location
        }
    except Exception as e:
        log(f"⚠️ Failed to fetch metadata for {vintage_id}: {e}")
        return dict.fromkeys([
            "wine_id", "wine_name", "year",
            "winery_id", "winery_name", "image_location"
        ], None)

# --- Cache helpers ---
def load_metadata_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_metadata_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

# --- Enrich dataset ---
def enrich_metadata(df, label, cache, api_base):
    for field in ["wine_id", "wine_name", "year", "winery_id", "winery_name", "image_location"]:
        df[f"{field}_{label}"] = None
    for idx, row in tqdm(df.iterrows(), total=len(df), desc=f"Enriching {label}"):
        vintage_id = row.get(f"vintage_id_{label}")
        if not vintage_id or str(vintage_id).strip().lower() in ["none", "nan", ""]:
            continue
        vintage_id = str(int(float(vintage_id)))
        if vintage_id not in cache:
            cache[vintage_id] = fetch_vintage_metadata(vintage_id, api_base)
        meta = cache[vintage_id]
        for key in meta:
            df.at[idx, f"{key}_{label}"] = meta[key]
    return df

# --- Categorization logic ---
def categorize(row, labelA, labelB):
    id_a = row.get(f"vintage_id_{labelA}")
    id_b = row.get(f"vintage_id_{labelB}")

    if not id_a or str(id_a).lower() == "none":
        id_a = None
    if not id_b or str(id_b).lower() == "none":
        id_b = None

    wine_id_a = row.get(f"wine_id_{labelA}")
    wine_id_b = row.get(f"wine_id_{labelB}")
    wine_name_a = row.get(f"wine_name_{labelA}")
    wine_name_b = row.get(f"wine_name_{labelB}")
    winery_name_a = row.get(f"winery_name_{labelA}")
    winery_name_b = row.get(f"winery_name_{labelB}")

    if not id_a and not id_b:
        return "Both failed"
    if not id_a:
        return f"Only {labelB} recognized"
    if not id_b:
        return f"Only {labelA} recognized"
    if id_a == id_b:
        if wine_id_a == wine_id_b:
            if wine_name_a == wine_name_b:
                return "Exact match"
            return "Same vintage ID, name mismatch"
        return "Same vintage ID, different wine"
    if wine_id_a == wine_id_b:
        return "Same wine, different vintage"
    if winery_name_a == winery_name_b:
        return "Same winery, different wine"
    return "Completely different"

# --- File label fallback ---
def infer_label(filename, default):
    parts = os.path.basename(filename).split("_")
    return parts[1] if len(parts) >= 2 else default

# --- Main comparison logic ---
def compare_results(fileA, fileB, output_xlsx, use_cache=False, api_base=DEFAULT_API_BASE, github_base=DEFAULT_GITHUB_BASE):
    labelA = infer_label(fileA, "A")
    labelB = infer_label(fileB, "B")

    log(f"📂 Loading {fileA} and {fileB}...")
    dfA = pd.read_csv(fileA, keep_default_na=False)
    dfB = pd.read_csv(fileB, keep_default_na=False)
    dfA.rename(columns={dfA.columns[0]: "file"}, inplace=True)
    dfB.rename(columns={dfB.columns[0]: "file"}, inplace=True)
    dfA = dfA.rename(columns={col: f"{col}_{labelA}" for col in dfA.columns if col != "file"})
    dfB = dfB.rename(columns={col: f"{col}_{labelB}" for col in dfB.columns if col != "file"})
    df = pd.merge(dfA, dfB, on="file", how="outer")

    for label in [labelA, labelB]:
        for col in [f"match_status_{label}", f"integrity_issue_{label}"]:
            if col not in df.columns:
                df[col] = ""
            else:
                df[col] = df[col].astype(str)

    cache = load_metadata_cache() if use_cache else {}
    df = enrich_metadata(df, labelA, cache, api_base)
    df = enrich_metadata(df, labelB, cache, api_base)
    if use_cache:
        save_metadata_cache(cache)

    df["category"] = df.apply(lambda row: categorize(row, labelA, labelB), axis=1)
    df["original_image_url"] = df["file"].apply(lambda f: f"{github_base}{f}")
    df[f"{labelA}_match_url"] = df[f"vintage_id_{labelA}"].apply(
        lambda x: f"https://www.vivino.com/wines/{int(x)}" if pd.notna(x) and str(x).strip().isdigit() else ""
    )
    df[f"{labelB}_match_url"] = df[f"vintage_id_{labelB}"].apply(
        lambda x: f"https://www.vivino.com/wines/{int(x)}" if pd.notna(x) and str(x).strip().isdigit() else ""
    )
    df["preferred_system"] = ""
    df["target_match_url"] = ""

    side_by_side_order = [
        "file", "category", "preferred_system", "target_match_url",
        f"label_ocr_{labelA}", f"label_ocr_{labelB}",
        f"label_ocr_source_{labelA}", f"label_ocr_source_{labelB}",
        f"wine_name_{labelA}", f"wine_name_{labelB}",
        f"year_{labelA}", f"year_{labelB}",
        f"winery_name_{labelA}", f"winery_name_{labelB}",
        "original_image_url", f"{labelA}_match_url", f"{labelB}_match_url",
        f"image_location_{labelA}", f"image_location_{labelB}",
        f"vintage_id_{labelA}", f"vintage_id_{labelB}",
        f"wine_id_{labelA}", f"wine_id_{labelB}",
        f"winery_id_{labelA}", f"winery_id_{labelB}",
        f"user_vintage_id_{labelA}", f"user_vintage_id_{labelB}",
        f"processing_id_{labelA}", f"processing_id_{labelB}",
        f"match_status_{labelA}", f"match_status_{labelB}",
        f"status_{labelA}", f"status_{labelB}",
        f"upload_status_{labelA}", f"upload_status_{labelB}",
        f"id_{labelA}", f"id_{labelB}",
        f"match_message_{labelA}", f"match_message_{labelB}",
        f"upload_duration_ms_{labelA}", f"upload_duration_ms_{labelB}",
        f"total_duration_ms_{labelA}", f"total_duration_ms_{labelB}",
        f"fetch_duration_ms_{labelA}", f"fetch_duration_ms_{labelB}",
        f"run_label_{labelA}", f"run_label_{labelB}",
        f"contradiction_{labelA}", f"contradiction_{labelB}",
        f"integrity_issue_{labelA}", f"integrity_issue_{labelB}",
        f"error_{labelA}", f"error_{labelB}"
    ]
    other_cols = [col for col in df.columns if col not in side_by_side_order]
    df = df[[col for col in side_by_side_order if col in df.columns] + other_cols]

    print("\n📊 Match Categorization Summary")
    counts = Counter(df["category"])
    for cat, count in counts.items():
        print(f"{cat:30s}: {count:3d} ({100 * count / len(df):.1f}%)")

    for label in [labelA, labelB]:
        count = df[f"integrity_issue_{label}"].apply(lambda x: x not in ["", "None", "nan"]).sum()
        print(f"🔎 {label}: {count} rows with integrity issues")

    df.to_excel(output_xlsx, index=False)
    print(f"\n✅ Results written to {output_xlsx}")

# --- Entry point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two image recognition scan results using Vivino metadata")
    parser.add_argument("fileA", help="CSV from system A (e.g. clip)")
    parser.add_argument("fileB", help="CSV from system B (e.g. vuforia)")
    parser.add_argument("--output", default="comparison_results.xlsx", help="Output Excel file")
    parser.add_argument("--use-cache", action="store_true", help="Use cached metadata")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Vivino API base URL")
    parser.add_argument("--github-base", default=DEFAULT_GITHUB_BASE, help="GitHub image base URL")
    args = parser.parse_args()

    compare_results(args.fileA, args.fileB, args.output, args.use_cache, args.api_base, args.github_base)
