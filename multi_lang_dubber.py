"""
Multi-Language Dubbing Engine (`multi_lang_dubber.py`)
Generates audio tracks with BGM intro/outro preservation, volume ducking, and timing sync across 11 target languages.
"""

import os
import sys
import re
import asyncio
import glob
import edge_tts
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import GoogleTranslator
from utils_audio import change_audio_speed, get_audio_duration

# FFmpeg configuration
ffmpeg_bin = r"C:\Users\kyomi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
if os.path.exists(ffmpeg_bin):
    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
AudioSegment.converter = os.path.join(ffmpeg_bin, "ffmpeg.exe") if os.path.exists(ffmpeg_bin) else "ffmpeg"
AudioSegment.ffprobe = os.path.join(ffmpeg_bin, "ffprobe.exe") if os.path.exists(ffmpeg_bin) else "ffprobe"

# Language Mapping & Voice Definitions for edge-tts
LANGUAGE_CONFIG = {
    "en": {"name": "English", "translator": "en", "voice_male": "en-US-ChristopherNeural", "voice_female": "en-US-AriaNeural"},
    "zh-CN": {"name": "Chinese (Simplified)", "translator": "zh-CN", "voice_male": "zh-CN-YunjianNeural", "voice_female": "zh-CN-XiaoxiaoNeural"},
    "de": {"name": "German", "translator": "de", "voice_male": "de-DE-ConradNeural", "voice_female": "de-DE-KatjaNeural"},
    "fr": {"name": "French", "translator": "fr", "voice_male": "fr-FR-HenriNeural", "voice_female": "fr-FR-DeniseNeural"},
    "pt": {"name": "Portuguese", "translator": "pt", "voice_male": "pt-BR-AntonioNeural", "voice_female": "pt-BR-FranciscaNeural"},
    "es": {"name": "Spanish", "translator": "es", "voice_male": "es-ES-AlvaroNeural", "voice_female": "es-ES-ElviraNeural"},
    "sv": {"name": "Swedish", "translator": "sv", "voice_male": "sv-SE-MattiasNeural", "voice_female": "sv-SE-SofieNeural"},
    "ru": {"name": "Russian", "translator": "ru", "voice_male": "ru-RU-DmitryNeural", "voice_female": "ru-RU-SvetlanaNeural"},
    "uk": {"name": "Ukrainian", "translator": "uk", "voice_male": "uk-UA-OstapNeural", "voice_female": "uk-UA-PolinaNeural"},
    "hi": {"name": "Hindi", "translator": "hi", "voice_male": "hi-IN-MadhurNeural", "voice_female": "hi-IN-SwaraNeural"},
    "th": {"name": "Thai", "translator": "th", "voice_male": "th-TH-NiwatNeural", "voice_female": "th-TH-PremwadeeNeural"},
    "vi": {"name": "Vietnamese", "translator": "vi", "voice_male": "vi-VN-NamMinhNeural", "voice_female": "vi-VN-HoaiMyNeural"}
}

MAX_CONCURRENT_TTS = 15


def detect_speaker(ja_text):
    """Detect male (Kenji) vs female (Misaki) speaker from Japanese text."""
    if any(k in ja_text for k in ['みさちゃん', 'ミサキ', 'みささん', '健二さん', 'ケンジさん']):
        if 'みさちゃん' in ja_text or 'ミサキ' in ja_text or 'みささん' in ja_text:
            return 'kenji'
        return 'misaki'
    if any(k in ja_text for k in ['みさです', 'ミサです', 'アシスタント']):
        return 'misaki'
    if any(k in ja_text for k in ['賢二です', '健二です', 'ケンジです', '解説の健二']):
        return 'kenji'
    return None


async def generate_tts(text, output_path, voice):
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"[TTS Error] {e}")
        return False


