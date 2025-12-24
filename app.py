import streamlit as st
import asyncio
import sys
import os
import pandas as pd
import io
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
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #D4AF37; /* ゴールド系 */
        color: white;
        border: none;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #B8860B;
        color: white;
    }
    .report-box {
        padding: 20px;
        border-radius: 10px;
        background-color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 関数定義 (スクレイピング/AI/Excel) ---
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
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available_models else "models/gemini-1.5-flash"
        model = genai.GenerativeModel(target_model)
        
        prompt = f"""
        あなたは買取業界専門の広告コンサルタントです。以下のサイトを分析し、Google検索広告プランを作成してください。
        【解析サイト】: {site_text}
        
        【出力ルール】:
        以下の①〜⑥の見出しで構成し、最後に [DATA_START]CSVデータ[DATA_END] を付与してください。
        ①サイト解析結果
        ②広告文（DL）：見出し15個
        ③説明文（DL）：4個
        ④キーワード（DL）：20個以上（表形式）
        ⑤構造化スニペット
        ⑥コールアウトアセット
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

# --- 4. メインUI ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide", page_icon="🚀")

# サイドバー設定
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/1995/1995531.png", width=100)
    st.title("Admin Menu")
    input_password = st.text_input("アクセスパスワード", type="password")
    st.divider()
    st.markdown("### 使い方")
    st.info("1. パスワードを入力\n2. 解析したいURLを入力\n3. 生成ボタンを押す\n4. Excelをダウンロード")

# 認証チェック
if input_password != "password":
    if input_password == "":
        st.info("サイドバーからパスワードを入力してください。")
    else:
        st.error("パスワードが正しくありません。")
    st.stop()

# APIキー取得
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("管理者エラー: SecretsにAPIキーが設定されていません。")
    st.stop()

# メインコンテンツ
st.title("🚀 検索（リスティング）広告案 自動生成ツール")
st.caption("AIがサイトを解析し、Google広告の最適なキーワード、見出し、アセットを自動生成します。")

with st.container():
    col1, col2 = st.columns([4, 1])
    with col1:
        target_url = st.text_input("解析したい買取LPのURLを入力してください", placeholder="https://********.com", label_visibility="collapsed")
    with col2:
        start_btn = st.button("分析＆生成スタート")

if start_btn:
    if not target_url:
        st.warning("URLを入力してください。")
    else:
        with st.status("🚀 広告戦略を構築中...", expanded=True) as status:
            st.write("1. サイトの情報を読み込んでいます...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cleaned_text = loop.run_until_complete(fetch_and_clean_content(target_url))
            
            if "Error" in cleaned_text:
                st.error("サイトの読み込みに失敗しました。")
            else:
                st.write("2. AIによる競合・サイト分析を開始...")
                st.session_state.ad_result = generate_ad_plan(cleaned_text, api_key)
                status.update(label="✅ 生成完了！", state="complete", expanded=False)
                st.balloons()

# --- 結果の表示エリア ---
if st.session_state.ad_result:
    excel_file = create_excel(st.session_state.ad_result)
    
    if excel_file:
        st.download_button(
            label="📊 Excel形式でダウンロード（広告文・キーワード）",
            data=excel_file,
            file_name="ad_strategy_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # 結果をタブで整理
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ ターゲット・アセット"])
    
    full_text = st.session_state.ad_result.split("[DATA_START]")[0]
    sections = full_text.split("②") # 暫定的に分割してタブに振り分け
    
    with tab1:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(full_text.split("②")[0])
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        if len(sections) > 1:
            st.markdown("②" + sections[1].split("④")[0])
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        if "④" in full_text:
            st.markdown("④" + full_text.split("④")[1])
        st.markdown('</div>', unsafe_allow_html=True)
