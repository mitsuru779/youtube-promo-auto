import sys
import yt_dlp
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_fetch_details(url):
    print(f"Fetching details for: {url}")
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title')
        desc = info.get('description', '')
        tags = info.get('tags', [])
        
        print(f"\n[TITLE]: {title}")
        print(f"\n[DESCRIPTION (First 300 chars)]:\n{desc[:300]}...")
        print(f"\n[TAGS]: {tags[:5]}")

if __name__ == "__main__":
    test_fetch_details("https://www.youtube.com/watch?v=vcRdgyPo7IM")