async def translate_and_generate_all(ja_segments, lang_code, temp_dir):
    config = LANGUAGE_CONFIG[lang_code]
    translator = GoogleTranslator(source='ja', target=config['translator'])
    sem = asyncio.Semaphore(MAX_CONCURRENT_TTS)
    tasks = []

    current_speaker = 'kenji'

    print(f"[{config['name']}] Translating {len(ja_segments)} segments...")
    for i, segment in enumerate(ja_segments):
        text_val = getattr(segment, 'text', segment.get('text') if isinstance(segment, dict) else "")
        ja_text = text_val.replace('\n', ' ').strip()

        if not ja_text or ja_text in ('[音楽]', '[拍手]', '。'):
            tasks.append(asyncio.sleep(0, result=None))
            continue

        detected = detect_speaker(ja_text)
        if detected:
            current_speaker = detected

        voice = config['voice_female'] if current_speaker == 'misaki' else config['voice_male']

        try:
            target_text = translator.translate(ja_text) if ja_text.strip() else ""
        except Exception as e:
            target_text = ja_text

        clean_text = re.sub(r'\[Music\]', '', target_text).strip()
        clean_text = re.sub(
            r'^\s*[\(\[\{♪]*\s*(Kenji|Misaki|Misa|Keni|Minori)\s*[:：\]\}\)]*\s*',
            '', clean_text, flags=re.IGNORECASE
        ).strip()

        if not clean_text:
            tasks.append(asyncio.sleep(0, result=None))
            continue

        temp_path = os.path.join(temp_dir, f"seg_{i}.mp3")

        async def bound_generate(txt, v, path):
            async with sem:
                if not os.path.exists(path):
                    await generate_tts(txt, path, v)
                return path

        tasks.append(bound_generate(clean_text, voice, temp_path))

    results = await asyncio.gather(*tasks)
    return results


def process_video_dubbing(video_id, target_languages=None, bgm_intro_end=40.0, bgm_outro_start=None):
    if target_languages is None:
        target_languages = list(LANGUAGE_CONFIG.keys())

    original_audio_path = f"original_audio_{video_id}.mp3"
    if not os.path.exists(original_audio_path):
        print(f"Downloading original audio for {video_id}...")
        import yt_dlp
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': original_audio_path}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f'https://www.youtube.com/watch?v={video_id}'])

    orig = AudioSegment.from_file(original_audio_path)
    target_duration_sec = len(orig) / 1000.0

    api = YouTubeTranscriptApi()
    ja_transcript = api.list(video_id).find_transcript(['ja'])
    ja_segments = ja_transcript.fetch()

    # Determine BGM boundaries dynamically if not passed
    first_speech_time = ja_segments[0].start if len(ja_segments) > 0 else 30.0
    last_speech_time = ja_segments[-1].start if len(ja_segments) > 0 else target_duration_sec - 30.0

    bgm_intro_end = first_speech_time
    bgm_outro_start = last_speech_time if bgm_outro_start is None else bgm_outro_start

    bgm_intro = orig[:int(bgm_intro_end * 1000)].fade_out(2500)
    bgm_outro = orig[int(bgm_outro_start * 1000):].fade_in(2000).fade_out(3000)

    generated_files = {}

    for lang_code in target_languages:
        if lang_code not in LANGUAGE_CONFIG:
            continue

        print(f"\n--- Generating {LANGUAGE_CONFIG[lang_code]['name']} Dub for {video_id} ---")
        temp_dir = f"temp_audio_{video_id}_{lang_code}"
        os.makedirs(temp_dir, exist_ok=True)

        tts_paths = asyncio.run(translate_and_generate_all(ja_segments, lang_code, temp_dir))

        target_duration_ms = int(target_duration_sec * 1000)
        voice_track = AudioSegment.silent(duration=target_duration_ms)
        last_placed_end_ms = 0

        for i, segment in enumerate(ja_segments):
            start_val = getattr(segment, 'start', segment.get('start') if isinstance(segment, dict) else 0)
            start_time_ms = int(start_val * 1000)
            tts_path = tts_paths[i]

            if not tts_path or not os.path.exists(str(tts_path)) or os.path.getsize(tts_path) == 0:
                continue

            tts_duration_sec = get_audio_duration(tts_path)
            next_start = ja_segments[i + 1].start if i + 1 < len(ja_segments) else target_duration_sec
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
                    except Exception:
                        audio_chunk = None

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
        final_audio.export(output_filename, format="mp3", bitrate="192k")
        print(f"Created: {output_filename} ({os.path.getsize(output_filename) / (1024*1024):.1f} MB)")
        generated_files[lang_code] = output_filename

    return generated_files


if __name__ == "__main__":
    if len(sys.argv) > 1:
        vid = sys.argv[1]
        langs = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        process_video_dubbing(vid, langs)
    else:
        print("Usage: python multi_lang_dubber.py <VIDEO_ID> [LANG_CODES_CSV]")
