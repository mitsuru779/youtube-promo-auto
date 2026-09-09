import yt_dlp

ydl_opts = {'extract_flat': True, 'quiet': True}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    res = ydl.extract_info("https://www.youtube.com/@Tori-ShiraTTLab", download=False)
    ch_id = res.get('channel_id') or res.get('id')
    print(f"TTLab Channel ID: {ch_id}")
