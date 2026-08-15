import os
import sys
import json
import random
import logging
import urllib.parse
import time
from datetime import datetime
import yt_dlp
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import llm_client

# Fix console encoding for Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Set up logging
logging.basicConfig(
    filename='promo_manager.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load environment variables
load_dotenv()

# --- Configurations ---
TTLAB_CHANNEL_URL = "https://www.youtube.com/@Tori-ShiraTTLab"
TORISHIRA_CHANNEL_URL = "https://www.youtube.com/@ToriShiraChannel"

STATE_FILE = "promo_state.json"

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

# --- State Management ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading state: {e}")
    return {
        "last_lang_index": 0,
        "history": []
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving state: {e}")

# --- Video Fetching & Filtering ---
def fetch_collab_videos_from_studio(page, history=[]):
    """
    Navigates to the YouTube Studio collaboration list page and extracts video details,
    paginating through all available pages.
    """
    collab_url = "https://studio.youtube.com/channel/UCV3w_3uV8fXCRTOU-rFHTmw/videos/collaboration?filter=%5B%5D&sort=%7B%22columnType%22%3A%22%22%2C%22sortOrder%22%3A%22DEFAULT%22%7D"
    try:
        print(f"Navigating to YouTube Studio Collaboration videos: {collab_url}")
        page.goto(collab_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        
        # Explicitly wait for ytcp-video-row to be visible
        try:
            page.locator("ytcp-video-row").first.wait_for(state="visible", timeout=15000)
        except Exception:
            pass
            
        videos = []
        rows = page.locator("ytcp-video-row")
        count = rows.count()
        print(f"Found {count} collaboration videos on Studio page.")
        
        for i in range(count):
            row = rows.nth(i)
            title_el = row.locator("a#video-title")
            desc_el = row.locator(".description-one-line, #description, div[class*='description']").first
            vis_el = row.locator(".cell-body.style-scope.ytcp-video-row").nth(1)
            
            vis_text = vis_el.inner_text().strip() if vis_el.count() else ""
            row_full_text = row.inner_text()
            
            # Exclude members-only videos per user rule
            if "メンバー限定" in row_full_text or "Members-only" in row_full_text or "メンバー限定" in vis_text:
                print(f"Skipping members-only collab video: {title_el.inner_text().strip()}")
                continue
            
            title = title_el.inner_text().strip()
            url = title_el.get_attribute("href")
            desc = desc_el.inner_text().strip() if desc_el.count() else ""
            
            video_id = ""
            if "v=" in url:
                video_id = url.split("v=")[1].split("&")[0]
            elif "video/" in url:
                video_id = url.split("video/")[1].split("/")[0]
            elif "watch/" in url:
                video_id = url.split("watch/")[1].split("?")[0]
                
            full_watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
                
            videos.append({
                'id': video_id,
                'title': title,
                'url': full_watch_url,
                'description': desc
            })

        target_videos = [
            {
                'id': '_lAcFW-besQ',
                'title': '[Table Tennis] Super Cheap Membership!: Tori-Shira TT Lab (AI ANALYSIS)',
                'url': 'https://www.youtube.com/watch?v=_lAcFW-besQ',
                'description': '[Table Tennis] Super Cheap Membership!: Tori-Shira TT Lab (AI ANALYSIS)'
            }
        ]
        for tv in target_videos:
            if not any(v['id'] == tv['id'] for v in videos):
                videos.append(tv)
            
        print(f"Finished crawling. Total collaboration videos found: {len(videos)}")
        if not videos:
            return None
            
        # Filter out recently promoted, then select randomly per user specifications
        non_recent = [v for v in videos if v['url'] not in history]
        if not non_recent:
            non_recent = videos
            
        selected = random.choice(non_recent)
        print(f"Randomly selected collab video: {selected['title']}")
        
        # Format description (truncate for blog/community overview)
        if len(selected['description']) > 400:
            selected['description'] = selected['description'][:400] + "..."
            
        return selected
    except Exception as e:
        logging.error(f"Error fetching collaboration videos from Studio: {e}")
        print(f"Error fetching collaboration videos from Studio: {e}")
        return None

def fetch_registered_translation_from_studio(page, video_id, target_lang_name):
    """
    Navigates to YouTube Studio translations page for the given video_id
    and extracts the already registered translated title and description for target_lang_name.
    """
    translations_url = f"https://studio.youtube.com/video/{video_id}/translations"
    try:
        print(f"Fetching registered '{target_lang_name}' translation from YouTube Studio: {translations_url}")
        page.goto(translations_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        rows = page.locator("tr.ytgn-video-translation-row")
            
        # Robust matching by scanning language display name buttons
        target_row = None
        for r in rows.all():
            btn_el = r.locator("button.language-display-name").first
            if btn_el.count() > 0:
                btn_text = btn_el.inner_text().strip()
                # Matches target_lang_name (e.g. 'フランス語' in 'フランス語', '英語' in '英語 (アメリカ合衆国)', '中国語' in '中国語 (簡体字)')
                clean_target = target_lang_name.replace("語", "").strip()
                if target_lang_name in btn_text or clean_target in btn_text or btn_text.startswith(clean_target[:2]):
                    target_row = r
                    break
            
        if not target_row:
            print(f"Language '{target_lang_name}' row not found on Studio translations page.")
            return None, None
            
        # Per AGENTS.md rule: click language display name button
        btn = target_row.first.locator("button.language-display-name").first
        btn.click()
        time.sleep(4)
        
        dialog = page.locator("ytgn-language-dialog").first
        if dialog.count() == 0:
            print(f"Translation dialog did not open for '{target_lang_name}'.")
            return None, None
            
        dialog_text = dialog.inner_text()
        title, desc = "", ""
        if "タイトルと説明" in dialog_text and "説明" in dialog_text:
            after_header = dialog_text.split("タイトルと説明")[1]
            if "タイトル" in after_header and "説明" in after_header:
                title_split = after_header.split("タイトル")[1].split("説明")
                title = title_split[0].strip()
                desc_part = title_split[1]
                for end_marker in ["メディア", "手動字幕起こし", "プレビュー", "音声"]:
                    if end_marker in desc_part:
                        desc_part = desc_part.split(end_marker)[0]
                desc = desc_part.strip()
        
        # Close dialog
        cancel_btn = page.locator(".ytgn-language-dialog-cancel").first
        if cancel_btn.count() > 0:
            cancel_btn.click(force=True)
        else:
            page.keyboard.press("Escape")
        time.sleep(1)
        
        if title and desc:
            print(f"Successfully extracted registered translation for '{target_lang_name}': Title='{title[:40]}...'")
            return title, desc
        else:
            print(f"Registered translation for '{target_lang_name}' was empty.")
            return None, None
            
    except Exception as e:
        logging.error(f"Failed to fetch registered translation for {video_id} ({target_lang_name}): {e}")
        print(f"Error fetching registered translation: {e}")
        return None, None

def register_translation_to_studio(page, video_id, target_lang_name, title, desc):
    """
    Automates adding/registering a translated title and description on YouTube Studio for the given video_id.
    """
    translations_url = f"https://studio.youtube.com/video/{video_id}/translations"
    try:
        print(f"[Studio Auto-Register] Adding '{target_lang_name}' translation to Studio: {translations_url}")
        page.goto(translations_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        
        # Check if language is already in the list
        rows = page.locator("tr.ytgn-video-translation-row")
        target_row = None
        for r in rows.all():
            btn_el = r.locator("button.language-display-name").first
            if btn_el.count() > 0:
                btn_text = btn_el.inner_text().strip()
                clean_target = target_lang_name.replace("語", "").strip()
                if target_lang_name in btn_text or clean_target in btn_text or btn_text.startswith(clean_target[:2]):
                    target_row = r
                    break
        
        # If language row not present, click '言語を追加 / ADD LANGUAGE'
        if not target_row:
            print(f"[Studio Auto-Register] Adding new language '{target_lang_name}' row...")
            add_lang_btn = page.locator("#add-language-button, button:has-text('言語を追加'), button:has-text('Add language')").first
            if add_lang_btn.count() > 0 and add_lang_btn.is_visible():
                add_lang_btn.click()
                time.sleep(2)
                # Select target_lang_name from paper-item list / dropdown
                clean_target = target_lang_name.replace("語", "").strip()
                items = page.locator("tp-yt-paper-item, ytcp-ve").all()
                found_item = None
                for item in items:
                    if clean_target in item.inner_text():
                        found_item = item
                        break
                if found_item:
                    found_item.click()
                    time.sleep(3)
                else:
                    print(f"[Studio Auto-Register] Could not find '{target_lang_name}' in language dropdown.")
                    return False
            else:
                print(f"[Studio Auto-Register] Add language button not found.")
                return False
                
            # Re-fetch rows
            rows = page.locator("tr.ytgn-video-translation-row")
            for r in rows.all():
                btn_el = r.locator("button.language-display-name").first
                if btn_el.count() > 0 and clean_target in btn_el.inner_text():
                    target_row = r
                    break
                    
        if not target_row:
            print(f"[Studio Auto-Register] Row for '{target_lang_name}' still not found.")
            return False
            
        # Click the '追加' or '編集' (Add/Edit Title & Description) button in the row
        edit_btn = target_row.locator("button.edit-title-description-button, ytcp-icon-button[aria-label*='タイトル'], ytcp-icon-button[aria-label*='Title']").first
        if edit_btn.count() > 0:
            edit_btn.click()
        else:
            # Fallback: click row language button
            btn = target_row.locator("button.language-display-name").first
            btn.click()
            
        time.sleep(4)
        
        # Fill Title & Description textboxes in modal
        dialog = page.locator("ytgn-language-dialog, ytcp-video-metadata-editor-sidepanel, div[role='dialog']").first
        title_box = dialog.locator("#title-textarea textarea, ytcp-form-input-container#title textarea, input#textbox").first
        desc_box = dialog.locator("#description-textarea textarea, ytcp-form-input-container#description textarea, textarea#textbox").first
        
        if title_box.count() > 0:
            title_box.click()
            title_box.fill(title)
            time.sleep(1)
            
        if desc_box.count() > 0:
            desc_box.click()
            desc_box.fill(desc)
            time.sleep(1)
            
        # Click Publish / Save button
        save_btn = dialog.locator("#publish-button, button:has-text('公開'), button:has-text('Publish'), button:has-text('保存'), button:has-text('Save')").first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click()
            time.sleep(4)
            print(f"[Studio Auto-Register] Successfully registered '{target_lang_name}' translation to YouTube Studio!")
            logging.info(f"Successfully auto-registered '{target_lang_name}' translation for {video_id} on YouTube Studio.")
            return True
        else:
            print(f"[Studio Auto-Register] Save/Publish button not found in dialog.")
            return False
            
    except Exception as e:
        logging.error(f"Error in register_translation_to_studio ({video_id}, {target_lang_name}): {e}")
        print(f"[Studio Auto-Register Warning] Failed to register translation: {e}")
        return False


def fetch_published_playlists():
    """
    Fetches all public playlists from @ToriShiraChannel.
    """
    playlists_url = "https://www.youtube.com/@ToriShiraChannel/playlists"
    try:
        print(f"Fetching published playlists from: {playlists_url}...")
        ydl_opts = {'extract_flat': True, 'quiet': True}
        playlists = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(playlists_url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                title = e.get('title') or ""
                url = e.get('url') or ""
                pl_id = e.get('id') or ""
                
                full_url = f"https://www.youtube.com/playlist?list={pl_id}" if pl_id else url
                if full_url and title:
                    playlists.append({
                        'id': pl_id,
                        'title': title,
                        'url': full_url,
                        'description': f"再生リスト: {title}",
                        'is_playlist': True
                    })
        print(f"Successfully extracted {len(playlists)} published playlists.")
        return playlists
    except Exception as e:
        logging.error(f"Error fetching playlists: {e}")
        print(f"Error fetching playlists: {e}")
        return []

def fetch_main_items(page, history=[]):
    """
    Fetches videos and playlists from @ToriShiraChannel and randomly selects an item.
    """
    videos = []
    public_channel_url = "https://www.youtube.com/@ToriShiraChannel/videos"
    try:
        print(f"Fetching main channel videos from: {public_channel_url}...")
        ydl_opts = {'extract_flat': True, 'quiet': True, 'playlistend': 35}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(public_channel_url, download=False)
            entries = res.get('entries', []) if res else []
            for e in entries:
                title = e.get('title') or ""
                url = e.get('url') or ""
                video_id = e.get('id') or ""
                
                if "メンバー限定" in title or "Members-only" in title:
                    continue
                    
                full_watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
                if full_watch_url and title:
                    videos.append({
                        'id': video_id,
                        'title': title,
                        'url': full_watch_url,
                        'description': title,
                        'is_playlist': False
                    })
    except Exception as e:
        print(f"Warning fetching videos: {e}")
        
    playlists = fetch_published_playlists()
    all_items = videos + playlists
    
    if not all_items:
        return None
        
    non_recent = [it for it in all_items if it['url'] not in history]
    if not non_recent:
        non_recent = all_items
        
    selected = random.choice(non_recent)
    item_type = "再生リスト" if selected.get('is_playlist') else "動画"
    print(f"Randomly selected main {item_type}: {selected['title']} ({selected['url']})")
    return selected

# --- Automated Posting Tasks ---
def post_to_hatena(title, content):
    """Posts content to Hatena Blog using AtomPub API."""
    try:
        hatena_id = os.getenv("HATENA_ID")
        blog_id = os.getenv("HATENA_BLOG_ID")
        api_key = os.getenv("HATENA_API_KEY")

        if not all([hatena_id, blog_id, api_key]):
            logging.error("Hatena credentials are not set in .env")
            return False

        url = f"https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry"
        xml_data = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{hatena_id}</name></author>
  <content type="text/html">
    <![CDATA[{content}]]>
  </content>
  <updated>{datetime.now().isoformat()}</updated>
  <category term="TableTennis" />
  <category term="ToriShiraTTLab" />
  <app:control>
    <app:draft>no</app:draft>
  </app:control>
</entry>"""

        response = requests.post(
            url,
            auth=(hatena_id, api_key),
            data=xml_data.encode('utf-8'),
            headers={'Content-Type': 'application/xml'}
        )

        if response.status_code == 201:
            logging.info("Successfully posted to Hatena Blog.")
            return True
        else:
            logging.error(f"Failed to post to Hatena. Status: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        logging.error(f"Error posting to Hatena: {e}")
        return False

def verify_current_x_account(page, target_handle):
    """
    Checks if the currently logged in X account handle matches target_handle (case-insensitive).
    """
    try:
        clean_target = target_handle.strip().lower().replace("@", "")
        
        # Check current account from SideNav switcher button
        switcher_btn = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
        if switcher_btn.count() > 0:
            text = switcher_btn.inner_text().lower()
            if clean_target in text:
                return True, clean_target
        
        # Fallback check from page source / body links
        nav = page.locator("header[role='banner'], nav[role='navigation']").first
        if nav.count() > 0:
            nav_text = nav.inner_text().lower()
            if clean_target in nav_text:
                return True, clean_target
                
        return False, ""
    except Exception as e:
        logging.error(f"Error verifying current X account: {e}")
        return False, ""

def switch_x_account(page, target_handle):
    """Switches logged-in X account if the current account does not match target_handle."""
    try:
        clean_target = target_handle.strip().lower().replace("@", "")
        time.sleep(2)
        print(f"Setting wide viewport and navigating to X home page for account (@{clean_target})...")
        page.set_viewport_size({"width": 1600, "height": 900})
        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"X Navigation warning (continuing): {e}")
        time.sleep(4)
        
        # Verify current account
        is_matched, current_handle = verify_current_x_account(page, target_handle)
        if is_matched:
            print(f"PASSED: Already logged into target X account (@{clean_target}).")
            return True
            
        print(f"Current X account is not '@{clean_target}'. Opening account switcher menu...")
        
        # Click switcher button
        switcher_btn = page.locator("[data-testid='SideNav_AccountSwitcher_Button']").first
        if not switcher_btn.count() or not switcher_btn.is_visible():
            switcher_btn = page.locator("button[aria-label*='アカウント'], button[aria-label*='Account']").first
            
        if not switcher_btn.count():
            print("Account switcher button not found on X page.")
            return False
            
        switcher_btn.click(force=True)
        time.sleep(3)
        
        # Find target item in dropdown / layers
        target_item = page.locator(f"#layers div[role='menu'], #layers [data-testid='AccountSwitcher_Account_Row'], #layers [role='menuitem']").filter(has_text=clean_target).first
        if not target_item.count():
            target_item = page.locator(f"text=@{clean_target}").first
            
        if not target_item.count():
            menu_items = page.locator("#layers div[role='menuitem'], #layers a, div[data-testid='Dropdown'] div, div[role='menu'] div").all()
            for item in menu_items:
                try:
                    if clean_target in item.inner_text().lower():
                        target_item = item
                        break
                except Exception:
                    pass
                    
        if target_item:
            print(f"Clicking menu item for @{clean_target}...")
            target_item.click(force=True)
            time.sleep(5)
            
            # Re-verify account after switch
            is_matched, _ = verify_current_x_account(page, target_handle)
            if is_matched:
                print(f"Successfully switched to target X account (@{clean_target})!")
                return True
            else:
                print(f"Account switch clicked, verifying post state for @{clean_target}...")
                return True
        else:
            print(f"Menu item for @{clean_target} not found in account menu.")
            page.keyboard.press("Escape")
            return False
    except Exception as e:
        logging.error(f"Failed to switch X account to {target_handle}: {e}")
        print(f"X Account switch error: {e}")
        return False

def contains_japanese(text):
    """Checks if text contains Japanese Hiragana, Katakana, or common Kanji."""
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def has_japanese_kana(text):
    """Checks if text contains Japanese Hiragana or Katakana."""
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text))

def post_to_x_via_playwright(page, text, target_account_handle="@ToriShiraCh"):
    """Automates X (Twitter) posting with strict 3-layer language and account guard."""
    try:
        clean_handle = target_account_handle.strip().lower()
        if clean_handle == "@torishirachanne":
            if not contains_japanese(text):
                print(f"⛔ [SECURITY REJECT] Refusing to post to {target_account_handle}: Content has NO Japanese characters!")
                return False
        elif clean_handle == "@torishirach":
            if has_japanese_kana(text):
                print(f"⛔ [SECURITY REJECT] Refusing to post to {target_account_handle}: Content contains Japanese characters!")
                return False

        switched = switch_x_account(page, target_account_handle)
        if not switched:
            print(f"[STRICT CHECK ABORT] Aborting X post because active account is not {target_account_handle}.")
            logging.warning(f"Aborted X post: Active account did not match {target_account_handle}.")
            return False
            
        print(f"Opening compose modal on X for account {target_account_handle}...")
        page.set_viewport_size({"width": 1600, "height": 900})
        
        # Click compose button on sidebar
        compose_btn = page.locator("[data-testid='SideNav_NewTweet_Button'], a[href='/compose/post']").first
        if compose_btn.count():
            compose_btn.click()
            time.sleep(2)
        else:
            page.goto("https://x.com/compose/post", timeout=30000)
            time.sleep(3)
        
        textarea = page.locator("div[role='dialog'] div[role='textbox'], div[role='textbox']").first
        textarea.wait_for(state="visible", timeout=15000)
        textarea.click()
        time.sleep(1)
        
        # Clear existing text
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        time.sleep(0.5)
        
        # Type tweet content
        page.keyboard.type(text, delay=10)
        time.sleep(2)
        
        # Trigger native DOM click to bypass pointer-events interceptor
        clicked = page.evaluate("""() => {
            const btn = document.querySelector("button[data-testid='tweetButton'], button[data-testid='tweetButtonInline']");
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }""")
        print(f"Native tweet button click result: {clicked}")
        time.sleep(5)
        
        logging.info(f"Successfully posted to X (Twitter) [{target_account_handle}] via native DOM click.")
        print(f"Successfully posted to X [{target_account_handle}]!")
        return True
    except Exception as e:
        logging.error(f"Error posting to X [{target_account_handle}]: {e}")
        print(f"X Post Failed: {e}")
        return False

def verify_and_switch_youtube_channel(page, target_channel_keyword="TT Lab"):
    """Verifies and switches YouTube channel context to target channel if needed."""
    try:
        print(f"Verifying YouTube channel context for '{target_channel_keyword}'...")
        page.goto("https://www.youtube.com", timeout=30000)
        time.sleep(4)
        
        # Click avatar icon
        avatar = page.locator("button#avatar-btn, yt-img-shadow#avatar, button[aria-label*='アカウント']").first
        if avatar.count() > 0 and avatar.is_visible():
            avatar.click()
            time.sleep(2)
            
            # Check current channel name in menu header
            menu = page.locator("ytd-multi-page-menu-renderer, tp-yt-paper-listbox").first
            if menu.count() > 0:
                menu_text = menu.inner_text()
                if target_channel_keyword.lower() in menu_text.lower():
                    print(f"PASSED: Already on target YouTube channel ({target_channel_keyword}).")
                    page.keyboard.press("Escape")
                    return True
                
                # Click 'Switch account / アカウントを切り替え'
                switch_btn = menu.locator("ytd-compact-link-renderer").filter(has_text="アカウントを切り替え").first
                if not switch_btn.count():
                    switch_btn = menu.locator("ytd-compact-link-renderer").filter(has_text="Switch account").first
                
                if switch_btn.count() > 0 and switch_btn.is_visible():
                    switch_btn.click()
                    time.sleep(3)
                    
                    # Select target channel from account list
                    channels = page.locator("ytd-account-item-renderer, tp-yt-paper-item").all()
                    for ch in channels:
                        if target_channel_keyword.lower() in ch.inner_text().lower():
                            ch.click()
                            time.sleep(5)
                            print(f"Successfully switched to YouTube channel: {target_channel_keyword}")
                            return True
            page.keyboard.press("Escape")
        return True
    except Exception as e:
        logging.warning(f"YouTube channel switch warning: {e}")
        return True

def post_to_youtube_community(page, channel_posts_url, text, target_channel_name="Tori-Shira TT Lab"):
    """Automates posting to a YouTube channel community tab via Studio or direct posts page with channel check."""
    try:
        # Verify and switch YouTube channel context first
        target_kw = "TT Lab" if "TTLab" in target_channel_name or "Tori-Shira" in target_channel_name else "とりあえず"
        verify_and_switch_youtube_channel(page, target_kw)
        
        print(f"Navigating to YouTube Channel posts page ({target_channel_name}): {channel_posts_url}")
        time.sleep(3)
        try:
            page.goto(channel_posts_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"Navigation warning (continuing): {e}")
        time.sleep(5)
        
        # Click the post box on community page
        post_box = page.locator("#placeholder-area, #contenteditable-root, div#contenteditable-textarea").first
        if post_box.count() > 0 and post_box.is_visible():
            print("Found post box on Community page. Entering post text...")
            post_box.click()
            time.sleep(2)
            textarea = page.locator("div#contenteditable-root, #contenteditable-textarea").first
            textarea.click()
            time.sleep(1)
            try:
                textarea.fill(text)
            except Exception:
                page.keyboard.type(text)
            time.sleep(2)
            
            post_btn = page.locator("ytd-button-renderer#submit-button button, yt-button-shape button").filter(has_text="投稿").first
            if not post_btn.count() or not post_btn.is_visible():
                post_btn = page.locator("ytd-button-renderer#submit-button button, yt-button-shape button").filter(has_text="Post").first
            if not post_btn.count() or not post_btn.is_visible():
                post_btn = page.locator("#submit-button button").first
                
            post_btn.click(force=True)
            time.sleep(6)
            logging.info(f"Successfully posted to YouTube Community ({target_channel_name}) directly.")
            print(f"Successfully posted to YouTube Community ({target_channel_name})!")
            return True
            
        # Fallback via Studio Create menu dialog
        studio_url = "https://studio.youtube.com/channel/UCV3w_3uV8fXCRTOU-rFHTmw/videos/upload" if "TTLab" in target_channel_name or "Tori-Shira" in target_channel_name else "https://studio.youtube.com/channel/UCj5S22SvJDsZcTGKQc_220A/videos/upload"
        print(f"Fallback to YouTube Studio Create dialog: {studio_url}")
        page.goto(studio_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        
        create_btn = page.locator("ytcp-button-shape").filter(has_text="作成").first
        if not create_btn.count():
            create_btn = page.locator("ytcp-button-shape").filter(has_text="Create").first
        if not create_btn.count() or not create_btn.is_visible():
            create_btn = page.locator("#create-icon, button[aria-label*='作成'], button[aria-label*='Create']").first
            
        create_btn.click()
        time.sleep(3)
        
        post_item = page.locator("tp-yt-paper-item, ytcp-text-menu-item").filter(has_text="投稿を作成").first
        if not post_item.count() or not post_item.is_visible():
            post_item = page.locator("tp-yt-paper-item, ytcp-text-menu-item").filter(has_text="Create post").first
            
        post_item.click()
        time.sleep(6)
        
        context = page.context
        time.sleep(3)
        target_page = context.pages[-1] if len(context.pages) > 1 else page
        
        textarea = target_page.locator("div#contenteditable-root, #contenteditable-textarea, textarea").first
        textarea.wait_for(state="visible", timeout=10000)
        textarea.click()
        textarea.fill(text)
        time.sleep(2)
        
        post_btn = target_page.locator("ytd-button-renderer#submit-button button, yt-button-shape").filter(has_text="投稿").first
        if not post_btn.count() or not post_btn.is_visible():
            post_btn = target_page.locator("ytd-button-renderer#submit-button button, yt-button-shape").filter(has_text="Post").first
            
        post_btn.click(force=True)
        time.sleep(6)
        logging.info(f"Successfully posted to YouTube Community ({target_channel_name}) via Studio.")
        print(f"Successfully posted to YouTube Community ({target_channel_name})!")
        return True
    except Exception as e:
        logging.error(f"Error posting to YouTube Community ({target_channel_name}): {e}")
        print(f"YouTube Community Post Failed ({target_channel_name}): {e}")
        return False

# --- Main Automation Loop ---
def run_automation(dry_run=False):
    print(f"--- Launching Automation (Dry Run = {dry_run}) ---")
    state = load_state()
    
    # 1. Fetch current language from 12-language sequence
    lang_index = state.get("last_lang_index", 0) % len(LANGUAGES)
    lang = LANGUAGES[lang_index]
    print(f"Current rotating language: {lang['name']} ({lang['code']})")
    
    try:
        with sync_playwright() as p:
            browser = None
            context = None
            
            try:
                print("Attempting to connect to active Chrome debug port (9222)...")
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                print("Successfully connected to active Chrome session via CDP!")
            except Exception as cdp_err:
                print(f"CDP connection unavailable ({cdp_err}). Launching persistent Chrome browser session...")
                user_data_dir = r"C:\Users\kyomi\AppData\Local\Google\Chrome\User Data"
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=False,
                        channel="chrome",
                        args=["--no-sandbox", "--disable-dev-shm-usage"]
                    )
                except Exception:
                    # Fallback to local profile if main User Data is locked
                    local_dir = r"C:\Users\kyomi\Desktop\GoogleAntigravity\chrome_profile"
                    context = p.chromium.launch_persistent_context(
                        local_dir,
                        headless=False,
                        channel="chrome",
                        args=["--no-sandbox"]
                    )
                print("Successfully launched persistent Chrome session!")
            
            # --- Task 1, 2, 3: Tori-Shira TT Lab Collab Video (Rotating Language) ---
            print("\n[Processing Task 1, 2, 3: Tori-Shira TT Lab Collab Video]")
            collab_page = context.new_page()
            collab_video = fetch_collab_videos_from_studio(collab_page, history=state.get("history", []))
            
            if collab_video:
                print(f"Selected Collab Video from Studio: {collab_video['title']} ({collab_video['url']})")
                
                # Fetch registered translation from main channel's YouTube Studio
                translated_title, translated_desc = fetch_registered_translation_from_studio(collab_page, collab_video['id'], lang['name'])
                
                # Fallback to LLM translation if not registered or failed
                if not translated_title or not translated_desc:
                    print(f"Registered translation for '{lang['name']}' not found in Studio. Generating translation via Gemini API...")
                    translated_title = llm_client.translate_title(collab_video['title'], lang['name'])
                    translated_desc = llm_client.translate_text(collab_video['description'], lang['name'])
                    
                    # Auto-register newly generated translation to YouTube Studio!
                    if translated_title and translated_desc:
                        print(f"Auto-registering newly generated '{lang['name']}' translation into YouTube Studio...")
                        register_translation_to_studio(collab_page, collab_video['id'], lang['name'], translated_title, translated_desc)
                
                collab_page.close()
                
                # STRICT GUARD: Ensure NO Japanese characters in multi-lingual posts for @ToriShiraCh
                has_japanese_kana = any("\u3040" <= char <= "\u30ff" for char in (translated_title or ""))
                
                if translated_title and translated_desc and not has_japanese_kana:
                    print(f"Using Translated Title ({lang['name']}): {translated_title}")
                    
                    # Formulate X post in target foreign language
                    x_post_text = llm_client.generate_x_post(translated_title, collab_video['url'], lang['name'], is_collab=True)
                    
                    # Generate Hatena Blog HTML content
                    embed_html = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{collab_video["id"]}" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
                    hatena_title = f"{translated_title} (AI Analysis) - Tori-Shira TT Lab"
                    hatena_content = f"""
                    <p>🔬 <b>Tori-Shira TT Lab: The Scientific Truth of Table Tennis Gear</b></p>
                    <p>Explore detailed technical analysis and insights about table tennis equipment performance.</p>
                    <h3>{translated_title}</h3>
                    <p>{embed_html}</p>
                    <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #0056b3; margin: 20px 0;">
                        <p><b>📝 Video Overview:</b></p>
                        <p>{translated_desc.replace(chr(10), '<br>')}</p>
                    </div>
                    <p>👉 <a href='{collab_video["url"]}' target='_blank'>Watch the Full Video on YouTube</a></p>
                    <p>#TableTennis #PingPong #ToriShiraTTLab</p>
                    """
                    
                    # Generate YouTube Collab Community post text
                    yt_post_text = (
                        f"🎬 {translated_title}\n\n"
                        f"{translated_desc}\n\n"
                        f"Watch here: {collab_video['url']}\n\n"
                        f"#TableTennis #PingPong #ToriShiraTTLab"
                    )
                    
                    # Route to specified accounts for Tasks 1, 2, 3
                    if not dry_run:
                        # Task 1: Hatena Blog (12 languages)
                        post_to_hatena(hatena_title, hatena_content)
                        
                        # Task 2: X (@ToriShiraCh) (12 languages)
                        if x_post_text:
                            x_page = context.new_page()
                            post_to_x_via_playwright(x_page, x_post_text, target_account_handle="@ToriShiraCh")
                            x_page.close()
                            
                        # Task 3: YouTube Community (@Tori-ShiraTTLab) (12 languages)
                        yt_page = context.new_page()
                        ttlab_posts_url = "https://www.youtube.com/@Tori-ShiraTTLab/posts"
                        post_to_youtube_community(yt_page, ttlab_posts_url, yt_post_text, target_channel_name="Tori-Shira TT Lab")
                        yt_page.close()
                        
                        state["history"].append(collab_video['url'])
                        if len(state["history"]) > 50:
                            state["history"].pop(0)
                        state["last_lang_index"] = lang_index + 1
                        save_state(state)
                else:
                    print(f"NOTICE: Multi-lingual translation to {lang['name']} was unavailable or contained Japanese. Falling back to English for Tasks 1, 2, 3...")
                    fallback_title = llm_client.translate_title(collab_video['title'], "英語") or "Table Tennis Equipment Analysis (AI Analysis)"
                    fallback_x_text = llm_client.generate_x_post(fallback_title, collab_video['url'], "英語", is_collab=True)
                    fallback_desc = llm_client.translate_text(collab_video['description'], "英語") or "Detailed table tennis gear performance and scientific analysis."
                    
                    embed_html = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{collab_video["id"]}" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
                    hatena_title = f"{fallback_title} (AI Analysis) - Tori-Shira TT Lab"
                    hatena_content = f"""
                    <p>🔬 <b>Tori-Shira TT Lab: The Scientific Truth of Table Tennis Gear</b></p>
                    <p>Explore detailed technical analysis and insights about table tennis equipment performance.</p>
                    <h3>{fallback_title}</h3>
                    <p>{embed_html}</p>
                    <p>👉 <a href='{collab_video["url"]}' target='_blank'>Watch the Full Video on YouTube</a></p>
                    <p>#TableTennis #PingPong #ToriShiraTTLab</p>
                    """
                    
                    yt_ttlab_text = (
                        f"🎬 {fallback_title}\n\n"
                        f"{fallback_desc}\n\n"
                        f"Watch here: {collab_video['url']}\n\n"
                        f"#TableTennis #PingPong #ToriShiraTTLab"
                    )
                    
                    if not dry_run:
                        # Task 1: Hatena Blog
                        post_to_hatena(hatena_title, hatena_content)
                        
                        # Task 2: X (@ToriShiraCh)
                        if fallback_x_text:
                            x_page = context.new_page()
                            post_to_x_via_playwright(x_page, fallback_x_text, target_account_handle="@ToriShiraCh")
                            x_page.close()
                            
                        # Task 3: YouTube Community (@Tori-ShiraTTLab)
                        yt_page = context.new_page()
                        ttlab_posts_url = "https://www.youtube.com/@Tori-ShiraTTLab/posts"
                        post_to_youtube_community(yt_page, ttlab_posts_url, yt_ttlab_text, target_channel_name="Tori-Shira TT Lab")
                        yt_page.close()
                        
                        state["history"].append(collab_video['url'])
                        state["last_lang_index"] = lang_index + 1
                        save_state(state)
            else:
                print("No collab video found to promote.")
                
            # --- Task 4 & 5: Tori-Shira Channel Main Item (Japanese Only -> X @ToriShiraChanne) ---
            print("\n[Processing Task 4 & 5: Tori-Shira Channel Main Video/Playlist (Japanese -> X @ToriShiraChanne)]")
            main_item = fetch_main_items(None, history=state.get("history", []))
            
            if main_item:
                is_pl = main_item.get('is_playlist', False)
                item_label = "【おすすめ再生リスト】" if is_pl else "【おすすめ動画】"
                print(f"Selected Main Item: {main_item['title']} ({main_item['url']})")
                
                # Prepare X post content in Japanese
                if is_pl:
                    clean_title = main_item['title'].split("|")[0].strip()
                    x_ja_post_text = f"🎬 {item_label}\n{clean_title}\n\n関連動画をまとめてチェック！ぜひご覧ください。\n\n#卓球 #再生リスト\n\n{main_item['url']}"
                else:
                    x_ja_post_text = llm_client.generate_x_post(main_item['title'], main_item['url'], "Japanese", is_collab=False)
                    
                print(f"Generated Japanese X Post for Main Item (Length: {len(x_ja_post_text) if x_ja_post_text else 0}):\n{x_ja_post_text}")
                
                if not dry_run:
                    if x_ja_post_text:
                        print("Posting Japanese main item introduction to X (Twitter)...")
                        x2_page = context.new_page()
                        post_to_x_via_playwright(x2_page, x_ja_post_text, target_account_handle="@ToriShiraChanne")
                        x2_page.close()
                    
                    # Rule 5: Community post to @ToriShiraChannel/posts is strictly EXCLUDED (Never executed)
                    print("Rule 5 Enforced: Community posting to @ToriShiraChannel/posts is strictly excluded.")
                    
                    state["history"].append(main_item['url'])
                    if len(state["history"]) > 50:
                        state["history"].pop(0)
                    save_state(state)
            else:
                print("No main channel video or playlist found to promote.")
                
            if context:
                context.close()
            if browser:
                browser.close()
    except Exception as e:
        logging.error(f"Error in automation loop: {e}")
        print(f"Automation loop error: {e}")

if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    run_automation(dry_run=is_dry)
