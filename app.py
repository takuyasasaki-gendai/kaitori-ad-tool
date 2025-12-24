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

# --- 2. CSSデザイン ---
st.markdown("""
    <style>
    /* 全体背景 */
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }

    /* サイドバーのアイコンを白くする */
    [data-testid="stSidebar"] img {
        filter: brightness(0) invert(1);
    }

    /* ボタン */
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }

    /* タイトル（黄色背景・黒文字） */
    .plan-title {
        background-color: #ffff00; font-weight: bold; padding: 6px 12px;
        font-size: 1.3em; display: inline-block; border-radius: 2px;
        margin-bottom: 20px; color: #000000 !important;
    }

    /* ①〜⑥見出し（白背景・黒文字） */
    .white-block-heading {
        background-color: #ffffff; color: #000000 !important;
        font-weight: bold; font-size: 1.15em; margin-top: 25px;
        margin-bottom: 15px; padding: 5px 15px; display: inline-block; border-radius: 2px;
    }
    .white-block-heading span, .white-block-heading { color: #000000 !important; }

    /* 下線キーワード */
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }

    /* レポート容器 */
    .report-box {
        padding: 30px; border-radius: 10px; background-color: #262626;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); margin-bottom: 25px; line-height: 1.8;
    }

    /* テーブルスタイル */
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    # ①〜⑥を白背景・黒文字に
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="white-block-heading">\1\2</span>', text)
    # キーワード下線
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    # 黄色タイトル
    text = re.sub(r'(Google検索広告プラン：[^\n<]+)', r'<span class="plan-title">\1</span>', text)
    text = text.replace("\n", "<br>")
    return text

# --- 4. ロジック関数 ---
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header", "aside"]): s.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:4000]
        except Exception as e:
            await browser.close()
            return f"Error: {str(e)}"

def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-1.5-flash" if "models/gemini-1.5-flash" in available_models else available_models[0]
        model = genai.GenerativeModel(target_model)
        prompt = f"買取広告コンサルとして、①解析結果、②広告見出し15個、③説明文4個、④キーワード20個、⑤スニペット、⑥コールアウトを作成。末尾に[DATA_START]CSVデータ[DATA_END]を付与。解析：{site_text}"
        return model.generate_content(prompt).text
    except Exception as e: return f"AI生成エラー: {str(e)}"

# --- 5. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    # 歯車アイコン（CSSフィルタで白くしています）
    st.image("https://cdn-icons-png.flaticon.com/512/3524/3524659.png", width=60)
    st.title("Admin Menu")
    pwd = st.text_input("アクセスパスワード", type="password")
    if pwd != "password":
        if pwd != "": st.error("パスワードが違います")
        st.stop()

api_key = st.secrets.get("GEMINI_API_KEY")
st.title("検索（リスティング）広告案 自動生成ツール")

url_in = st.text_input("LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略構築中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

if st.session_state.ad_result:
    # データのパース
    df_all = None
    if "[DATA_START]" in st.session_state.ad_result:
        raw = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
        df_all = pd.read_csv(io.StringIO(raw))

    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_all[df_all['Type'] == '見出し'].to_excel(writer, index=False, sheet_name='②広告文')
            df_all[df_all['Type'] == '説明文'].to_excel(writer, index=False, sheet_name='③説明文')
            df_all[df_all['Type'] == 'キーワード'].to_excel(writer, index=False, sheet_name='④キーワード')
            df_all[df_all['Type'].isin(['スニペット', 'コールアウト'])].to_excel(writer, index=False, sheet_name='アセット')
        st.download_button("📊 Excel形式でダウンロード", data=out.getvalue(), file_name="ad_strategy.xlsx")

    main_text = st.session_state.ad_result.split("[DATA_START]")[0]
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        content1 = main_text.split("②")[0] if "②" in main_text else main_text
        st.markdown(f'<div class="report-box">{apply_decoration(content1)}</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        # ②広告文（表）
        st.markdown(apply_decoration("②広告文（見出し15個）"), unsafe_allow_html=True)
        if df_all is not None:
            h_df = df_all[df_all['Type'] == '見出し'].copy()
            st.table(h_df[['Content']].rename(columns={'Content': '見出し案'}))
        
        # ③説明文（表）
        st.markdown(apply_decoration("③説明文（4個）"), unsafe_allow_html=True)
        if df_all is not None:
            d_df = df_all[df_all['Type'] == '説明文'].copy()
            st.table(d_df[['Content']].rename(columns={'Content': '説明文案'}))
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        # ④キーワード（表）
        st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
        if df_all is not None:
            kw_df = df_all[df_all['Type'] == 'キーワード'].copy()
            st.table(kw_df[['Content', 'Details', 'Other1', 'Other2']].rename(columns={'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'}))
        
        # ⑤スニペット（表）
        st.markdown(apply_decoration("⑤構造化スニペット"), unsafe_allow_html=True)
        if df_all is not None:
            sn_df = df_all[df_all['Type'] == 'スニペット'].copy()
            st.table(sn_df[['Content', 'Details']].rename(columns={'Content':'種類','Details':'値'}))

        # ⑥コールアウト
        st.markdown(apply_decoration("⑥コールアウトアセット"), unsafe_allow_html=True)
        c_text = main_text.split("⑥")[1] if "⑥" in main_text else ""
        st.markdown(c_text.replace("\n", "<br>"), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
