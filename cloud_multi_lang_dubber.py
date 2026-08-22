"""
Cloud Multi-Language Dubbing Engine (`cloud_multi_lang_dubber.py`)
Generates audio tracks with BGM intro/outro preservation, volume ducking, and timing sync across 12 target languages.
"""

import os
import sys
import re
import asyncio
import glob
import edge_tts
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
from utils_audio import change_audio_speed, get_audio_duration

# Language Mapping & Voice Definitions for edge-tts (12 Target Languages)
LANGUAGE_CONFIG = {
    "zh-CN": {"name": "Chinese (Simplified)", "candidates": ["zh-Hans", "zh-CN", "zh-SG", "zh"], "voice_male": "zh-CN-YunxiNeural", "voice_female": "zh-CN-XiaoxiaoNeural"},
    "de": {"name": "German", "candidates": ["de", "de-DE"], "voice_male": "de-DE-ConradNeural", "voice_female": "de-DE-KatjaNeural"},
    "fr": {"name": "French", "candidates": ["fr", "fr-FR"], "voice_male": "fr-FR-HenriNeural", "voice_female": "fr-FR-DeniseNeural"},
    "pt": {"name": "Portuguese", "candidates": ["pt", "pt-BR", "pt-PT"], "voice_male": "pt-BR-AntonioNeural", "voice_female": "pt-BR-FranciscaNeural"},
    "es": {"name": "Spanish", "candidates": ["es", "es-ES", "es-419"], "voice_male": "es-ES-AlvaroNeural", "voice_female": "es-ES-ElviraNeural"},
    "sv": {"name": "Swedish", "candidates": ["sv", "sv-SE"], "voice_male": "sv-SE-MattiasNeural", "voice_female": "sv-SE-SofieNeural"},
    "ru": {"name": "Russian", "candidates": ["ru", "ru-RU"], "voice_male": "ru-RU-DmitryNeural", "voice_female": "ru-RU-SvetlanaNeural"},
    "uk": {"name": "Ukrainian", "candidates": ["uk", "uk-UA"], "voice_male": "uk-UA-OstapNeural", "voice_female": "uk-UA-PolinaNeural"},
    "hi": {"name": "Hindi", "candidates": ["hi", "hi-IN"], "voice_male": "hi-IN-MadhurNeural", "voice_female": "hi-IN-SwaraNeural"},
    "th": {"name": "Thai", "candidates": ["th", "th-TH"], "voice_male": "th-TH-NiwatNeural", "voice_female": "th-TH-PremwadeeNeural"},
    "vi": {"name": "Vietnamese", "candidates": ["vi", "vi-VN"], "voice_male": "vi-VN-NamMinhNeural", "voice_female": "vi-VN-HoaiMyNeural"},
    "ko": {"name": "Korean", "candidates": ["ko", "ko-KR"], "voice_male": "ko-KR-InJoonNeural", "voice_female": "ko-KR-SunHiNeural"}
}

MAX_CONCURRENT_TTS = 20

def detect_speaker(text, ja_text=""):
    lower = text.lower().strip()
    misaki_patterns = [
        r'^misaki', r'^misa[^a-z]', r'^misa$', r'^this is misaki',
        r'^assistant', r'^yes,', r'^that\'s right', r'^wow', r'^amazing',
        r'^i see', r'^that\'s incredible', r'^thank you', r'^hello everyone'
    ]
    kenji_patterns = [
        r'^kenji', r'^i\'m kenji', r'^welcome', r'^in short', r'^let\'s',
        r'^executive summary', r'^first is', r'^second is', r'^third is',
        r'^fourth is', r'^now,', r'^regarding', r'^from the perspective'
    ]
    for pat in misaki_patterns:
        if re.search(pat, lower): return 'misaki'
    for pat in kenji_patterns:
        if re.search(pat, lower): return 'kenji'

    if ja_text:
        if any(k in ja_text for k in ['みさき', 'ミサキ', 'みささん', '美咲', 'みさん', 'MCのみさき', 'ナビゲーターのみさ']):
            if 'MCのみさき' in ja_text or 'みさきです' in ja_text or 'ナビゲーター' in ja_text:
                return 'misaki'
            return 'kenji'
        if any(k in ja_text for k in ['健二さん', 'ケンジさん', 'けんじさん']):
            return 'misaki'
        if any(k in ja_text for k in ['賢二です', '健二です', 'ケンジです', 'けんじがお届け', '解説の健二']):
            return 'kenji'
    return None

async def generate_tts(text, output_path, voice):
    for _ in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            return True
        except:
            await asyncio.sleep(1)
    return False

async def generate_all_tts_for_lang(segments, ja_segments, temp_dir, voice_male, voice_female):
    sem = asyncio.Semaphore(MAX_CONCURRENT_TTS)
    tasks = []
    
    ja_text_by_time = {}
    for seg in ja_segments:
        start_val = getattr(seg, 'start', seg.get('start') if isinstance(seg, dict) else 0)
        text_val = getattr(seg, 'text', seg.get('text') if isinstance(seg, dict) else "")
        ja_text_by_time[round(start_val, 1)] = text_val.replace('\n', ' ').strip()

    current_speaker = 'misaki'

    for i, segment in enumerate(segments):
        start_val = getattr(segment, 'start', segment.get('start') if isinstance(segment, dict) else 0)
        text_val = getattr(segment, 'text', segment.get('text') if isinstance(segment, dict) else "")

        text = text_val.replace('\n', ' ').strip()
        if not text or text in ('[Music]', '[Applause]', '.', 'ສ', 'Eh'):
            tasks.append(asyncio.sleep(0, result=None))
            continue

        ja_text = ja_text_by_time.get(round(start_val, 1), "")
        detected = detect_speaker(text, ja_text)
        if detected:
            current_speaker = detected

        current_voice = voice_female if current_speaker == 'misaki' else voice_male

        clean_text = re.sub(r'\[Music\]', '', text).strip()
        clean_text = re.sub(
            r'^\s*[\(\[\{♪]*\s*(Kenji|Misaki|Misa|Keni|Minori)\s*[:：\]\}\)]*\s*',
            '', clean_text, flags=re.IGNORECASE
        ).strip()

        if not clean_text or clean_text in ('ສ', 'Eh'):
            tasks.append(asyncio.sleep(0, result=None))
            continue

        temp_path = os.path.join(temp_dir, f"seg_{i}.mp3")

        async def bound_generate(txt, v, path):
            async with sem:
                if not os.path.exists(path):
                    await generate_tts(txt, path, v)
                return path

        tasks.append(bound_generate(clean_text, current_voice, temp_path))

    results = await asyncio.gather(*tasks)
    return results

