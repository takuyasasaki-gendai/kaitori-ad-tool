import streamlit as st
import asyncio
import sys
import os
import pandas as pd
import io
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- Playwright自動インストール (Streamlit Cloud用) ---
@st.cache_resource
def install_playwright():
    if sys.platform != "win32":
        os.system("playwright install chromium")

install_playwright()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- セッション状態の初期化 (結果を保持するため) ---
if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# サイトの読み込み・掃除
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"]
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

# AI生成関数 (順序とデータ出力を厳格化)
def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available_models else "models/gemini-1.5-flash"
        model = genai.GenerativeModel(target_model)
        
        prompt = f"""
        あなたは買取業界専門の広告コンサルタントです。以下のサイト情報を分析し、Google検索広告プランを作成してください。
        
        【解析サイトテキスト】: {site_text}

        【回答の構成ルール】
        必ず以下の①〜⑥の順番で、見出しを正確に書いて出力してください。
        ①サイト解析結果：強みと課題、改善案を詳細に記載。
        ②広告文（DL）：見出し15個（30文字以内）を作成。
        ③説明文（DL）：説明文4個（90文字以内）を作成。
        ④キーワード（DL）：20個以上（キーワード, マッチタイプ, 推定CPC, 優先度）を表形式で。
        ⑤構造化スニペット：2種類以上の「種類」と「値」。
        ⑥コールアウトアセット：8個以上のベネフィット。

        ---
        【重要：データ書き出し】
        回答の最後に、必ず [DATA_START] と [DATA_END] というタグで囲んで、以下の形式のCSVデータのみを省略せずに出力してください。
        Type,Content,Details,Other1,Other2
        見出し,見出しテキスト,文字数,,
        説明文,説明文テキスト,文字数,,
        キーワード,キーワード名,マッチタイプ,推定CPC,優先度
        スニペット,種類,値,,
        コールアウト,アセット内容,,,
        [DATA_START]
        Type,Content,Details,Other1,Other2
        見出し,テキスト1...
        ...
        [DATA_END]
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI生成エラー: {str(e)}"

# Excel作成
def create_excel(text):
    try:
        if "[DATA_START]" in text:
            raw_data = text.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
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

# --- UI ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide")
st.title("🚀 検索（リスティング）広告案 自動生成ツール")

# パスワード認証
st.sidebar.title("認証")
input_password = st.sidebar.text_input("アクセスパスワードを入力してください", type="password")

if input_password != "password":
    if input_password == "":
        st.info("サイドバーにパスワードを入力してください。")
    else:
        st.error("パスワードが正しくありません。")
    st.stop()

# APIキー取得
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("管理者エラー: SecretsにGEMINI_API_KEYが設定されていません。")
    st.stop()

# URL入力
target_url = st.text_input("解析したい買取LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if not target_url:
        st.warning("URLを入力してください。")
    else:
        with st.spinner("AIコンサルタントが全項目を生成中..."):
            try:
                # Playwright実行
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                cleaned_text = loop.run_until_complete(fetch_and_clean_content(target_url))
                
                if "Error" in cleaned_text:
                    st.error(f"サイト読み込み失敗: {cleaned_text}")
                else:
                    # 結果をセッションに保存
                    st.session_state.ad_result = generate_ad_plan(cleaned_text, api_key)
                    st.balloons()
            except Exception as e:
                st.error(f"エラー: {e}")

# --- 結果表示とダウンロード ---
if st.session_state.ad_result:
    excel_file = create_excel(st.session_state.ad_result)
    
    if excel_file:
        st.success("分析が完了しました！")
        st.download_button(
            label="📊 Excel形式でダウンロード（②③④）",
            data=excel_file,
            file_name="search_ad_plan.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_button"
        )
    else:
        st.warning("Excel用データの生成に失敗しました。もう一度実行してください。")

    st.markdown("---")
    # CSVタグ部分を隠して表示
    display_content = st.session_state.ad_result.split("[DATA_START]")[0]
    st.markdown(display_content)
