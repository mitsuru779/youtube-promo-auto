import os
import sys
import json
import random
import logging
import time
import re
import requests
import yt_dlp
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import llm_client

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()

STATE_FILE = "promo_state.json"
AUTH_FILE = os.getenv("AUTH_STATE_FILE", "auth_state.json")

# 12 Foreign Languages strictly for @ToriShiraCh (NO Japanese)
LANGUAGES = [
    {"code": "en", "name": "英語"},
    {"code": "zh-CN", "name": "中国語"},
    {"code": "de", "name": "ドイツ語"},
    {"code": "fr", "name": "フランス語"},
    {"code": "pt", "name": "ポルトガル語"},
    {"code": "es", "name": "スペイン語"},
    {"code": "sv", "name": "スウェーデン語"},
    {"code": "ru", "name": "ロシア語"},
    {"code": "uk", "name": "ウクライナ語"},
    {"code": "hi", "name": "ヒンディー語"},
    {"code": "th", "name": "タイ語"},
    {"code": "vi", "name": "ベトナム語"}
]

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading state: {e}")
    return {"last_lang_index": 0, "history": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving state: {e}")

def fetch_collab_videos():
    try:
        url = "https://www.youtube.com/@Tori-ShiraTTLab/videos"
        ydl_opts = {'extract_flat': True, 'quiet': True, 'playlistend': 30}
        videos = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                v_id = e.get('id') or ""
                if v_id and t:
                    videos.append({
                        'id': v_id,
                        'title': t,
                        'url': f"https://www.youtube.com/watch?v={v_id}",
                        'description': t
                    })
        return videos
    except Exception as e:
        logging.error(f"Error fetching collab videos: {e}")
        return []

def fetch_published_playlists():
    playlists_url = "https://www.youtube.com/@ToriShiraChannel/playlists"
    try:
        ydl_opts = {'extract_flat': True, 'quiet': True}
        playlists = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(playlists_url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                pl_id = e.get('id') or ""
                if pl_id and t:
                    playlists.append({
                        'id': pl_id,
                        'title': t,
                        'url': f"https://www.youtube.com/playlist?list={pl_id}",
                        'description': f"再生リスト: {t}",
                        'is_playlist': True
                    })
        return playlists
    except Exception as e:
        logging.error(f"Error fetching playlists: {e}")
        return []

def fetch_main_items(history=[]):
    videos = []
    public_channel_url = "https://www.youtube.com/@ToriShiraChannel/videos"
    try:
        ydl_opts = {'extract_flat': True, 'quiet': True, 'playlistend': 35}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(public_channel_url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                v_id = e.get('id') or ""
                if "メンバー限定" in t or "Members-only" in t:
                    continue
                if v_id and t:
                    videos.append({
                        'id': v_id,
                        'title': t,
                        'url': f"https://www.youtube.com/watch?v={v_id}",
                        'description': t,
                        'is_playlist': False
                    })
    except Exception as e:
        print(f"Warning fetching main videos: {e}")
        
    playlists = fetch_published_playlists()
    all_items = videos + playlists
    if not all_items:
        return None
        
    non_recent = [it for it in all_items if it['url'] not in history]
    if not non_recent:
        non_recent = all_items
    return random.choice(non_recent)

def post_to_hatena(title, content):
    try:
        hatena_id = os.getenv("HATENA_ID")
        blog_id = os.getenv("HATENA_BLOG_ID")
        api_key = os.getenv("HATENA_API_KEY")
        if not all([hatena_id, blog_id, api_key]):
            logging.error("Hatena credentials missing")
            return False
            
        url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
        xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{hatena_id}</name></author>
  <content type="text/html"><![CDATA[{content}]]></content>
  <category term="TableTennis" />
  <app:control><app:draft>no</app:draft></app:control>
</entry>"""
        res = requests.post(url, auth=(hatena_id, api_key), data=xml_data.encode('utf-8'), headers={'Content-Type': 'application/xml'}, timeout=30)
        return res.status_code in [200, 201]
    except Exception as e:
        logging.error(f"Hatena error: {e}")
        return False

def is_strict_account_match(text, target_handle):
    """Strictly checks that the handle appears as an exact handle with negative lookahead.
    Prevents @ToriShiraCh from matching @ToriShiraChanne."""
    clean = target_handle.strip().lower().replace("@", "")
    pattern = rf"@{clean}(?![a-zA-Z0-9_])"
    return bool(re.search(pattern, text.lower()))

def switch_x_account(page, target_handle):
    """Switches X account and strictly verifies that the active account exactly matches target_handle."""
    clean_target = target_handle.strip().lower().replace("@", "")
    try:
        page.set_viewport_size({"width": 1600, "height": 900})
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        
        switcher = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
        if switcher.count():
            cur_text = switcher.inner_text().lower()
            if is_strict_account_match(cur_text, target_handle):
                print(f"PASSED: Already logged into target X account (@{clean_target}).")
                return True
                
            print(f"Current active X account is NOT @{clean_target}. Switching account...")
            switcher.click(force=True)
            time.sleep(2)
            
            # Find the exact row in menu (excluding other accounts like torishirachanne when looking for torishirach)
            rows = page.locator("#layers [data-testid='AccountSwitcher_Account_Row'], #layers div[role='menuitem'], #layers a").all()
            target_item = None
            for r in rows:
                try:
                    if is_strict_account_match(r.inner_text(), target_handle):
                        target_item = r
                        break
                except Exception:
                    pass
                    
            if target_item:
                print(f"Clicking exact menu item for @{clean_target}...")
                target_item.click(force=True)
                time.sleep(6)
                
                # STRICT RE-VERIFY AFTER SWITCH:
                page.goto("https://x.com/home", wait_until="domcontentloaded")
                time.sleep(3)
                sw_after = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
                if sw_after.count() and is_strict_account_match(sw_after.inner_text(), target_handle):
                    print(f"🎉 Successfully switched and strictly verified active account is @{clean_target}!")
                    return True
                    
        print(f"⛔ [STRICT CHECK FAILED] Active account is NOT @{clean_target}. Aborting to prevent wrong-account posting.")
        return False
    except Exception as e:
        logging.error(f"X switch error: {e}")
        return False

def post_to_x(page, text, target_handle):
    try:
        # STRICT PROTECTION: Never post if account does not strictly match target_handle
        if not switch_x_account(page, target_handle):
            print(f"⛔ [STRICT ABORT] Refusing to post because active account is NOT {target_handle}. Skipping post.")
            return False
            
        compose_btn = page.locator("[data-testid='SideNav_NewTweet_Button'], a[href='/compose/post']").first
        if compose_btn.count():
            compose_btn.click()
        else:
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        
        box = page.locator("div[role='dialog'] div[role='textbox'], div[role='textbox']").first
        box.wait_for(state="visible", timeout=15000)
        box.click()
        time.sleep(1)
        
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        time.sleep(0.5)
        
        page.keyboard.type(text, delay=10)
        time.sleep(2)
        
        page.evaluate("""() => {
            const btn = document.querySelector("button[data-testid='tweetButton'], button[data-testid='tweetButtonInline']");
            if (btn) btn.click();
        }""")
        time.sleep(5)
        print(f"Successfully posted to X [{target_handle}]!")
        return True
    except Exception as e:
        logging.error(f"X post error: {e}")
        return False

def post_to_yt_community(page, channel_url, text):
    try:
        page.goto(channel_url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        
        post_box = page.locator("#placeholder-area, #contenteditable-root, div#contenteditable-textarea").first
        if post_box.count() and post_box.is_visible():
            post_box.click()
            time.sleep(1)
            page.keyboard.type(text, delay=10)
            time.sleep(2)
            submit = page.locator("ytd-button-renderer#submit-button, button[aria-label*='投稿'], button[aria-label*='Post']").first
            submit.click(force=True)
            time.sleep(4)
            print("Successfully posted to YouTube Community!")
            return True
        return False
    except Exception as e:
        logging.error(f"YouTube Community error: {e}")
        return False

def run_cloud_job():
    print("=== Launching Promo Job on Cloud ===")
    state = load_state()
    lang_index = state.get("last_lang_index", 0) % len(LANGUAGES)
    lang = LANGUAGES[lang_index]
    print(f"Current Language: {lang['name']} ({lang['code']})")
    
    # Task 1, 2, 3: Collab videos (12 foreign languages only)
    collab_videos = fetch_collab_videos()
    if collab_videos:
        non_recent = [v for v in collab_videos if v['url'] not in state.get("history", [])]
        collab_video = random.choice(non_recent if non_recent else collab_videos)
        
        trans_title = llm_client.translate_title(collab_video['title'], lang['name']) or collab_video['title']
        trans_desc = llm_client.translate_text(collab_video['description'], lang['name']) or collab_video['description']
        
        # Check no Japanese kana in foreign post
        if any("\u3040" <= char <= "\u30ff" for char in trans_title):
            trans_title = llm_client.translate_title(collab_video['title'], "英語")
            trans_desc = llm_client.translate_text(collab_video['description'], "英語")
            
        x_foreign_text = llm_client.generate_x_post(trans_title, collab_video['url'], lang['name'], is_collab=True)
        
        # 1. Hatena Blog (12 foreign languages)
        embed_html = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{collab_video["id"]}" frameborder="0" allowfullscreen></iframe>'
        hatena_title = f"{trans_title} (AI Analysis) - Tori-Shira TT Lab"
        hatena_content = f"<p><b>Tori-Shira TT Lab</b></p><h3>{trans_title}</h3>{embed_html}<p>{trans_desc}</p><p><a href='{collab_video['url']}'>Watch on YouTube</a></p>"
        post_to_hatena(hatena_title, hatena_content)
        
        # Launch Headless Playwright
        if os.path.exists(AUTH_FILE):
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                except Exception:
                    browser = p.chromium.launch(headless=True, channel="chrome", args=["--no-sandbox"])
                context = browser.new_context(storage_state=AUTH_FILE)
                
                # 2. X (@ToriShiraCh - 12 Foreign Languages ONLY, STRICT ABORT IF NOT @ToriShiraCh)
                p1 = context.new_page()
                post_to_x(p1, x_foreign_text, target_handle="@ToriShiraCh")
                p1.close()
                
                # 3. YouTube Community (@Tori-ShiraTTLab)
                yt_text = f"🎬 {trans_title}\n\n{trans_desc}\n\n{collab_video['url']}\n\n#TableTennis #ToriShiraTTLab"
                p2 = context.new_page()
                post_to_yt_community(p2, "https://www.youtube.com/@Tori-ShiraTTLab/posts", yt_text)
                p2.close()
                
                # 4. Japanese Main Video/Playlist (@ToriShiraChanne - Japanese ONLY, STRICT ABORT IF NOT @ToriShiraChanne)
                main_item = fetch_main_items(history=state.get("history", []))
                if main_item:
                    is_pl = main_item.get('is_playlist', False)
                    if is_pl:
                        clean_title = main_item['title'].split("|")[0].strip()
                        x_ja_text = f"🎬 【おすすめ再生リスト】\n{clean_title}\n\n関連動画をまとめてチェック！ぜひご覧ください。\n\n#卓球 #再生リスト\n\n{main_item['url']}"
                    else:
                        x_ja_text = llm_client.generate_x_post(main_item['title'], main_item['url'], "Japanese", is_collab=False)
                        
                    p3 = context.new_page()
                    post_to_x(p3, x_ja_text, target_handle="@ToriShiraChanne")
                    p3.close()
                    
                    state["history"].append(main_item['url'])
                    
                context.close()
                browser.close()
                
        state["history"].append(collab_video['url'])
        state["last_lang_index"] = lang_index + 1
        if len(state["history"]) > 50:
            state["history"] = state["history"][-50:]
        save_state(state)
        print("=== Cloud Job Completed Successfully ===")

if __name__ == "__main__":
    run_cloud_job()
