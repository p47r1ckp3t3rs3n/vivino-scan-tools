import os
import time
import csv
import json
import requests
import argparse
from collections import defaultdict
from getpass import getpass
from datetime import datetime
from statistics import mean
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CLI Prompts ---
def prompt_if_missing(value, prompt_text, is_password=False):
    if value:
        return value
    return getpass(prompt_text) if is_password else input(prompt_text)

# --- Authentication ---
def get_auth_token(env, username, password):
    if env == "prod":
        client_id = "uLGCMd5hl6jDJw5y6uCdwsdMCHdxQR31wRUuSazL"
        client_secret = "tKaH7pdpBv4uD5OJJhow6YiaMp0NmqDDuSZXqiji"
    else:
        client_id = "TESTING_ID_FOR_ANDROID"
        client_secret = "TESTING_SECRET_FOR_ANDROID"

    base_url = {
        "testing": "https://api.testing.vivino.com",
        "stable": "https://api.stable.vivino.com",
        "prod": "https://api.vivino.com"
    }[env]

    url = f"{base_url}/oauth/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "password",
        "username": username,
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
def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}")

# --- Detect contradictions ---
def detect_contradictions(data):
    issues = []
    if data.get("match_status") is None and data.get("vintage_id"):
        issues.append("vintage_id present despite match_status=None")
    if data.get("upload_status") != "Completed" and data.get("vintage_id"):
        issues.append("vintage_id present despite incomplete upload")
    if data.get("match_status") == "Matched" and not data.get("vintage_id"):
        issues.append("match_status=Matched but vintage_id is null")
    return "; ".join(issues) if issues else None

# --- Integrity check ---
def verify_integrity(label_id, user_vintage_id):
    label_url = f"{base_url}/v/9.0.0/scans/v2/label/{label_id}"
    uv_url = f"{base_url}/v/9.1.1/user_vintages/{user_vintage_id}"
    headers = {"Authorization": f"Bearer {token}"}
    integrity_issues = []

    try:
        label_resp = requests.get(label_url, headers=headers, timeout=TIMEOUT, verify=False)
        label_data = label_resp.json()
    except Exception as e:
        return f"Failed to fetch label {label_id}: {e}"

    try:
        uv_resp = requests.get(uv_url, headers=headers, timeout=TIMEOUT, verify=False)
        uv_data = uv_resp.json()
    except Exception as e:
        return f"Failed to fetch user_vintage {user_vintage_id}: {e}"

    if label_data.get("id") != label_id:
        integrity_issues.append("Label ID mismatch")
    if label_data.get("user_vintage_id") != user_vintage_id:
        integrity_issues.append("Mismatch: label.user_vintage_id != userVintage.id")
    if uv_data.get("label_id") != label_id:
        integrity_issues.append("Mismatch: userVintage.label_id != label.id")
    if label_data.get("match_status") == "Matched" and label_data.get("vintage_id") is None:
        integrity_issues.append("label.match_status=Matched but no vintage_id")
    if label_data.get("image") is None and uv_data.get("image") is None:
        integrity_issues.append("No image in either label or user_vintage")

    return "; ".join(integrity_issues) if integrity_issues else None

# --- Argument Parsing ---
parser = argparse.ArgumentParser()
parser.add_argument("--env", choices=["testing", "stable", "prod"], help="API environment")
parser.add_argument("--username", help="Vivino username")
parser.add_argument("--password", help="Vivino password")
parser.add_argument("--label", default="", help="Run label (e.g. clip or vuforia)")
parser.add_argument("--output", default="", help="CSV output file name")
args = parser.parse_args()

args.env = prompt_if_missing(args.env, "Which environment? (testing/stable/prod): ")
args.username = prompt_if_missing(args.username, "Enter your Vivino username/email: ")
args.password = prompt_if_missing(args.password, "Enter your Vivino password: ", is_password=True)
args.label = prompt_if_missing(args.label, "Label for this run (clip/vuforia/etc.): ")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = args.output or f"results_{args.label}_{timestamp}.csv"
token, base_url = get_auth_token(args.env, args.username, args.password)

UPLOAD_URL = f"{base_url}/v/10.0.0/scans/label?image_type=jpg&add_user_vintage=true&queue_tier_matching=false"
FETCH_URL_TEMPLATE = f"{base_url}/v/9.0.0/scans/v2/label/{{processing_id}}?user_id=3&language=en"

def get_image_urls_from_github():
    api_url = "https://api.github.com/repos/p47r1ckp3t3rs3n/vivino-test-images/contents/images"
    raw_base = "https://raw.githubusercontent.com/p47r1ckp3t3rs3n/vivino-test-images/main/images"
    try:
        r = requests.get(api_url, timeout=10)
        r.raise_for_status()
        files = r.json()
        urls = [f"{raw_base}/{f['name']}" for f in files if f['name'].lower().endswith(".jpg")]
        log(f"🔍 Fetched {len(urls)} image URLs from GitHub:")
        for u in urls[:5]:
            log(f"  📷 {u}")
        if len(urls) > 5:
            log(f"  ...and {len(urls) - 5} more.")
        return urls
    except Exception as e:
        log(f"[ERROR] Failed to fetch image list from GitHub: {e}")
        return []

image_urls = get_image_urls_from_github()

RETRIES = 3
TIMEOUT = 10
FETCH_DELAY = 0.5
MAX_FETCH_RETRIES = 100

