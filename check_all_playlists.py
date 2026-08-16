import sys
import yt_dlp

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def check_playlists():
    channels = [
        ("Main Channel", "https://www.youtube.com/@ToriShiraChannel/playlists"),
        ("TTLab Channel", "https://www.youtube.com/@Tori-ShiraTTLab/playlists")
    ]
    
    for label, url in channels:
        print(f"\n=== Fetching Playlists for {label} ({url}) ===")
        try:
            ydl_opts = {'extract_flat': True, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(url, download=False)
                entries = res.get('entries', []) if res else []
                print(f"Total playlists found: {len(entries)}")
                for i, e in enumerate(entries):
                    print(f"[{i+1}] {e.get('title')} -> https://www.youtube.com/playlist?list={e.get('id')}")
        except Exception as ex:
            print(f"Error fetching {label}: {ex}")

if __name__ == "__main__":
    check_playlists()
