"""
YouTube Studio Audio Uploader (`studio_audio_uploader.py`)
Automates Playwright browser uploading of multi-language audio tracks into YouTube Studio.
"""

import os
import sys
import time
import json
from playwright.sync_api import sync_playwright

LANG_STUDIO_MAP = {
    "en": "英語",
    "zh-CN": "中国語（簡体字）",
    "de": "ドイツ語",
    "fr": "フランス語",
    "pt": "ポルトガル語",
    "es": "スペイン語",
    "sv": "スウェーデン語",
    "ru": "ロシア語",
    "uk": "ウクライナ語",
    "hi": "ヒンディー語",
    "th": "タイ語",
    "vi": "ベトナム語"
}


def upload_audio_tracks(video_id, audio_files_dict, cdp_url=None, storage_state_path=None):
    """
    Uploads audio tracks into YouTube Studio for specified video.
    Supports CDP connection (local Chrome) or Storage State (headless on cloud).
    """
    print(f"\n--- Uploading Audio Tracks to YouTube Studio for {video_id} ---")
    with sync_playwright() as p:
        if cdp_url:
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
        elif storage_state_path and os.path.exists(storage_state_path):
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state_path)
        else:
            print("Error: Either cdp_url or valid storage_state_path must be provided.")
            return False

        page = context.new_page()
        url = f"https://studio.youtube.com/video/{video_id}/translations"
        page.goto(url)
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        for lang_code, audio_file_path in audio_files_dict.items():
            if not os.path.exists(audio_file_path):
                print(f"Skipping missing audio file: {audio_file_path}")
                continue

            lang_name = LANG_STUDIO_MAP.get(lang_code, lang_code)
            print(f"Adding/Updating Audio Track for {lang_name} ({lang_code})...")

            try:
                # Click Add Language button if language row doesn't exist
                add_lang_btn = page.query_selector('#add-language-button')
                if add_lang_btn and add_lang_btn.is_visible():
                    add_lang_btn.click()
                    time.sleep(1)
                    # Search language name and click
                    search_input = page.query_selector('input[placeholder*="検索"]') or page.query_selector('input[type="text"]')
                    if search_input:
                        search_input.fill(lang_name)
                        time.sleep(1)
                        page.keyboard.press("Enter")
                        time.sleep(1)

                # Locate row for the specific language
                rows = page.query_selector_all('ytcp-video-translation-row')
                for row in rows:
                    row_text = row.inner_text()
                    if lang_name in row_text:
                        # Find Audio track column pencil / edit button inside shadow DOM
                        audio_cell = row.query_selector('.audio-cell') or row.query_selector('[id*="audio"]')
                        if audio_cell:
                            edit_btn = audio_cell.query_selector('ytcp-icon-button') or audio_cell.query_selector('tp-yt-paper-icon-button')
                            if edit_btn:
                                edit_btn.click()
                                time.sleep(2)
                                # File input
                                file_input = page.query_selector('input[type="file"]')
                                if file_input:
                                    file_input.set_input_files(os.path.abspath(audio_file_path))
                                    time.sleep(5)
                                    # Click Save / Publish
                                    save_btn = page.query_selector('#save-button') or page.query_selector('ytcp-button#save')
                                    if save_btn:
                                        save_btn.click()
                                        time.sleep(3)
                                        print(f"[SUCCESS] Audio track uploaded for {lang_name}!")
            except Exception as e:
                print(f"[ERROR] Failed uploading audio for {lang_name}: {e}")

        browser.close()
        return True


if __name__ == "__main__":
    if len(sys.argv) > 2:
        vid = sys.argv[1]
        files_json = json.loads(sys.argv[2])
        upload_audio_tracks(vid, files_json, cdp_url="http://127.0.0.1:9222")
