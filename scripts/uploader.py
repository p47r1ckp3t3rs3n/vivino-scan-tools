# === BASE: uploader.py ===
import os
import time
import csv
import json
import requests
from urllib.parse import urlparse
import argparse
from collections import defaultdict
from getpass import getpass
from datetime import datetime
from statistics import mean
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List
import urllib3
import tempfile

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Constants ---
DEFAULT_TIMEOUT = 10
MAX_FETCH_RETRIES = 100
FETCH_DELAY = 0.5

# --- CLI Prompts ---
def prompt_if_missing(value: Optional[str], prompt_text: str, is_password: bool = False) -> str:
    if value:
        return value
    return getpass(prompt_text) if is_password else input(prompt_text)

# --- Authentication ---
def get_auth_token(env: str, email: str, password: str) -> tuple[str, str]:
    creds = {
        "prod": ("TESTING_ID_FOR_GO-API", "TESTING_SECRET_FOR_GO-API"),
        "testing": ("TESTING_ID_FOR_GO-API", "TESTING_SECRET_FOR_GO-API"),
        "stable": ("TESTING_ID_FOR_GO-API", "TESTING_SECRET_FOR_GO-API")
    }
    base_urls = {
        "prod": "https://api.vivino.com",
        "testing": "https://api.testing.vivino.com",
        "stable": "https://api.stable.vivino.com"
    }
    client_id, client_secret = creds[env]
    base_url = base_urls[env]
    url = f"{base_url}/oauth/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "password",
        "username": email,
        "password": password
    }
    print("\n🔐 [DEBUG] Auth Request:")
    print(f"POST {url}")
    for k, v in data.items():
        print(f"  {k}: {'*' * len(v) if k == 'password' else v}")
    try:
        print(f"[DEBUG] Full auth request: {json.dumps(data)}")
        response = requests.post(url, data=data, verify=False)
        print(f"🔍 [DEBUG] Status code: {response.status_code}")
        print(f"🧾 [DEBUG] Response body: {response.text}")
        response.raise_for_status()
        return response.json()["access_token"], base_url
    except requests.RequestException as e:
        print(f"❌ [ERROR] Auth failed: {e}")
        raise

# --- Logger ---
def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}")

# --- Detect contradictions ---
def detect_contradictions(data: Dict[str, Any]) -> Optional[str]:
    issues = []
    if data.get("match_status") is None and data.get("vintage_id"):
        issues.append("vintage_id present despite match_status=None")
    if data.get("upload_status") != "Completed" and data.get("vintage_id"):
        issues.append("vintage_id present despite incomplete upload")
    if data.get("match_status") == "Matched" and not data.get("vintage_id"):
        issues.append("match_status=Matched but vintage_id is null")
    return "; ".join(issues) if issues else None

# --- Integrity check ---
def verify_integrity(label_id: int, user_vintage_id: int, base_url: str, token: str) -> Optional[str]:
    label_url = f"{base_url}/v/9.0.0/scans/v2/label/{label_id}"
    uv_url = f"{base_url}/v/9.1.1/user_vintages/{user_vintage_id}"
    headers = {"Authorization": f"Bearer {token}"}
    issues = []
    try:
        label_data = requests.get(label_url, headers=headers, timeout=DEFAULT_TIMEOUT, verify=False).json()
        uv_data = requests.get(uv_url, headers=headers, timeout=DEFAULT_TIMEOUT, verify=False).json()
    except Exception as e:
        return f"Integrity check failed: {e}"
    if label_data.get("id") != label_id:
        issues.append("Label ID mismatch")
    if label_data.get("user_vintage_id") != user_vintage_id:
        issues.append("label.user_vintage_id != userVintage.id")
    if uv_data.get("label_id") != label_id:
        issues.append("userVintage.label_id != label.id")
    if label_data.get("match_status") == "Matched" and not label_data.get("vintage_id"):
        issues.append("match_status=Matched but vintage_id is null")
    if not label_data.get("image") and not uv_data.get("image"):
        issues.append("No image in either label or user_vintage")
    return "; ".join(issues) if issues else None

