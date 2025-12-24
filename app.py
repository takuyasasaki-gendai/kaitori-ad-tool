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

# --- 2. CSSデザイン (ご指示のUIを完全維持) ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    [data-testid="stSidebar"] img { filter: brightness(0) invert(1); }
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }
    .plan-title {
        background-color: #ffff00; font-weight: bold; padding: 6px 12px;
        font-size: 1.3em; display: inline-block; border-radius: 2px;
        margin-bottom: 20px; color: #000000 !important;
    }
    .white-block-heading {
        background-color: #ffffff; color: #000000 !important;
        font-weight: bold; font-size: 1.15em; margin-top: 25px;
        margin-bottom: 15px; padding: 5px 15px; display: inline-block; border-radius: 2px;
    }
    .white-block-heading span, .white-block-heading { color: #000000 !important; }
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }
    .report-box {
        padding: 30px; border-radius: 10px; background-color: #262626;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); margin-bottom: 25px; line-height: 1.8;
    }
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="white-block-heading">\1\2</span>', text)
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
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
        # プロンプトで列名を厳密に指定
        prompt = f"買取広告コンサルとして以下のサイトを分析し、①サイト解析、②見出し15個、③説明文4個、④キーワード20個、⑤スニペット、⑥コールアウトを作成。最後に必ず Type,Content,Details,Other1,Other2 というヘッダーのCSVを [DATA_START] [DATA_END] で囲んで付与。解析：{site_text}"
        return model.generate_content(prompt).text
    except Exception as e: return f"AI生成エラー: {str(e)}"

# エラー対策済みのパース関数
def get_safe_table(df, filter_type, col_map):
    try:
        sub_df = df[df['Type'].str.contains(filter_type, na=False)].copy()
        if sub_df.empty: return None
        # 必要な列が存在するか確認し、なければ空文字で補完
        for col in col_map.keys():
            if col not in sub_df.columns: sub_df[col] = ""
        return sub_df[list(col_map.keys())].rename(columns=col_map)
    except: return None

# --- 5. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3524/3524659.png", width=60)
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
    df_all = None
    if "[DATA_START]" in st.session_state.ad_result:
        try:
            raw = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            df_all = pd.read_csv(io.StringIO(raw))
            df_all.columns = df_all.columns.str.strip() # 列名の余計な空白を削除
        except: pass

    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            for s, t in [('②広告文','見出し'),('③説明文','説明文'),('④キーワード','キーワード')]:
                tmp = df_all[df_all['Type'].str.contains(t, na=False)]
                if not tmp.empty: tmp.to_excel(writer, index=False, sheet_name=s)
            tmp_a = df_all[df_all['Type'].str.contains('スニペット|コールアウト', na=False)]
            if not tmp_a.empty: tmp_a.to_excel(writer, index=False, sheet_name='⑤⑥アセット')
        st.download_button("📊 Excel形式でダウンロード", data=out.getvalue(), file_name="ad_strategy.xlsx")

    main_text = st.session_state.ad_result.split("[DATA_START]")[0]
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        c1 = main_text.split("②")[0] if "②" in main_text else main_text
        st.markdown(f'<div class="report-box">{apply_decoration(c1)}</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("②広告文（見出し15個）"), unsafe_allow_html=True)
        if df_all is not None:
            res = get_safe_table(df_all, '見出し', {'Content': '見出し案'})
            if res is not None: st.table(res)
            else: st.write("（データ形式エラーのため、下の全体テキストを参照してください）")
        
        st.markdown(apply_decoration("③説明文（4個）"), unsafe_allow_html=True)
        if df_all is not None:
            res = get_safe_table(df_all, '説明文', {'Content': '説明文案'})
            if res is not None: st.table(res)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
        if df_all is not None:
            res = get_safe_table(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'})
            if res is not None: st.table(res)
        
        st.markdown(apply_decoration("⑤構造化スニペット"), unsafe_allow_html=True)
        if df_all is not None:
            res = get_safe_table(df_all, 'スニペット', {'Content':'種類','Details':'値'})
            if res is not None: st.table(res)

        st.markdown(apply_decoration("⑥コールアウトアセット"), unsafe_allow_html=True)
        c6 = main_text.split("⑥")[1] if "⑥" in main_text else ""
        st.markdown(c6.replace("\n", "<br>"), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
