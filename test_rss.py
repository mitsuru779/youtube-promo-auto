import urllib.request
import xml.etree.ElementTree as ET
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_rss_feed():
    # ToriShiraChannel ID: UCY6k5Q5pXh-9xP-b18s64_Q or similar
    # Let's test Tori-Shira TT Lab channel feed
    channels = [
        ("TTLab", "https://www.youtube.com/feeds/videos.xml?channel_id=UC6P7x1r3YgYmZ5vVq7V-0kw"), # sample
    ]
    
    # Or fetch from handle via ytdlp channel id
    import yt_dlp
    ydl_opts = {'extract_flat': True, 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info("https://www.youtube.com/@ToriShiraChannel", download=False)
        ch_id = res.get('channel_id') or res.get('id')
        print(f"Main Channel ID: {ch_id}")
        
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch_id}"
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            xml_data = resp.read().decode('utf-8')
            root = ET.fromstring(xml_data)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'media': 'http://search.yahoo.com/mrss/'}
            
            entries = root.findall('atom:entry', ns)
            print(f"Total videos in RSS: {len(entries)}")
            for e in entries[:3]:
                title = e.find('atom:title', ns).text
                v_id = e.find('atom:id', ns).text
                group = e.find('media:group', ns)
                desc = group.find('media:description', ns).text if group is not None else ""
                print(f"\n[RSS Title]: {title}")
                print(f"[RSS Desc]: {desc[:150]}...")

if __name__ == "__main__":
    test_rss_feed()