results = []

def upload_and_fetch(image_url):
    filename = os.path.basename(image_url)
    headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
    processing_id = None

    try:
        response = requests.get(image_url, timeout=TIMEOUT)
        response.raise_for_status()
        image_bytes = response.content
    except Exception as e:
        log(f"[DOWNLOAD] 💥 {filename} | {e}")
        return {"file": filename, "status": "fail", "error": "Download failed", "run_label": args.label}

    try:
        upload_start = time.time()
        files = {"image": (filename, image_bytes, "image/jpeg")}
        resp = requests.post(UPLOAD_URL, headers=headers, files=files, timeout=TIMEOUT, verify=False)
        if resp.status_code == 200:
            resp_data = resp.json()
            processing_id = resp_data.get("processing_id")
            upload_end = time.time()
            log(f"[UPLOAD] ✅ {filename} | processing_id={processing_id}")
        else:
            log(f"[UPLOAD] ❌ {filename} | HTTP {resp.status_code}")
            return {"file": filename, "status": resp.status_code, "error": resp.text, "run_label": args.label}
    except Exception as e:
        log(f"[UPLOAD] 💥 {filename} | {e}")
        return {"file": filename, "status": "fail", "error": "Upload failed", "run_label": args.label}

    url = FETCH_URL_TEMPLATE.format(processing_id=processing_id)
    for attempt in range(MAX_FETCH_RETRIES):
        try:
            fetch_start = time.time()
            resp = requests.get(url, headers=headers, timeout=TIMEOUT, verify=False)
            fetch_duration = round((time.time() - fetch_start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                contradiction = detect_contradictions(data)
                total_ms = round((time.time() - upload_start) * 1000)
                upload_ms = round((upload_end - upload_start) * 1000)

                integrity_issue = None
                if data.get("id") and data.get("user_vintage_id"):
                    log(f"[🔄 CROSS-REF] {filename} | Validating /label/{data['id']} ↔ /user_vintages/{data['user_vintage_id']}")
                    integrity_issue = verify_integrity(data["id"], data["user_vintage_id"])
                    if integrity_issue:
                        log(f"[🧯 INTEGRITY] {filename} | {integrity_issue}")
                    else:
                        log(f"[✅ INTEGRITY] {filename} | All good")

                log(f"[FETCH] ✅ {filename} | match_status={data.get('match_status')} | vintage_id={data.get('vintage_id')}")
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
                    "total_duration_ms": total_ms,
                    "upload_duration_ms": upload_ms,
                    "fetch_duration_ms": fetch_duration,
                    "run_label": args.label,
                    "contradiction": contradiction,
                    "integrity_issue": integrity_issue
                }

            elif resp.status_code == 204:
                log(f"[FETCH] … {filename} | Still processing (204)")
            else:
                log(f"[FETCH] ❌ {filename} | HTTP {resp.status_code} | Body: {resp.text}")
        except Exception as e:
            log(f"[FETCH] 💥 {filename} | Exception: {e}")

        time.sleep(FETCH_DELAY)

    return {
        "file": filename,
        "status": "fail",
        "processing_id": processing_id,
        "error": f"No valid response after {MAX_FETCH_RETRIES} retries",
        "run_label": args.label
    }

# --- Run uploads + fetches concurrently ---
start = time.time()
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = [pool.submit(upload_and_fetch, url) for url in image_urls]
    for future in as_completed(futures):
        result = future.result()
        results.append(result)
        if result.get("status") == 200:
            log(f"[⏱️ PERFORM] {result['file']} | Upload: {result['upload_duration_ms']} ms | Fetch: {result['fetch_duration_ms']} ms | Total: {result['total_duration_ms']} ms")

# --- Save Results ---
with open(output_file, "w", newline="", encoding="utf-8") as f:
    fieldnames = [
        "file", "status", "processing_id", "upload_status", "match_status",
        "vintage_id", "user_vintage_id", "id", "image_location",
        "match_message", "upload_duration_ms", "fetch_duration_ms",
        "total_duration_ms", "run_label", "error", "contradiction", "integrity_issue"
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

# --- Summary ---
success = [r for r in results if r["status"] == 200]
fail = len(results) - len(success)
processing_times = [r["total_duration_ms"] for r in success if "total_duration_ms" in r]

duration = round((time.time() - start) * 1000)
log(f"📊 SUMMARY")
log(f"Total: {len(results)} | Success: {len(success)} | Failures: {fail}")
if processing_times:
    log(f"⏱ Avg: {round(mean(processing_times), 2)} ms | Max: {max(processing_times)} ms")
log(f"🕐 Total run time: {duration} ms")
log(f"📁 Output written to {output_file}")

# --- Label Summary ---
by_label = defaultdict(list)
for r in success:
    label = r.get("run_label", "unknown")
    by_label[label].append(r)

log("\n📈 LABEL COMPARISON SUMMARY")
for label, items in by_label.items():
    times = [i["total_duration_ms"] for i in items if i.get("total_duration_ms") is not None]
    vintages = set(i["vintage_id"] for i in items if i.get("vintage_id"))
    log(f"🔖 Label: {label}")
    log(f"  🟢 Successes: {len(items)}")
    log(f"  ⏱ Avg Processing Time: {round(mean(times), 2) if times else 'N/A'} ms")
    log(f"  🍷 Unique Vintage Matches: {len(vintages)}")