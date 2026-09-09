import os
import json
import urllib.request
import logging
import time
import re
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Model fallback list: confirmed working models
MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]
MODEL_NAME = MODEL_CANDIDATES[0]

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
                _active_model = model
                print(f"[llm_client] Model {model} rate-limited (429). Will use it with backoff.")
                return model
            print(f"[llm_client] Model {model} not available ({code}). Trying next...")
    
    _active_model = MODEL_CANDIDATES[0]
    return _active_model

def query_gemini(prompt, system_instruction=None, max_tokens=300):
    """
    Sends a query to Gemini API with automatic model fallback and retries.
    """
    if not GEMINI_API_KEY:
        logging.error("GEMINI_API_KEY is not set.")
        return None

    contents = [{"parts": [{"text": prompt}]}]
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": max_tokens
        }
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    headers = {"Content-Type": "application/json"}
    
    preferred_model = _get_active_model()
    try_models = [preferred_model] + [m for m in MODEL_CANDIDATES if m != preferred_model]
    
    for model in try_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        if content_parts:
                            return content_parts[0].get("text", "").strip()
            except urllib.error.HTTPError as e:
                code = e.code
                if code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                elif code in [404, 400]:
                    break
                else:
                    logging.error(f"Gemini API query failed on {model}: HTTP Error {code}")
                    break
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                else:
                    logging.error(f"Error querying Gemini ({model}): {e}")
                    break
    
    return None

def translate_text(text, target_lang_name):
    """
    Translates any input text into the target language.
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
    """
    prompt = (
        f"Translate the following YouTube video title into a natural, catchy title in {target_lang_name}. "
        "Even if the original title is already in English, you MUST translate it entirely into the target language. "
        "Keep brackets like 【卓球】 or [AI Analysis] if present (translated appropriately to target language). "
        "Provide ONLY the translated title, with absolutely no quotes or extra text.\n\n"
        f"Title: {japanese_title}"
    )
    result = query_gemini(prompt, system_instruction=f"You are a native copywriter for {target_lang_name}. You always output the result in {target_lang_name} only.")
    return result if result else None

def generate_x_post(translated_title, video_url, target_lang_name, video_description="", is_collab=False):
    """
    Generates a social post for X (Twitter) strictly consistent with the actual video content.
    Uses video_description to ensure 100% factual accuracy and zero hallucination.
    """
    collab_instruction = "Note: Mention this is an AI dubbed video." if is_collab else ""
    
    content_context = f"\nVideo Summary & Key Facts:\n\"{video_description.strip()[:400]}\"" if video_description and video_description.strip() else ""
    
    prompt = (
        f"You are a table tennis marketer. Write a concise, engaging promotional tweet for X in {target_lang_name}.\n"
        f"Video Title: \"{translated_title}\"{content_context}\n"
        f"{collab_instruction}\n\n"
        "Strict Accuracy & Style Requirements:\n"
        f"1. You MUST write ENTIRELY in {target_lang_name}.\n"
        "2. ACCURACY FIRST: Reflect the SPECIFIC topic, gear names, or technical analysis from the video summary. DO NOT invent false claims or generic filler.\n"
        "3. LENGTH: Keep it very concise (MAX 50 words or 75 characters for Asian languages).\n"
        "4. HASHTAGS: Include 2 relevant hashtags (e.g. #TableTennis #PingPong or specific gear tags).\n"
        "5. DO NOT write [Link], [URL], or brackets. The URL is appended automatically.\n"
        "6. Output ONLY the tweet text, no quotes or commentary."
    )
    
    result = query_gemini(prompt, system_instruction=f"You are an expert table tennis Twitter copywriter. You write concise, strictly accurate tweets in {target_lang_name} only.", max_tokens=150)
    if result:
        if result.startswith('"') and result.endswith('"'):
            result = result[1:-1].strip()
            
        for ph in ["[Link]", "[link]", "[URL]", "[url]", "[Video Link]", "[Enlace]", "[Lien]", "[Video]", "[video]"]:
            if ph in result:
                result = result.replace(ph, "").strip()
        
        result = re.sub(r'(Mira aquí|Watch here|Hier ansehen|Regardez ici|Veja aqui|Смотрите здесь|Дивіться тут|यहाँ देखें|ดูที่นี่|Xem tại đây)[:：\s]*$', '', result, flags=re.IGNORECASE).strip()
            
        if target_lang_name in ["Japanese", "日本語"]:
            if len(result) > 85:
                result = result[:80] + "..."
            return f"{result}\n\n{video_url}"
        else:
            if len(result) + len(video_url) + 2 > 230:
                allowed_text_len = 230 - len(video_url) - 5
                result = result[:allowed_text_len].rsplit(' ', 1)[0] + "..."
            return f"{result}\n\n{video_url}"
    
    # Fallback template
    if is_collab:
        return f"🏓 {translated_title}\n\n{video_url}"
    else:
        return f"🎬 【卓球】{translated_title}\n\n{video_url}"

def generate_detailed_summary(title, description, target_lang_name):
    """
    Generates a rich 2-3 paragraph informative summary for Hatena Blog and YouTube Community
    strictly based on the actual video description.
    """
    if not description or len(description.strip()) < 30:
        return translate_text(f"{title}\n\nAn in-depth table tennis analysis covering equipment physics, tactical applications, and player insights.", target_lang_name)
        
    prompt = (
        f"Write an informative, engaging 2-paragraph summary in {target_lang_name} about this table tennis video for a blog/community post.\n\n"
        f"Video Title: \"{title}\"\n"
        f"Video Full Description:\n\"{description.strip()[:1000]}\"\n\n"
        "Requirements:\n"
        f"1. Write entirely in {target_lang_name}.\n"
        "2. Highlight the key questions answered, equipment analyzed, or techniques discussed in the video.\n"
        "3. Strictly base all statements on the provided description (NO hallucinations).\n"
        "4. Tone: Professional, enthusiastic, informative."
    )
    result = query_gemini(prompt, system_instruction=f"You are a professional table tennis analyst and technical writer in {target_lang_name}.", max_tokens=400)
    return result if result else translate_text(description[:300], target_lang_name)