def process_video_dubbing(video_id, target_languages=None):
    if target_languages is None:
        target_languages = list(LANGUAGE_CONFIG.keys())

    original_audio_path = f"original_audio_{video_id}.mp3"
    if not os.path.exists(original_audio_path):
        print(f"Downloading original audio for {video_id} via Android client...")
        ydl_opts = {
            'format': '18/bestaudio/best',
            'outtmpl': original_audio_path,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['android']}}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f'https://www.youtube.com/watch?v={video_id}'])

    orig = AudioSegment.from_file(original_audio_path)
    target_duration_sec = len(orig) / 1000.0

    api = YouTubeTranscriptApi()
    t_list = api.list(video_id)
    ja_transcript = t_list.find_transcript(['ja'])
    ja_segments = ja_transcript.fetch()

    # BGM Intro and Outro
    first_speech_time = ja_segments[0].start if len(ja_segments) > 0 else 30.0
    last_speech_time = ja_segments[-1].start if len(ja_segments) > 0 else target_duration_sec - 30.0

    bgm_intro_end = first_speech_time
    bgm_outro_start = last_speech_time

    bgm_intro = orig[:int(bgm_intro_end * 1000)].fade_out(2500)
    bgm_outro = orig[int(bgm_outro_start * 1000):].fade_in(2000).fade_out(3000)

    generated_files = {}

    for lang_code in target_languages:
        if lang_code not in LANGUAGE_CONFIG:
            continue

        conf = LANGUAGE_CONFIG[lang_code]
        print(f"\n--- Generating {conf['name']} Dub for {video_id} ---")
        
        # Get transcript for language (or translate from ja)
        segments = None
        try:
            t = t_list.find_transcript(conf['candidates'])
            segments = t.fetch()
        except:
            segments = ja_transcript.translate(conf['candidates'][0]).fetch()

        temp_dir = f"temp_audio_{video_id}_{lang_code}"
        os.makedirs(temp_dir, exist_ok=True)

        tts_paths = asyncio.run(generate_all_tts_for_lang(segments, ja_segments, temp_dir, conf['voice_male'], conf['voice_female']))

        target_duration_ms = int(target_duration_sec * 1000)
        voice_track = AudioSegment.silent(duration=target_duration_ms)
        last_placed_end_ms = 0

        for i, segment in enumerate(segments):
            start_val = getattr(segment, 'start', segment.get('start') if isinstance(segment, dict) else 0)
            start_time_ms = int(start_val * 1000)
            tts_path = tts_paths[i]

            if not tts_path or not os.path.exists(str(tts_path)) or os.path.getsize(tts_path) == 0:
                continue

            tts_duration_sec = get_audio_duration(tts_path)
            next_start = getattr(segments[i + 1], 'start', segments[i+1].get('start') if isinstance(segments[i+1], dict) else start_val) if i + 1 < len(segments) else target_duration_sec
            available_time = next_start - start_val
            max_allowed_time = available_time * 0.95

            audio_chunk = None
            if max_allowed_time > 0.3:
                speed_ratio = tts_duration_sec / max_allowed_time
                speed_ratio = max(0.9, min(1.35, speed_ratio))

                temp_speed_path = os.path.join(temp_dir, f"seg_{i}_speed.mp3")
                success = change_audio_speed(tts_path, temp_speed_path, speed_ratio)
                if success and os.path.exists(temp_speed_path) and os.path.getsize(temp_speed_path) > 0:
                    try:
                        audio_chunk = AudioSegment.from_file(temp_speed_path)
                    except:
                        pass
                    try:
                        os.remove(temp_speed_path)
                    except:
                        pass

            if audio_chunk is None:
                audio_chunk = AudioSegment.from_file(tts_path)

            if start_time_ms < last_placed_end_ms:
                start_time_ms = last_placed_end_ms

            if start_time_ms < target_duration_ms:
                voice_track = voice_track.overlay(audio_chunk, position=start_time_ms)
                last_placed_end_ms = start_time_ms + len(audio_chunk)

            try:
                os.remove(tts_path)
            except:
                pass

        bgm_track = AudioSegment.silent(duration=target_duration_ms)
        bgm_track = bgm_track.overlay(bgm_intro, position=0)
        bgm_track = bgm_track.overlay(bgm_outro, position=int(bgm_outro_start * 1000))

        final_audio = bgm_track.overlay(voice_track)
        if len(final_audio) > target_duration_ms:
            final_audio = final_audio[:target_duration_ms]

        output_filename = f"{video_id}_{lang_code}_dub.mp3"
        final_audio.export(output_filename, format="mp3", bitrate="128k")
        print(f"Created: {output_filename} ({os.path.getsize(output_filename) / (1024*1024):.1f} MB)")
        generated_files[lang_code] = output_filename

    return generated_files
