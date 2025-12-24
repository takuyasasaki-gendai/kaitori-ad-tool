import streamlit as st
import asyncio
import sys
import os
import pandas as pd
import io
import re  # 文字置換用に追加
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- 1. 初期設定 ---
@st.cache_resource
def install_playwright():
    if sys.platform != "win32":
        os.system("playwright install chromium")

install_playwright()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# --- 2. CSSによるデザイン調整 ---
st.markdown("""
    <style>
    /* メインタイトル背景（黄色） */
    .plan-title {
        background-color: #ffff00;
        font-weight: bold;
        padding: 5px 10px;
        font-size: 1.5em;
        display: inline-block;
        border-radius: 3px;
        margin-bottom: 20px;
    }
    /* ①〜⑥の見出し（赤字・太字） */
    .red-heading {
        color: #ff0000;
        font-weight: bold;
        font-size: 1.2em;
        margin-top: 25px;
        margin-bottom: 10px;
        display: block;
    }
    /* 強み・課題・改善案（下線） */
    .underlined-keyword {
        text-decoration: underline;
        font-weight: bold;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3.5em;
        background-color: #007bff;
        color: white;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover {
        background-color: #0056b3;
    }
    .report-container {
        background-color: white;
        padding: 30px;
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. テキスト装飾用関数 ---
def apply_custom_styles(text):
    # ①〜⑥を赤文字に
    for i in ["①", "②", "③", "④", "⑤", "⑥"]:
        text = text.replace(i, f"<span class='red-heading'>{i}")
    
    # 閉じタグの調整（簡易的ですが見出しの終わりを検知）
    text = text.replace("】", "】</span>")
    
    # 「強み」「課題」「改善案」に下線
    keywords = ["強み", "課題", "改善案"]
    for kw in keywords:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    
    # タイトル行（Google検索広告プラン：）を黄色背景に
    text = re.sub(r'(Google検索広告プラン：[^\n]+)', r'<span class="plan-title">\1</span>', text)
    
    return text

# --- 4. スクレイピング & AIロジック ---
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--single-process"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header"]): s.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:4000]
        except Exception as e:
            await browser.close()
            return f"Error: {str(e)}"

def generate_ad_plan(site_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash') # 安定性重視
    prompt = f"""
    あなたは買取専門のプロ広告運用者です。
    以下の情報を元に、Google検索広告案を作成してください。
    
    【出力形式ルール】:
    1. 冒頭に必ず「Google検索広告プラン：(サイト名)」と記載。
    2. 見出しは必ず ①サイト解析結果 ②広告文（DL） ③説明文（DL） ④キーワード（DL） ⑤構造化スニペット ⑥コールアウトアセット の順で。
    3. ①の中には必ず「強み」「課題」「改善案」の単語を含めて詳細に解説。
    4. 最後に [DATA_START]CSVデータ[DATA_END] を付与。
    
    解析対象: {site_text}
    """
    response = model.generate_content(prompt)
    return response.text

def create_excel(text):
    try:
        raw = text.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
        df = pd.read_csv(io.StringIO(raw))
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df[df['Type'] == '見出し'].to_excel(writer, index=False, sheet_name='②広告文（見出し）')
            df[df['Type'] == '説明文'].to_excel(writer, index=False, sheet_name='③説明文')
            df[df['Type'] == 'キーワード'].to_excel(writer, index=False, sheet_name='④キーワード')
            df[df['Type'].isin(['スニペット', 'コールアウト'])].to_excel(writer, index=False, sheet_name='アセット')
        return out.getvalue()
    except: return None

# --- 5. UIレイアウト ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.title("🛡️ 認証")
    input_password = st.text_input("パスワード", type="password")
    st.divider()
    st.markdown("### 運用ルール\n- 生成結果はExcelで保存可能\n- 1週間アクセスがないと休止します")

if input_password != "password":
    st.info("パスワードを入力して開始してください。")
    st.stop()

api_key = st.secrets.get("GEMINI_API_KEY")

st.title("🚀 検索（リスティング）広告案 自動生成ツール")

url_col, btn_col = st.columns([4, 1])
with url_col:
    target_url = st.text_input("URL入力", placeholder="https://********.com", label_visibility="collapsed")
with btn_col:
    if st.button("分析＆生成スタート"):
        if target_url:
            with st.spinner("AIが広告戦略を構築中..."):
                cleaned = asyncio.run(fetch_and_clean_content(target_url))
                st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
                st.balloons()

if st.session_state.ad_result:
    excel = create_excel(st.session_state.ad_result)
    if excel:
        st.download_button("📊 Excel形式でダウンロード", data=excel, file_name="ad_strategy.xlsx", key="dl")
    
    st.markdown("---")
    
    # 装飾を適用して表示
    display_text = st.session_state.ad_result.split("[DATA_START]")[0]
    styled_html = apply_custom_styles(display_text)
    
    st.markdown(f'<div class="report-container">{styled_html}</div>', unsafe_allow_html=True)
