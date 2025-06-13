# Vivino Scan Tools

This repo provides tooling to upload label images to the Vivino scan API, collect scan results, compare system outputs (e.g. Vuforia vs CLIP), and validate scan accuracy.

Used together with [`vivino-test-images`](https://github.com/p47r1ckp3t3rs3n/vivino-test-images), this enables testing and benchmarking across real-world wine label scenarios.

---

## 📦 Structure

- `/scripts/` — Python tools for uploading, comparing, and generating test metadata
- `/config/` — Optional configuration files (e.g. `.env` with API secrets)
- `/tests/` — Unit tests and test utilities (optional)

---

## 🛠 Tools

### `upload_and_fetch.py`
Uploads a set of images (from labels.jsonl) and fetches recognition results.

```bash
python scripts/upload_and_fetch.py --env testing --label clip
```

## Optional flags:

--inject-ocr — inject ocr_text if available

--validate-vintage — check result against expected_vintage_id

## compare_runs.py
Compares two result files (e.g. from clip and vuforia runs), enriches with metadata, and outputs Excel with side-by-side diffs.

```bash
python scripts/compare_runs.py results_clip.csv results_vuforia.csv --output comparison.xlsx --use-cache
```
## generate_from_curls.py
Converts raw curl logs from real mobile scans into valid labels.jsonl entries.
```bash
python scripts/generate_from_curls.py curl_logs.txt > new_labels.jsonl
```

## 🔗 Related Repo
- 🖼 vivino-test-images: test image library and metadata

## 🧪 Development
Install dependencies:
```bash
pip install -r requirements.txt
```
Create a .env file with:
```env
VIVINO_USERNAME=your_email
VIVINO_PASSWORD=your_password
```
Or pass them interactively at runtime.
```yaml
```
---

## 📦 `requirements.txt`
```txt
requests
pandas
openpyxl
urllib3
```
