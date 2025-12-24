import streamlit as st
import asyncio
import sys
import os
import pandas as pd
import io
import re
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- 1. 初期設定 & パッチ ---
@st.cache_resource
def install_playwright():
    if sys.platform != "win32":
        os.system("playwright install chromium")

install_playwright()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# --- 2. CSSによるUIカスタマイズ ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    /* ボタンデザイン */
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #D4AF37;
        color: white;
        border: none;
        font-weight: bold;
    }
    /* メインタイトル黄色背景 */
    .plan-title {
        background-color: #ffff00;
        font-weight: bold;
        padding: 5px 10px;
        font-size: 1.3em;
        display: inline-block;
        border-radius: 3px;
        margin-bottom: 15px;
        color: #000;
    }
    /* ①〜⑥の見出し（赤字・太字・サイズ統一） */
    .red-heading {
        color: #ff0000;
        font-weight: bold;
        font-size: 1.25em;
        margin-top: 10px;
        margin-bottom: 5px;
        display: block;
    }
    /* 強み・課題・改善案の下線 */
    .underlined-keyword {
        text-decoration: underline;
        font-weight: bold;
    }
    /* レポートボックス */
    .report-box {
        padding: 25px;
        border-radius: 10px;
        background-color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. テキスト装飾ロジック ---
def apply_custom_styles(text):
    # タイトル行（Google検索広告プラン：）を黄色背景に
    text = re.sub(r'(Google検索広告プラン：[^\n]+)', r'<span class="plan-title">\1</span>', text)
    
    # ①〜⑥を赤文字・太字・サイズ統一
    headings = ["①", "②", "③", "④", "⑤", "⑥"]
    for h in headings:
        # 見出しの開始から改行または特定の終端までをクラスで囲む
        pattern = rf'({h}[^ \n\d]+)'
        text = re.sub(pattern, r'<span class="red-heading">\1</span>', text)
    
    # 強み・課題・改善案に下線
    keywords = ["強み", "課題", "改善案"]
    for kw in keywords:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    
    # 改行をHTMLの改行に変換
    text = text.replace("\n", "<br>")
    return text

# --- 4. 関数定義 (スクレイピング/AI/Excel) ---
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

def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        
        prompt = f"""
        あなたは買取業界専門の広告コンサルタントです。以下のサイトを分析し、Google検索広告プランを作成してください。
        冒頭に「Google検索広告プラン：(サイト名)」を必ず含めてください。
        
        【出力ルール】:
        以下の①〜⑥の見出しで構成し、①には「強み」「課題」「改善案」という言葉を必ず含めてください。
        最後に [DATA_START]CSVデータ[DATA_END] を付与してください。
        ①サイト解析結果
        ②広告文（DL）：見出し15個
        ③説明文（DL）：4個
        ④キーワード（DL）：20個以上
        ⑤構造化スニペット
        ⑥コールアウトアセット
        
        【サイトテキスト】: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI生成エラー: {str(e)}"

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
    except: return None

# --- 5. メインUI ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide", page_icon="🚀")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/1995/1995531.png", width=100)
    st.title("Admin Menu")
    input_password = st.text_input("アクセスパスワード", type="password")
    st.divider()
    st.info("URLを入力して「分析＆生成スタート」を押してください。")

if input_password != "password":
    if input_password != "": st.error("パスワードが正しくありません。")
    st.stop()

api_key = st.secrets.get("GEMINI_API_KEY")

st.title("🚀 検索（リスティング）広告案 自動生成ツール")

with st.container():
    col1, col2 = st.columns([4, 1])
    with col1:
        target_url = st.text_input("URL入力", placeholder="https://********.com", label_visibility="collapsed")
    with col2:
        start_btn = st.button("分析＆生成スタート")

if start_btn and target_url:
    with st.status("🚀 解析中...", expanded=True) as status:
        cleaned_text = asyncio.run(fetch_and_clean_content(target_url))
        st.session_state.ad_result = generate_ad_plan(cleaned_text, api_key)
        status.update(label="✅ 生成完了！", state="complete")
        st.balloons()

# --- 結果表示エリア ---
if st.session_state.ad_result:
    excel_file = create_excel(st.session_state.ad_result)
    if excel_file:
        st.download_button(label="📊 Excel形式でダウンロード", data=excel_file, file_name="ad_strategy.xlsx")

    # 装飾を適用
    styled_html = apply_custom_styles(st.session_state.ad_result.split("[DATA_START]")[0])

    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ ターゲット・アセット"])
    
    # 各タブに装飾済みHTMLを流し込む
    with tab1:
        st.markdown(f'<div class="report-box">{styled_html.split("<span class=\'red-heading\'>②")[0]}</div>', unsafe_allow_html=True)
    with tab2:
        content_tab2 = "②" + styled_html.split("<span class='red-heading'>②")[1].split("<span class='red-heading'>④")[0]
        st.markdown(f'<div class="report-box">{content_tab2}</div>', unsafe_allow_html=True)
    with tab3:
        content_tab3 = "④" + styled_html.split("<span class='red-heading'>④")[1]
        st.markdown(f'<div class="report-box">{content_tab3}</div>', unsafe_allow_html=True)
