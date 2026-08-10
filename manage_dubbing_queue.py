"""
Dubbing Queue & Progress Matrix Manager (`manage_dubbing_queue.py`)
Tracks completion status for 11 languages per video and prepares the next batch to execute.
Filters to public videos only to avoid members-only errors.
"""

import os
import json

STATUS_FILE = "dubbing_matrix.json"
PUBLIC_VIDEOS_FILE = "scratch/public_videos.json"
COMPLETED_VIDEOS_FILE = "completed_videos.json"

TARGET_LANGUAGES = ["en", "zh-CN", "de", "fr", "pt", "es", "sv", "ru", "uk", "hi", "th", "vi"]


def load_matrix():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    matrix = {}
    video_ids = []

    # Prefer public videos
    if os.path.exists(PUBLIC_VIDEOS_FILE):
        with open(PUBLIC_VIDEOS_FILE, "r", encoding="utf-8") as f:
            pub_data = json.load(f)
            video_ids = [item["videoId"] for item in pub_data if isinstance(item, dict) and "videoId" in item]

    if not video_ids and os.path.exists(COMPLETED_VIDEOS_FILE):
        with open(COMPLETED_VIDEOS_FILE, "r", encoding="utf-8") as f:
            video_ids = json.load(f)

    for vid in video_ids:
        matrix[vid] = {lang: False for lang in TARGET_LANGUAGES}

    save_matrix(matrix)
    return matrix


def save_matrix(matrix):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, indent=2)


def get_next_unprocessed_batch(batch_size=1):
    matrix = load_matrix()
    pending = []

    for vid, status in matrix.items():
        missing_langs = [lang for lang, done in status.items() if not done]
        if missing_langs:
            pending.append((vid, missing_langs))
            if len(pending) >= batch_size:
                break

    return pending


def mark_completed(video_id, lang_code):
    matrix = load_matrix()
    if video_id in matrix:
        matrix[video_id][lang_code] = True
        save_matrix(matrix)


if __name__ == "__main__":
    matrix = load_matrix()
    print(f"Total tracked videos in matrix: {len(matrix)}")
    next_batch = get_next_unprocessed_batch(2)
    print(f"Next batch to process: {next_batch}")
