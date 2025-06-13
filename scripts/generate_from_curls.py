import urllib.parse

# Function using actual image filename and preserving original OCR text
def parse_curl_to_metadata_v2(curl_str):
    # Extract filename from the -F 'image=@...' part
    file_match = re.search(r"-F\s+'image=@.*?([\\/]?([\d:-]+_image))'", curl_str)
    filename = file_match.group(2) + ".JPG" if file_match else "unknown_image.JPG"

    metadata = {
        "filename": filename,
        "added_by": "patrick",
        "added_at": datetime.utcnow().isoformat() + "Z",
        "tags": []
    }

    # Extract URL params
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

    # Remove duplicate tags
    metadata["tags"] = list(sorted(set(metadata["tags"])))

    return metadata

# Run with updated logic
results_v2 = [parse_curl_to_metadata_v2(curl) for curl in curl_requests]
jsonl_output_v2 = "\n".join(json.dumps(obj, ensure_ascii=False) for obj in results_v2)
jsonl_output_v2
