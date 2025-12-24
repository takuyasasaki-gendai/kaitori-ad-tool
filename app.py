import streamlit as st
import asyncio
import sys
import os # 追加
import pandas as pd
import io
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- 【重要】Streamlit Cloud上でのPlaywrightブラウザ自動インストール ---
@st.cache_resource # 1回だけ実行されるようにキャッシュ
def install_playwright():
    # クラウド環境（Linux）の場合のみ実行
    if sys.platform != "win32":
        os.system("playwright install chromium")

install_playwright()

# Windows + Python 3.14 用の互換性パッチ
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- セッション状態の初期化 ---
if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# サイトの読み込み・掃除関数
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        # 起動引数をクラウド用に調整
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header", "aside"]):
                s.decompose()
            text = " ".join(soup.get_text(separator=" ").split())
            return text[:4000]
        except Exception as e:
            await browser.close()
            return f"Error: {str(e)}"

# --- 以下、以前のコードと同じ（AI生成、UI、認証など） ---
def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available_models else "models/gemini-1.5-flash"
        model = genai.GenerativeModel(target_model)
        prompt = f"あなたは買取業界専門の広告コンサルタントです。以下のサイト情報を分析し、Google検索広告プラン案を①〜⑥の順で作成してください。最後に必ず [EXCEL_DATA] タグでCSVデータを付与してください。\n\n解析サイト：{site_text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI生成エラー: {str(e)}"

def create_excel(text):
    try:
        if "[EXCEL_DATA]" in text:
            raw_data = text.split("[EXCEL_DATA]")[1].split("[EXCEL_DATA]")[0].strip()
            df = pd.read_csv(io.StringIO(raw_data))
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df[df['Type'] == '見出し'].to_excel(writer, index=False, sheet_name='②広告文（見出し）')
                df[df['Type'] == '説明文'].to_excel(writer, index=False, sheet_name='③説明文')
                df[df['Type'] == 'キーワード'].to_excel(writer, index=False, sheet_name='④キーワード')
                df[df['Type'].isin(['スニペット', 'コールアウト'])].to_excel(writer, index=False, sheet_name='⑤⑥アセット')
            return output.getvalue()
        return None
    except:
        return None

st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide")
st.title("🚀 検索（リスティング）広告案 自動生成ツール")

st.sidebar.title("認証")
input_password = st.sidebar.text_input("アクセスパスワードを入力してください", type="password")

if input_password != "password":
    if input_password == "":
        st.info("サイドバーにパスワードを入力してログインしてください。")
    else:
        st.error("パスワードが正しくありません。")
    st.stop()

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("SecretsにGEMINI_API_KEYが設定されていません。")
    st.stop()

target_url = st.text_input("解析したい買取LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if not target_url:
        st.warning("URLを入力してください。")
    else:
        with st.spinner("AIが戦略を生成中...（初回はブラウザ起動に時間がかかる場合があります）"):
            try:
                # クラウド環境ではasyncio.runで直接実行
                cleaned_text = asyncio.run(fetch_and_clean_content(target_url))
                if "Error" in cleaned_text:
                    st.error(f"サイト読み込みエラー: {cleaned_text}")
                else:
                    st.session_state.ad_result = generate_ad_plan(cleaned_text, api_key)
                    st.balloons()
            except Exception as e:
                st.error(f"エラー: {e}")

if st.session_state.ad_result:
    excel_file = create_excel(st.session_state.ad_result)
    if excel_file:
        st.download_button(label="📊 Excel形式でダウンロード", data=excel_file, file_name="ad_strategy.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.markdown("---")
    st.markdown(st.session_state.ad_result.split("[EXCEL_DATA]")[0])