# --- Metadata Loader ---
def load_metadata(filepath_or_url: str) -> Dict[str, Dict[str, Any]]:
    if not filepath_or_url:
        return {}

    if filepath_or_url.startswith("http"):
        if "github.com" in filepath_or_url and "raw.githubusercontent.com" not in filepath_or_url:
            filepath_or_url = filepath_or_url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")

        try:
            log(f"🌐 Downloading metadata from: {filepath_or_url}")
            response = requests.get(filepath_or_url, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as tmp:
                tmp.write(response.text)
                tmp.flush()
                filepath_or_url = tmp.name
        except Exception as e:
            log(f"❌ Failed to download metadata: {e}")
            return {}

    if not os.path.exists(filepath_or_url):
        log(f"❌ Metadata file not found: {filepath_or_url}")
        return {}

    metadata = {}
    with open(filepath_or_url, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    meta = json.loads(line)
                    key = os.path.basename(meta.get("filename", ""))
                    metadata[key] = meta
                except json.JSONDecodeError as e:
                    log(f"⚠️ Skipping invalid JSON line: {e}")
    return metadata

# --- Image Fetchers ---
def get_image_files_from_folder(folder_path: str) -> List[str]:
    return [
        os.path.join(root, file)
        for root, _, files in os.walk(folder_path)
        for file in files if file.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

def get_image_urls_from_github(subfolder: str = "") -> List[str]:
    if subfolder.startswith("http"):
        parsed = urlparse(subfolder)
        try:
            parts = parsed.path.split("/images/")
            if len(parts) > 1:
                subfolder = parts[1].strip("/")
                log(f"✅ Normalized GitHub folder: {subfolder}")
            else:
                raise ValueError("Could not parse subfolder from GitHub URL")
        except Exception as e:
            log(f"❌ Failed to extract subfolder from GitHub URL: {e}")
            return []

    folder = f"images/{subfolder.strip('/')}" if subfolder else "images"
    api_url = f"https://api.github.com/repos/p47r1ckp3t3rs3n/vivino-test-images/contents/{folder}"
    raw_base = f"https://raw.githubusercontent.com/p47r1ckp3t3rs3n/vivino-test-images/main/{folder}"
    log(f"🌐 Fetching image list from GitHub folder: {subfolder}")
    try:
        r = requests.get(api_url, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        files = r.json()
        log(f"📦 Found {len(files)} images in GitHub folder.")
        return [f"{raw_base}/{f['name']}" for f in files if f['name'].lower().endswith((".jpg", ".jpeg", ".png"))]
    except Exception as e:
        log(f"[ERROR] GitHub fetch failed: {e}")
        return []

# --- Upload & Fetch Logic ---
def upload_and_fetch(image_input: str, token: str, base_url: str, metadata: Dict[str, Any], label: str, local_mode: bool, inject_ocr: bool) -> Dict[str, Any]:
    filename = os.path.basename(image_input)
    meta = metadata.get(filename, {})
    headers = {"Authorization": f"Bearer {token}"}
    upload_url = f"{base_url}/v/10.0.0/scans/label?image_type=jpg&add_user_vintage=true&queue_tier_matching=false"
    fetch_url_template = f"{base_url}/v/9.0.0/scans/v2/label/{{processing_id}}?user_id=3&language=en"

    try:
        image_bytes = (
            open(image_input, "rb").read() if local_mode
            else requests.get(image_input, timeout=DEFAULT_TIMEOUT).content
        )
    except Exception as e:
        log(f"[DOWNLOAD] 💥 {filename} | {e}")
        return {"file": filename, "status": "fail", "error": str(e), "run_label": label}

    try:
        upload_start = time.time()
        
        files = {
            "image": (filename, image_bytes, "image/jpeg")
        }
        label_ocr = meta.get("ocr_text") if inject_ocr else None

        query_params = {
            "image_type": "jpg",
            "add_user_vintage": "true",
            "queue_tier_matching": "false"
        }

        if label_ocr:
            query_params["label_ocr"] = label_ocr
            query_params["label_ocr_source"] = "vision"
            log(f"[✏️ OCR] Injecting OCR for {filename}")

        from urllib.parse import urlencode, quote_plus
        upload_url = f"{base_url}/v/10.0.0/scans/label?" + "&".join(f"{k}={quote_plus(str(v))}" for k, v in query_params.items())

        log(f"[DEBUG] Final upload URL: {upload_url}")

        resp = requests.post(upload_url, headers=headers, files=files, timeout=DEFAULT_TIMEOUT, verify=False)
        upload_end = time.time()
        upload_ms = round((upload_end - upload_start) * 1000)
        
        if resp.status_code != 200:
            log(f"[UPLOAD] ❌ {filename} | HTTP {resp.status_code}")
            return {"file": filename, "status": resp.status_code, "error": resp.text, "run_label": label}
        
        processing_id = resp.json().get("processing_id")
        log(f"[UPLOAD] ✅ {filename} | processing_id={processing_id}")
    except Exception as e:
        return {"file": filename, "status": "fail", "error": f"Upload failed: {e}", "run_label": label}


    for attempt in range(MAX_FETCH_RETRIES):
        try:
            fetch_start = time.time()
            r = requests.get(fetch_url_template.format(processing_id=processing_id), headers=headers, timeout=DEFAULT_TIMEOUT, verify=False)
            fetch_duration = round((time.time() - fetch_start) * 1000)
            if r.status_code == 200:
                data = r.json()
                contradiction = detect_contradictions(data)
                integrity_issue = None
                if data.get("id") and data.get("user_vintage_id"):
                    log(f"[🔄 CROSS-REF] {filename} | Validating /label/{data['id']} ↔ /user_vintages/{data['user_vintage_id']}")
                    integrity_issue = verify_integrity(data["id"], data["user_vintage_id"], base_url, token)
                total_ms = round((time.time() - upload_start) * 1000)
                log(f"[⏱️ PERFORM] {filename} | Upload: {upload_ms} ms | Fetch: {fetch_duration} ms | Total: {total_ms} ms")
                return {
                    "file": filename,
                    "status": 200,
                    "processing_id": processing_id,
                    "upload_status": data.get("upload_status"),
                    "match_status": data.get("match_status"),
                    "vintage_id": data.get("vintage_id"),
                    "user_vintage_id": data.get("user_vintage_id"),
                    "id": data.get("id"),
                    "image_location": data.get("image", {}).get("location", "").lstrip("/"),
                    "match_message": data.get("match_message"),
                    "upload_duration_ms": upload_ms,
                    "fetch_duration_ms": fetch_duration,
                    "total_duration_ms": total_ms,
                    "run_label": label,
                    "contradiction": contradiction,
                    "integrity_issue": integrity_issue,
                    "groundtruth_vintage_id": meta.get("vintage_id") or meta.get("expected_vintage_id"),
                    "groundtruth_wine_id": meta.get("wine_id"),
                    "label_ocr_text": label_ocr 
                }
            elif r.status_code == 204:
                log(f"[FETCH] … {filename} | Still processing (204)")
            else:
                log(f"[FETCH] ❌ {filename} | HTTP {r.status_code} | Body: {r.text}")
        except Exception as e:
            log(f"[FETCH] 💥 {filename} | Exception: {e}")
        time.sleep(FETCH_DELAY)

    return {"file": filename, "status": "fail", "error": "Timeout after max retries", "run_label": label}


# --- Run ---
def run_uploader(image_inputs: List[str], token: str, base_url: str, metadata: Dict[str, Any], label: str, local_mode: bool, output_file: str, inject_ocr: bool) -> None:
    start = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(upload_and_fetch, img, token, base_url, metadata, label, local_mode, inject_ocr) for img in image_inputs]
        for i, future in enumerate(as_completed(futures), 1):
            log(f"📸 Processed {i}/{len(image_inputs)}")
            results.append(future.result())

    if results:
        fieldnames = [
            "file", "processing_id","label_ocr_text", "match_status",  
            "vintage_id", "user_vintage_id", "id", "image_location", "contradiction", "integrity_issue",
            "groundtruth_vintage_id", "groundtruth_wine_id",
            "match_message", "upload_status", "status", "upload_duration_ms", "fetch_duration_ms", "total_duration_ms",
            "run_label", "error"
        ]
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    duration_ms = round((time.time() - start) * 1000)
    log(f"✅ Done. Scanned: {len(results)} | Output: {output_file} | Duration: {duration_ms} ms")

    # --- Optional Summary Breakdown ---
    success = [r for r in results if r.get("status") == 200]
    fail = len(results) - len(success)
    processing_times = [r["total_duration_ms"] for r in success if "total_duration_ms" in r]

    log(f"\n📊 SUMMARY")
    log(f"Total: {len(results)} | Success: {len(success)} | Failures: {fail}")
    if processing_times:
        log(f"⏱ Avg: {round(mean(processing_times), 2)} ms | Max: {max(processing_times)} ms")

    by_label = defaultdict(list)
    for r in success:
        by_label[r.get("run_label", "unknown")].append(r)

    log("\n📈 LABEL COMPARISON SUMMARY")
    for label, items in by_label.items():
        times = [i["total_duration_ms"] for i in items if i.get("total_duration_ms")]
        vintages = set(i["vintage_id"] for i in items if i.get("vintage_id"))
        log(f"🔖 Label: {label}")
        log(f"  🟢 Successes: {len(items)}")
        log(f"  ⏱ Avg Processing Time: {round(mean(times), 2) if times else 'N/A'} ms")
        log(f"  🍷 Unique Vintage Matches: {len(vintages)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vivino Label Upload CLI")
    parser.add_argument("--env", choices=["testing", "stable", "prod"], help="API environment")
    parser.add_argument("--email", help="Vivino email")
    parser.add_argument("--password", help="Vivino password")
    parser.add_argument("--label", help="Run label")
    parser.add_argument("--output", default="", help="CSV output file")
    parser.add_argument("--image-dir", help="Local image folder")
    parser.add_argument("--github-folder", help="GitHub /images/ subfolder")
    parser.add_argument("--metadata", help="Optional metadata JSONL file")
    parser.add_argument("--inject-ocr", dest="inject_ocr", action="store_true", help="Inject OCR text from metadata if available")
    parser.add_argument("--no-inject-ocr", dest="inject_ocr", action="store_false", help="Do not inject OCR text")
    parser.set_defaults(inject_ocr=None)  # So we can detect if it was explicitly passed or not
    args = parser.parse_args()

    args.env = prompt_if_missing(args.env, "Which environment? (testing/stable/prod): ")
    args.email = prompt_if_missing(args.email, "Vivino email: ")
    args.password = prompt_if_missing(args.password, "Vivino password: ", is_password=True)
    args.label = prompt_if_missing(args.label, "Label: ")

    if not args.image_dir and not args.github_folder:
        mode = input("📂 Choose image source - (1) local folder or (2) GitHub folder: ").strip()
        if mode == "1":
            args.image_dir = input("Enter local image folder path: ").strip()
        elif mode == "2":
            val = input("Enter GitHub image subfolder or full URL: ").strip()
            args.github_folder = val
        else:
            log("❌ Invalid input. Exiting.")
            exit(1)

    inject_ocr = args.inject_ocr  # Might be True, False, or None

    if not args.metadata:
        use_metadata = input("📄 Provide metadata file? (y/n): ").strip().lower()
        if use_metadata == "y":
            val = input("Enter metadata JSONL file path or GitHub URL: ").strip()
            if "github.com" in val and "/blob/" in val:
                val = val.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
                log(f"✅ Converted GitHub metadata URL to raw: {val}")
            args.metadata = val
            if inject_ocr is None:  # Only ask if not explicitly passed
                inject = input("Inject OCR from metadata if available? (y/n): ").strip().lower()
                inject_ocr = inject.startswith("y")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = args.output or f"results_{args.label}_{timestamp}.csv"
    token, base_url = get_auth_token(args.env, args.email, args.password)

    if args.image_dir and args.image_dir.startswith("http"):
        if "github.com" in args.image_dir and "tree" in args.image_dir:
            try:
                subpath = args.image_dir.split("/images/", 1)[1]
                args.github_folder = subpath.strip("/")
                image_inputs = get_image_urls_from_github(args.github_folder)
                local_mode = False
            except Exception as e:
                log(f"❌ Could not parse GitHub folder from URL: {e}")
                exit(1)
        else:
            log("❌ Unsupported image-dir URL format. Only GitHub folder links with '/tree/.../images/' are supported.")
            exit(1)
    elif args.image_dir:
        image_inputs = get_image_files_from_folder(args.image_dir)
        local_mode = True
    elif args.github_folder:
        image_inputs = get_image_urls_from_github(args.github_folder)
        local_mode = False
    else:
        log("❌ ERROR: You must provide either --image-dir or --github-folder")
        exit(1)

    metadata = load_metadata(args.metadata) if args.metadata else {}

    log(f"✅ Metadata keys loaded: {len(metadata)}")
    log(f"  First few: {list(metadata.keys())[:5]}")
    if not image_inputs:
        log("❌ No images found in the specified source. Exiting.")
        exit(1)
    log(f"✅ First image: {image_inputs[0]}")

    run_uploader(image_inputs, token, base_url, metadata, args.label, local_mode, output_file, inject_ocr)


if __name__ == "__main__":
    main()
