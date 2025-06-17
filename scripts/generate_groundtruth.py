import os
import csv
import json
import re
import requests
import argparse
from datetime import datetime
from typing import Dict, List


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def sanitize_filename(url: str) -> str:
    return os.path.basename(url)


def download_image(url: str, output_dir: str) -> str:
    filename = sanitize_filename(url)
    path = os.path.join(output_dir, filename)

    if not os.path.exists(path):
        try:
            print(f"⬇️  Downloading: {url}")
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            print(f"❌ Failed to download {url}: {e}")
            return None
    return filename


def parse_csv(csv_path: str, image_dir: str, added_by: str, skip_download: bool) -> List[Dict]:
    if not os.path.exists(csv_path):
        print(f"⚠️ CSV file not found: {csv_path}")
        return []

    entries = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("image") or not row.get("expected_vintage_id"):
                continue
            if skip_download:
                filename = sanitize_filename(row["image_url"])
            else:
                filename = download_image(row["image_url"], image_dir)
                if not filename:
                    continue
            entry = {
                "filename": filename,
                "image_url": row["image_url"],
                "expected_vintage_id": int(row["expected_vintage_id"]),
                "added_by": added_by,
                "added_at": row.get("created_at", datetime.utcnow().isoformat() + "Z"),
                "tags": ["verified"],
                "source": "label_scan_verifications",
                "notes": f"verification_id: {row.get('label_scan_verifications_id', '')}"
            }
            entries.append(entry)
    return entries


def parse_curl_line(curl_str: str, added_by: str) -> Dict:
    file_match = re.search(r"-F\s+'image=@.*?([\\/]?([\w:-]+_image))'", curl_str)
    fallback_name = f"unknown_image_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.JPG"
    filename = file_match.group(2) + ".JPG" if file_match else fallback_name

    metadata = {
        "filename": filename,
        "added_by": added_by,
        "added_at": datetime.utcnow().isoformat() + "Z",
        "tags": [],
        "source": "curl_test"
    }

    url_params = re.findall(r'[?&]([^=]+)=([^&\'"]+)', curl_str)
    crop = {}
    for key, val in url_params:
        if key == "label_ocr":
            metadata["ocr_text"] = val
            metadata["tags"].append("ocr")
        elif key.startswith("crop_"):
            crop[key[5:]] = float(val)
        elif key == "label_ocr_source" and val.lower() == "vision":
            metadata["tags"].append("ocr")

    if crop:
        metadata["crop"] = {
            "x": crop.get("x", 0),
            "y": crop.get("y", 0),
            "width": crop.get("width", 1),
            "height": crop.get("height", 1),
        }
        metadata["tags"].append("requires_crop")

    metadata["tags"] = sorted(set(metadata["tags"]))
    return metadata


def parse_curls(curl_path: str, added_by: str) -> List[Dict]:
    if not os.path.exists(curl_path):
        print(f"⚠️ cURL file not found: {curl_path}")
        return []

    entries = []
    with open(curl_path, "r", encoding="utf-8") as f:
        for line in f:
            if "curl" not in line:
                continue
            entry = parse_curl_line(line.strip(), added_by)
            entries.append(entry)
    return entries


def write_jsonl(entries: List[Dict], out_dir: str) -> str:
    ensure_dir(out_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(out_dir, f"labels_{timestamp}.jsonl")
    with open(output_path, "w", encoding="utf-8") as f_out:
        for entry in entries:
            json.dump(entry, f_out, ensure_ascii=False)
            f_out.write("\n")
    print(f"\n✅ Saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Input CSV file with DB exported labels")
    parser.add_argument("--curls", help="Input file with raw curl POSTs")
    parser.add_argument("--out-dir", required=True, help="Directory to store images + output jsonl")
    parser.add_argument("--added-by", default="patrick", help="Author tag")
    parser.add_argument("--skip-download", action="store_true", help="Only generate metadata, don't download images")

    args = parser.parse_args()

    all_entries = []
    image_dir = os.path.join(args.out_dir, "images")

    if args.csv:
        ensure_dir(image_dir)
        all_entries.extend(parse_csv(args.csv, image_dir, args.added_by, args.skip_download))

    if args.curls:
        all_entries.extend(parse_curls(args.curls, args.added_by))

    if not all_entries:
        print("⚠️  No entries created. Check inputs.")
    else:
        write_jsonl(all_entries, args.out_dir)
