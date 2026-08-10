import os
import json
import urllib.request
import logging
import time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Model fallback list: first available model will be used
# gemini-3.1-flash-lite confirmed working; others as fallback
MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
    "gemini-3.5-flash",
]
MODEL_NAME = MODEL_CANDIDATES[0]  # Will be updated at runtime if unavailable

# Track which model is currently active at module level
_active_model = None

def _get_active_model():
    """Returns the first working Gemini model from MODEL_CANDIDATES."""
    global _active_model
    if _active_model:
        return _active_model
    
    if not GEMINI_API_KEY:
        return MODEL_CANDIDATES[0]
    
    headers = {"Content-Type": "application/json"}
    probe_payload = {
        "contents": [{"parts": [{"text": "Hi"}]}],
        "generationConfig": {"maxOutputTokens": 5}
    }
    for model in MODEL_CANDIDATES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=json.dumps(probe_payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if "candidates" in res_data:
                    _active_model = model
                    print(f"[llm_client] Using Gemini model: {model}")
                    logging.info(f"Using Gemini model: {model}")
                    return model
        except Exception as e:
            code = e.code if hasattr(e, 'code') else None
            if code == 429:
                # Rate-limited but model exists; try with backoff later
                _active_model = model
                print(f"[llm_client] Model {model} rate-limited (429). Will use it with backoff.")
                return model
            print(f"[llm_client] Model {model} not available ({code}). Trying next...")
    
    # All failed, use first as default
    _active_model = MODEL_CANDIDATES[0]
    return _active_model

def query_gemini(prompt, system_instruction="You are a direct translator. Keep your output extremely brief and output the result immediately."):
    if not GEMINI_API_KEY:
        logging.error("GEMINI_API_KEY is not set in environment.")
        print("Error: GEMINI_API_KEY is missing.")
        return None

    active_model = _get_active_model()
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "systemInstruction": {
            "parts": [{
                "text": system_instruction
            }]
        },
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1000
        }
    }
    
    # Retry with backoff for 429 Rate Limit, also try fallback models on 404
    global _active_model
    models_to_try = [active_model] + [m for m in MODEL_CANDIDATES if m != active_model]
    
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    url, 
                    data=json.dumps(payload).encode("utf-8"), 
                    headers=headers, 
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    if "candidates" in res_data and res_data["candidates"]:
                        content = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        _active_model = model  # remember working model
                        return content
            except Exception as e:
                code = e.code if hasattr(e, 'code') else None
                if code == 429:
                    sleep_time = min(20, (5 * (attempt + 1)))
                    logging.warning(f"Rate limited (429) on {model}. Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                    continue
                elif code == 404:
                    logging.warning(f"Model {model} not available (404). Trying next model...")
                    break  # try next model
                else:
                    logging.error(f"Gemini API query failed on {model}: {e}")
                    print(f"Error querying Gemini ({model}): {e}")
                    break
    
    return None

def translate_text(text, target_lang_name):
    """
    Translates any input text into the target language.
    Returns None if translation fails.
    """
    if not text or not text.strip():
        return ""
    prompt = (
        f"Translate the following text into natural, fluent {target_lang_name}. "
        "Even if the original text is in English or Japanese, you MUST translate it entirely into the target language. "
        "Provide ONLY the translated text, without quotes, explanations, or introductory/concluding remarks.\n\n"
        f"Text to translate:\n{text}"
    )
    result = query_gemini(prompt, system_instruction=f"You are a native translator for {target_lang_name}. You always translate the input text into fluent {target_lang_name} without exception.")
    return result if result else None

def translate_title(japanese_title, target_lang_name):
    """
    Translates a YouTube title into a catchy, natural title in the target language.
    Returns None if translation fails.
    """
    prompt = (
        f"Translate the following YouTube video title into a natural, catchy title in {target_lang_name}. "
        "Even if the original title is already in English, you MUST translate it entirely into the target language. "
        "Keep any brackets like 【卓球】 or [AI Analysis] if present (but translated appropriately to the target language). "
        "Provide ONLY the translated title, with absolutely no quotes or extra text.\n\n"
        f"Title: {japanese_title}"
    )
    result = query_gemini(prompt, system_instruction=f"You are a native copywriter for {target_lang_name}. You always output the result in {target_lang_name} only.")
    return result if result else None

def generate_x_post(translated_title, video_url, target_lang_name, is_collab=False):
    """
    Generates a social post for X (Twitter) in the target language.
    Strictly keeps the total text under 230 characters (including URL) to avoid X limit issues.
    """
    collab_instruction = "Mention that this is a special AI dubbed video." if is_collab else ""
    
    prompt = (
        f"Write a very short promotional tweet for X (Twitter) about a table tennis video in {target_lang_name}.\n"
        f"Video title: \"{translated_title}\"\n"
        f"{collab_instruction}\n"
        "Requirements:\n"
        f"1. You MUST write ENTIRELY in {target_lang_name}.\n"
        "2. The text MUST be VERY SHORT (MAX 70 words or 90 characters).\n"
        "3. Include 2 relevant hashtags like #TableTennis #ToriShira.\n"
        "4. Output ONLY the tweet text, no quotation marks or commentary."
    )
    
    result = query_gemini(prompt, system_instruction=f"You are a Twitter marketer. You write extremely concise tweets strictly under character limits in {target_lang_name} only.")
    if result:
        # Strip external quotes
        if result.startswith('"') and result.endswith('"'):
            result = result[1:-1].strip()
            
        # Strict Japanese length limit: Total Japanese tweet text + URL must be under 120 chars
        if target_lang_name in ["Japanese", "日本語"]:
            if len(result) > 90:
                result = result[:85] + "..."
            post = f"{result}\n\n{video_url}"
        else:
            post = f"{result}\n\n{video_url}"
            if len(post) > 230:
                allowed_text_len = 230 - len(video_url) - 3
                result = result[:allowed_text_len].rsplit(' ', 1)[0] + "..."
                post = f"{result}\n\n{video_url}"
        return post
    
    # Fallback template (guaranteed short)
    if is_collab:
        return f"🏓 {translated_title}\n\n{video_url}"
    else:
        return f"🎬 【卓球】{translated_title}\n\n{video_url}"
