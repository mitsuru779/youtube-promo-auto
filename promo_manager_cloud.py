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

# Complete verified backup list of all 23 public playlists
STATIC_PLAYLISTS = [
    {"id": "PLAu_TXrTcoR0", "title": "卓球視覚・アイウェア・健康科学 | Visual Performance & Health Science"},
    {"id": "PLKRY5Rjpf4xk", "title": "卓球メンタル・練習理論・上達の思考法 | Mental Training & Practice Theories"},
    {"id": "PLen0E7freFcY", "title": "卓球バイオメカニクス・身体操作・打球解剖学 | Biomechanics & Movement in Table Tennis"},
    {"id": "PLLVNzVicYEhI", "title": "中学校部活動 | Junior High School Table Tennis Club Guide"},
    {"id": "PLfLqP02qloDI", "title": "チャンネルお知らせ | Channel Announcements & Updates"},
    {"id": "PLJxx78-bWD2c", "title": "卓球台・ボール比較ガイド | Table Tennis Tables & Balls Comparison Guide"},
    {"id": "PLAlJMCpP7EMI", "title": "卓球ニュース・最新トピック（速報・時事） | Table Tennis News & Current Topics"},
    {"id": "PLJ-F0GSgaPjw", "title": "グリップ・サイドテープ・コーティングなど周辺用具 | Accessories Guide (Grip & Side Tapes)"},
    {"id": "PLYLnjuOvJ61Y", "title": "用具選びの戦略：スタイル別ラケット＆ラバー構成 | Equipment Setup by Playstyle"},
    {"id": "PLKYvoOWkke0g", "title": "卓球界の「なぜ？」を深掘り：業界・ビジネス分析 | Why? Industry & Business Analysis"},
    {"id": "PLPSvAGol6Cpw", "title": "中学校部活動・地域移行・卓球普及の現在 | School Sports & Regional Transition"},
    {"id": "PLcjMwmOdnrtg", "title": "AliExpress・海外通販で賢く買う | Buying Smart on AliExpress & Global Stores"},
    {"id": "PLKVj34ZZEyPY", "title": "中国メーカー深掘り（DHS・銀河・SANWEI・LOKI等） | Chinese Brands Deep Dive"},
    {"id": "PLe_FuyqYUYeA", "title": "ラバーメンテナンス・保護・保管の正しい知識 | Rubber Maintenance & Storage Guide"},
    {"id": "PLfTnsjCwPWds", "title": "接着・貼り付けのプロ技術（ラバー接着剤マスター） | Pro Gluing & Assembly Techniques"},
    {"id": "PLIsVdg_Kwbpk", "title": "「同じ」用具を探す！代替品・類似品シリーズ | Equipment Clones & Alternatives"},
    {"id": "PLe6klWWrufQ8", "title": "特殊素材ラケット完全ガイド（カーボン・ZLC等） | Composite Blades Guide (ALC, ZLC, Carbon)"},
    {"id": "PLd_jaNWqKvBI", "title": "ラケット木材・構造・物理の科学 | Blade Wood Science & Structural Physics"},
    {"id": "PLY4Mm1mwEcv0", "title": "補助剤・ブースターの真実 | The Truth About Boosters & Tuning"},
    {"id": "PLZgEXv6tniy4", "title": "粘着ラバー徹底解説（中国ラバー専門）| Sticky Rubber Deep Dive (Chinese Rubber)"},
    {"id": "PLfmhWmQvgpqo", "title": "ラバーの科学と物理：裏ソフト・表ソフト・粒高・アンチ | Rubber Science & Physics"},
    {"id": "PLEcIkI6D0U3U", "title": "注目選手・レジェンドプレイヤー特集 | Featured Players & Legends"},
    {"id": "PLdZGgbtjqF9k", "title": "卓球ルール・大会・トーナメント完全ガイド | Table Tennis Rules, Tournaments & Competition Guide"}
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

def contains_japanese(text):
    """Checks if text contains Japanese Hiragana, Katakana, or common Kanji."""
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def has_japanese_kana(text):
    """Checks if text contains Japanese Hiragana or Katakana."""
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text))

