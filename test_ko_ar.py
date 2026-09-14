import sys
import llm_client

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def test_korean_and_arabic():
    title = "【卓球】スピンピップスD1と「同じ」回転系横目・表ソフトラバーを探す（AI分析）"
    url = "https://www.youtube.com/watch?v=vcRdgyPo7IM"
    desc = "回転系表ソフトの金字塔「スピンピップスD1」と全く同じ、または極めて近い特性を持つラバーをAIが徹底探索！"
    
    print("=== Testing Korean & Arabic Post Generation ===\n")
    
    for lang in ["韓国語", "アラビア語"]:
        print(f"--- Testing {lang} ---")
        trans_title = llm_client.translate_title(title, lang)
        print(f"Title: {trans_title}")
        
        post = llm_client.generate_x_post(trans_title, url, lang, video_description=desc, is_collab=True)
        print(f"X Post:\n{post}\n")

if __name__ == "__main__":
    test_korean_and_arabic()
