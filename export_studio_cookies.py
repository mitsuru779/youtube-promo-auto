"""
Export YouTube Studio Session Cookie for GitHub Secret (`export_studio_cookies.py`)
Run this script while Chrome with debugging port 9222 is open and logged into YouTube Studio.
It saves `storage_state.json` which can be set as `YT_STUDIO_COOKIES` secret in GitHub.
"""

import json
from playwright.sync_api import sync_playwright

def export_cookies():
    print("Connecting to Chrome on port 9222 to export cookies...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            state = context.storage_state()
            with open("storage_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            print("Successfully exported `storage_state.json`!")
            print("Now you can copy the contents of `storage_state.json` to GitHub Secret: YT_STUDIO_COOKIES")
    except Exception as e:
        print(f"Error connecting to Chrome: {e}")
        print("Please ensure Chrome is running with debug port 9222 logged into YouTube Studio.")

if __name__ == "__main__":
    export_cookies()
