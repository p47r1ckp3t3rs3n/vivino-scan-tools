import os
import json
from typing import List, Dict

# --- Load label entries from JSONL ---
def load_labels_from_jsonl(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

# --- Extract metadata for a given filename ---
def get_label_metadata(labels: List[Dict], filename: str) -> Dict:
    for entry in labels:
        if entry.get("filename") == filename:
            return entry
    return {}