def fetch_published_playlists():
    """Fetches all published playlists from YouTube, with static backup fallback."""
    playlists = []
    seen_ids = set()
    playlists_url = "https://www.youtube.com/@ToriShiraChannel/playlists"
    try:
        ydl_opts = {'extract_flat': True, 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(playlists_url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                pl_id = e.get('id') or ""
                if pl_id and t and pl_id not in seen_ids:
                    seen_ids.add(pl_id)
                    playlists.append({
                        'id': pl_id,
                        'title': t,
                        'url': f"https://www.youtube.com/playlist?list={pl_id}",
                        'description': f"再生リスト: {t}",
                        'is_playlist': True
                    })
    except Exception as e:
        logging.warning(f"Warning fetching playlists dynamically: {e}")

    # Fallback to ensure all static playlists are included
    for sp in STATIC_PLAYLISTS:
        if sp['id'] not in seen_ids:
            seen_ids.add(sp['id'])
            playlists.append({
                'id': sp['id'],
                'title': sp['title'],
                'url': f"https://www.youtube.com/playlist?list={sp['id']}",
                'description': f"再生リスト: {sp['title']}",
                'is_playlist': True
            })

    print(f"Total published playlists active: {len(playlists)}")
    return playlists

def fetch_multilingual_target_videos():
    """Fetches items from BOTH channels for multi-lingual promotion:
    1. Tori-Shira TT Lab (@Tori-ShiraTTLab/videos)
    2. Tori-Shira Main Channel (@ToriShiraChannel/videos) - Excluding members-only
    3. Featured / Target Videos
    4. All Playlists (Bilingual titles)
    """
    items = []
    seen_ids = set()
    
    # 1. Tori-Shira TT Lab Videos
    try:
        url_ttlab = "https://www.youtube.com/@Tori-ShiraTTLab/videos"
        ydl_opts = {'extract_flat': True, 'quiet': True, 'playlistend': 30}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(url_ttlab, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                v_id = e.get('id') or ""
                if v_id and t and v_id not in seen_ids:
                    seen_ids.add(v_id)
                    items.append({
                        'id': v_id,
                        'title': t,
                        'url': f"https://www.youtube.com/watch?v={v_id}",
                        'description': t,
                        'source': 'TTLab',
                        'is_playlist': False
                    })
    except Exception as e:
        logging.warning(f"Warning fetching TTLab videos: {e}")

    # 2. Main Channel Videos (@ToriShiraChannel/videos) - Excluding members-only
    try:
        url_main = "https://www.youtube.com/@ToriShiraChannel/videos"
        ydl_opts = {'extract_flat': True, 'quiet': True, 'playlistend': 40}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(url_main, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                t = e.get('title') or ""
                v_id = e.get('id') or ""
                if "メンバー限定" in t or "Members-only" in t:
                    continue
                if v_id and t and v_id not in seen_ids:
                    seen_ids.add(v_id)
                    items.append({
                        'id': v_id,
                        'title': t,
                        'url': f"https://www.youtube.com/watch?v={v_id}",
                        'description': t,
                        'source': 'Main',
                        'is_playlist': False
                    })
    except Exception as e:
        logging.warning(f"Warning fetching Main Channel videos for multilingual target: {e}")

    # 3. Explicitly featured target videos
    target_videos = [
        {
            'id': '_lAcFW-besQ',
            'title': '[Table Tennis] Super Cheap Membership!: Tori-Shira TT Lab (AI ANALYSIS)',
            'url': 'https://www.youtube.com/watch?v=_lAcFW-besQ',
            'description': '[Table Tennis] Super Cheap Membership!: Tori-Shira TT Lab (AI ANALYSIS)',
            'source': 'Featured',
            'is_playlist': False
        }
    ]
    for tv in target_videos:
        if tv['id'] not in seen_ids:
            seen_ids.add(tv['id'])
            items.append(tv)

    # 4. Include all playlists in multilingual pool
    playlists = fetch_published_playlists()
    for pl in playlists:
        if pl['url'] not in seen_ids:
            seen_ids.add(pl['url'])
            title_parts = pl['title'].split("|")
            eng_title = title_parts[1].strip() if len(title_parts) > 1 else pl['title']
            items.append({
                'id': pl['id'],
                'title': f"Table Tennis Playlist: {eng_title}",
                'url': pl['url'],
                'description': f"Official Playlist: {eng_title}",
                'source': 'Playlist',
                'is_playlist': True
            })

    print(f"Total multi-lingual candidate pool (videos + playlists) from BOTH channels: {len(items)}")
    return items

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

def get_current_active_handle(page):
    """Extracts active handle directly from profile link href and account switcher with 100% precision."""
    try:
        # 1. Primary Check: Profile link on left sidebar (e.g. href="/ToriShiraChanne" or href="/ToriShiraCh")
        prof_link = page.locator("a[data-testid='AppTabBar_Profile_Link']").first
        if prof_link.count():
            href = prof_link.get_attribute("href") or ""
            handle = href.strip("/").lower()
            if handle in ["torishirachanne", "torishirach"]:
                return f"@{handle}"

        # 2. Secondary Check: Account switcher button text
        sw = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
        if sw.count():
            txt = sw.inner_text().strip()
            # Match @torishirachanne or @torishirach explicitly
            if "@torishirachanne" in txt.lower():
                return "@torishirachanne"
            if "@torishirach" in txt.lower():
                return "@torishirach"
    except Exception:
        pass
    return ""

def switch_x_account(page, target_handle):
    """Switches X account and strictly verifies that the active account exactly matches target_handle."""
    clean_target = target_handle.strip().lower().replace("@", "")
    target_full = f"@{clean_target}"
    try:
        page.set_viewport_size({"width": 1600, "height": 900})
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        
        cur_handle = get_current_active_handle(page)
        if cur_handle == target_full:
            print(f"PASSED: Verified active X account is {target_full}.")
            return True
            
        print(f"Active account is '{cur_handle}', switching to '{target_full}'...")
        switcher = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
        if switcher.count():
            switcher.click(force=True)
            time.sleep(3)
            
            # Find the exact row in menu
            rows = page.locator("#layers [data-testid='AccountSwitcher_Account_Row'], #layers div[role='menuitem'], #layers a").all()
            target_item = None
            for r in rows:
                try:
                    href = r.get_attribute("href") or ""
                    txt = r.inner_text().strip().lower()
                    if clean_target == "torishirach":
                        if "/torishirachanne" in href.lower() or "@torishirachanne" in txt:
                            continue
                        if "/torishirach" in href.lower() or "@torishirach" in txt:
                            target_item = r
                            break
                    elif clean_target == "torishirachanne":
                        if "/torishirachanne" in href.lower() or "@torishirachanne" in txt:
                            target_item = r
                            break
                except Exception:
                    pass
                    
            if target_item:
                print(f"Clicking account row for {target_full}...")
                target_item.click(force=True)
                time.sleep(6)
                
                # STRICT RE-VERIFY AFTER SWITCH:
                page.goto("https://x.com/home", wait_until="domcontentloaded")
                time.sleep(4)
                sw_after = get_current_active_handle(page)
                if sw_after == target_full:
                    print(f"🎉 Successfully switched and verified account {target_full}!")
                    return True
            else:
                print(f"Menu item for {target_full} not found in switcher popup.")
                page.keyboard.press("Escape")
                
        # Final check
        if get_current_active_handle(page) == target_full:
            return True
            
        print(f"⛔ [STRICT CHECK FAILED] Could not switch to {target_full}. Current active: '{get_current_active_handle(page)}'.")
        return False
    except Exception as e:
        logging.error(f"X switch error: {e}")
        return False

def post_to_x(page, text, target_handle):
    clean_target = target_handle.strip().lower().replace("@", "")
    target_full = f"@{clean_target}"
    try:
        # =========================================================================
        # DEFENSE LAYER 1: STRICT CONTENT-LEVEL LANGUAGE ENFORCEMENT
        # =========================================================================
        if target_full == "@torishirachanne":
            # @ToriShiraChanne MUST be 100% Japanese.
            if not contains_japanese(text):
                logging.critical(f"⛔ [CRITICAL CONTENT BLOCK] Refusing post to {target_full}: Text has NO Japanese characters!\nBlocked text:\n{text}")
                print(f"⛔ [CRITICAL CONTENT BLOCK] Refusing post to {target_full}: Content is not Japanese!")
                return False
        elif target_full == "@torishirach":
            # @ToriShiraCh MUST NOT contain any Japanese Kana.
            if has_japanese_kana(text):
                logging.critical(f"⛔ [CRITICAL CONTENT BLOCK] Refusing post to {target_full}: Text contains Japanese Kana!\nBlocked text:\n{text}")
                print(f"⛔ [CRITICAL CONTENT BLOCK] Refusing post to {target_full}: Content contains Japanese characters!")
                return False

        # =========================================================================
        # DEFENSE LAYER 2: STRICT ACCOUNT SWITCHING & VERIFICATION
        # =========================================================================
        if not switch_x_account(page, target_full):
            logging.warning(f"⛔ [STRICT ABORT] Active account is NOT {target_full}. Skipping post.")
            print(f"⛔ [STRICT ABORT] Refusing to post because active account is NOT {target_full}. Skipping post.")
            return False
            
        # =========================================================================
        # DEFENSE LAYER 3: PRE-SUBMIT VERIFICATION (VERIFY ACTIVE ACCOUNT IN DOM)
        # =========================================================================
        active_handle = get_current_active_handle(page)
        if active_handle != target_full:
            logging.critical(f"⛔ [PRE-CLICK BLOCK] Active account '{active_handle}' != target '{target_full}'. Aborting!")
            print(f"⛔ [PRE-CLICK BLOCK] Active account '{active_handle}' != target '{target_full}'. Aborting!")
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
        print(f"Successfully posted to X [{target_full}]!")
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
    
    # Task 1, 2, 3: Multilingual promotion pool from BOTH channels + ALL Playlists (12 foreign languages only)
    multilingual_items = fetch_multilingual_target_videos()
    if multilingual_items:
        non_recent = [v for v in multilingual_items if v['url'] not in state.get("history", [])]
        chosen_item = random.choice(non_recent if non_recent else multilingual_items)
        print(f"Selected item for Multilingual Promotion: {chosen_item['title']} [{chosen_item['source']}] ({chosen_item['url']})")
        
        is_playlist = chosen_item.get('is_playlist', False)
        
        if is_playlist:
            raw_title = chosen_item['title'].replace("Table Tennis Playlist: ", "").strip()
            trans_title = llm_client.translate_title(raw_title, lang['name']) or raw_title
            trans_desc = f"Discover comprehensive table tennis tutorials, gear tests, and match strategies in this official playlist."
            x_foreign_text = f"🎬 Table Tennis Playlist: {trans_title}\n\nCheck out the curated video collection!\n\n#TableTennis #PingPong #ToriShiraTTLab\n\n{chosen_item['url']}"
        else:
            trans_title = llm_client.translate_title(chosen_item['title'], lang['name']) or chosen_item['title']
            trans_desc = llm_client.translate_text(chosen_item['description'], lang['name']) or chosen_item['description']
            
            # Check no Japanese kana in foreign post
            if has_japanese_kana(trans_title) or has_japanese_kana(trans_desc):
                trans_title = llm_client.translate_title(chosen_item['title'], "英語")
                trans_desc = llm_client.translate_text(chosen_item['description'], "英語")
                
            x_foreign_text = llm_client.generate_x_post(trans_title, chosen_item['url'], lang['name'], is_collab=True)
            
            # Ensure foreign post NEVER has kana
            if has_japanese_kana(x_foreign_text):
                x_foreign_text = llm_client.generate_x_post(trans_title, chosen_item['url'], "英語", is_collab=True)
        
        # 1. Hatena Blog (12 foreign languages)
        if not is_playlist:
            embed_html = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{chosen_item["id"]}" frameborder="0" allowfullscreen></iframe>'
        else:
            embed_html = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/videoseries?list={chosen_item["id"]}" frameborder="0" allowfullscreen></iframe>'
            
        hatena_title = f"{trans_title} - Tori-Shira TT Lab"
        hatena_content = f"<p><b>Tori-Shira TT Lab</b></p><h3>{trans_title}</h3>{embed_html}<p>{trans_desc}</p><p><a href='{chosen_item['url']}'>Watch on YouTube</a></p>"
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
                
                # 3. YouTube Community (@Tori-ShiraTTLab - 12 Foreign Languages ONLY)
                yt_text = f"🎬 {trans_title}\n\n{trans_desc}\n\n{chosen_item['url']}\n\n#TableTennis #ToriShiraTTLab"
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
                
        state["history"].append(chosen_item['url'])
        state["last_lang_index"] = lang_index + 1
        if len(state["history"]) > 50:
            state["history"] = state["history"][-50:]
        save_state(state)
        print("=== Cloud Job Completed Successfully ===")

if __name__ == "__main__":
    run_cloud_job()
