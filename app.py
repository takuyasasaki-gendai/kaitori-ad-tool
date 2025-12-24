import streamlit as st
import asyncio
import sys
import pandas as pd
import io
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- セッション状態の初期化 ---
if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# サイトの読み込み・掃除関数
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
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

# AI生成関数
def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available_models else "models/gemini-1.5-flash"
        model = genai.GenerativeModel(target_model)
        
        prompt = f"あなたは買取業界専門の広告コンサルタントです。以下のサイト情報を分析し、Google検索広告プラン案を①サイト解析結果 ②広告文15個 ③説明文4個 ④キーワード20個 ⑤構造化スニペット ⑥コールアウトアセット の順で作成してください。最後に必ず [EXCEL_DATA] タグでCSVデータを付与してください。\n\n解析サイト：{site_text}"
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

# --- UI設定 ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide")
st.title("🚀 検索（リスティング）広告案 自動生成ツール")

# APIキーの取得（設定から読み込むか、画面で入力させる）
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Keyを入力してください", type="password")

target_url = st.text_input("解析したい買取LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if not api_key:
        st.error("APIキーが設定されていません。サイドバーから入力するか、Secretsに設定してください。")
    elif not target_url:
        st.warning("URLを入力してください。")
    else:
        with st.spinner("AIが戦略を生成中..."):
            try:
                # Playwrightの実行
                cleaned_text = asyncio.run(fetch_and_clean_content(target_url))
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