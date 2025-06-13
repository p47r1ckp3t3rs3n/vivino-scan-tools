# Vivino Scan Tools

This repository contains tools to simulate and validate Vivino scan behavior using test images and ground truth data.

Used together with [`vivino-test-images`](https://github.com/p47r1ckp3t3rs3n/vivino-test-images), it provides a full pipeline for testing recognition logic across image uploads, OCR injection, and backend comparison (e.g. CLIP vs Vuforia).

---

## 📁 Structure

* `/scripts/` — Core CLI scripts for uploading, comparing, and generating metadata
* `/config/` — Optional configuration (e.g. `.env` with credentials)
* `/tests/` — (Optional) test utilities and validation helpers
* `requirements.txt` — Python package dependencies

---

## 🧰 Prerequisites

These tools are cross-platform and work on both macOS and Windows.

### ✅ Required:

* Python 3.9+ (install via [python.org](https://www.python.org/downloads/), `brew install python` on macOS, or `winget install Python.Python.3.9` on Windows)
* Git (optional, for cloning repos)

### ✅ Virtual Environment Setup

#### macOS/Linux (Required):

```bash
python3 -m venv ~/vivino-scan-env
source ~/vivino-scan-env/bin/activate
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

#### Windows:

No virtualenv required. Just run:

```bash
pip install -r requirements.txt
```

### 🔐 Auth (Optional)

Create a `.env` file with your credentials (instead of typing them on every run):

```env
VIVINO_USERNAME=my.user@vivino.com
VIVINO_PASSWORD=supersecure
```

Or pass them interactively when prompted.

---

## 🔧 Scripts

### `upload_and_fetch.py`

Uses metadata from `labels.jsonl` to simulate real scan scenarios. Supports:

- Injecting OCR (`ocr_text`) if `--inject-ocr` is passed  
- Injecting crop box if present in metadata and `--inject-crop` is passed  
- Validating scan result against `expected_vintage_id` if `--validate-vintage` is passed  

Uploads images and retrieves match results from Vivino’s label scan API.

```bash
python scripts/upload_and_fetch.py --env testing --label clip --labels-file ../vivino-test-images/metadata/labels.jsonl --inject-ocr --validate-vintage --output results_clip.csv
```

**Optional flags:**

- `--labels-file` → path to labels.jsonl metadata file (required for test automation)  
- `--inject-ocr` → use `ocr_text` if present in metadata  
- `--inject-crop` → use `crop_x/y/width/height` if present  
- `--validate-vintage` → compare returned `vintage_id` to `expected_vintage_id`  
- `--output results_clip.csv` → specify CSV output path

**Full command example:**

```bash
python scripts/upload_and_fetch.py --env testing --label clip --username my.user@vivino.com --password Password1! --labels-file ../vivino-test-images/metadata/labels.jsonl
```

---

### `compare_runs.py`

Compares scan result CSVs from two systems, enriches with metadata, and categorizes mismatches.

```bash
python scripts/compare_runs.py results_clip.csv results_vuforia.csv --output comparison.xlsx --use-cache
```

**Output includes:**

* Side-by-side wine metadata
* Match categorization (`Exact match`, `Same wine, different vintage`, etc.)
* Links to original images and matched Vivino wine pages

---

### `generate_from_curls.py`

Parses real `curl` commands from device logs and generates `labels.jsonl` entries.

```bash
python scripts/generate_from_curls.py curl_logs.txt > new_labels.jsonl
```

Automatically adds:

* `ocr_text` from request
* `crop_x/y/width/height` if present
* Tags like `ocr`, `requires_crop` if implied

---

## 🔗 Related Repository

* 🖼 [`vivino-test-images`](https://github.com/p47r1ckp3t3rs3n/vivino-test-images) — Test image library and metadata definitions
