import sys
import os
import llm_client
import yt_dlp

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_accurate_generation():
    url = "https://www.youtube.com/watch?v=vcRdgyPo7IM"
    ydl_opts = {'skip_download': True, 'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title')
        raw_desc = info.get('description', '')
        # Clean timestamps and links
        lines = [l.strip() for l in raw_desc.split('\n') if l.strip() and not l.strip().startswith('http') and not l.strip()[:2].isdigit()]
        clean_desc = "\n".join(lines[:4])

    print("=== [RAW DESCRIPTION EXTRACTED] ===")
    print(clean_desc)
    print("\n" + "="*50 + "\n")

    for lang in ["英語", "韓国語", "日本語"]:
        print(f"--- Testing Generation for: {lang} ---")
        prompt = (
            f"You are a table tennis marketer. Write a concise, engaging tweet for X in {lang}.\n"
            f"Video Title: \"{title}\"\n"
            f"Video Real Content & Summary:\n\"{clean_desc}\"\n\n"
            f"Strict Rules:\n"
            f"1. Accurately reflect the SPECIFIC content of the video (e.g. searching for alternatives to SpinPips D1, pimples-out rubber characteristics).\n"
            f"2. DO NOT invent false claims or talk about generic table tennis. Stick strictly to the video topic.\n"
            f"3. Entirely in {lang}.\n"
            f"4. Max 60 words (Asian languages max 75 characters).\n"
            f"5. Include 2 hashtags (e.g. #TableTennis #SpinPips or language equivalents).\n"
            f"6. Do not include URL or placeholders like [Link]."
        )
        post_text = llm_client.query_gemini(prompt)
        print(f"Generated Post:\n{post_text}\n")

if __name__ == "__main__":
    test_accurate_generation()
