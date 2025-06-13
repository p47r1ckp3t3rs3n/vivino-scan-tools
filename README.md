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
