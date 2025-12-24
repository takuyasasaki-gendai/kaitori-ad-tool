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

# --- 2. CSSデザイン (背景色を削除し、文字のみで構成) ---
st.markdown("""
    <style>
    /* 全体背景：黒 */
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }

    /* サイドバーの歯車アイコンを白く */
    [data-testid="stSidebar"] img { filter: brightness(0) invert(1); }

    /* Excelボタン: 背景ゴールド・テキスト黒 */
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    .stDownloadButton>button * { color: #000000 !important; }

    /* 生成ボタン: 背景ゴールド・テキスト白 */
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }

    /* メインタイトル: 背景なし・黄色太文字 */
    .plan-title {
        color: #ffff00 !important;
        font-size: 1.5em !important;
        font-weight: bold !important;
        margin-bottom: 25px !important;
        display: block !important;
        border-bottom: 2px solid #ffff00;
        padding-bottom: 10px;
    }

    /* ①〜⑥見出し: 背景なし・白太文字 + 左側にゴールドの線 */
    .section-heading {
        color: #ffffff !important;
        font-weight: bold !important;
        font-size: 1.3em !important;
        margin-top: 30px !important;
        margin-bottom: 15px !important;
        display: block !important;
        border-left: 5px solid #D4AF37;
        padding-left: 15px;
    }

    /* 下線キーワード */
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }

    /* レポート容器 */
    .report-box {
        padding: 20px; border-radius: 0px; background-color: transparent;
        margin-bottom: 25px; line-height: 1.8;
    }

    /* テーブルスタイル */
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }
    
    /* タブの文字色 */
    button[data-baseweb="tab"] p { color: #888 !important; }
    button[aria-selected="true"] p { color: #D4AF37 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    # ①〜⑥を装飾見出しに
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="section-heading">\1\2</span>', text)
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
        
        prompt = f"""
        あなたは買取広告コンサルタントです。以下のサイトを分析し、Google検索広告プランを作成してください。
        
        【構成】
        冒頭：Google検索広告プラン：(サイト名)
        ①サイト解析結果：詳細に記載。
        ②広告文（DL）：見出し15個
        ③説明文（DL）：4個
        ④キーワード（DL）：20個以上
        ⑤構造化スニペット
        ⑥コールアウトアセット

        【重要：データ書き出し】
        最後に必ず [DATA_START] と [DATA_END] で囲んで、以下のCSVデータ形式のみを出力してください。
        Type,Content,Details,Other1,Other2
        見出し,(内容),,,
        説明文,(内容),,,
        キーワード,(内容),(マッチ),(CPC),(優先)
        スニペット,(種類),(値),,
        コールアウト,(内容),,,

        解析サイト：{site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AI生成エラー: {str(e)}"

def safe_table_display(df, type_name, col_mapping):
    try:
        if df is None or df.empty: return False
        sub_df = df[df['Type'].str.contains(type_name, na=False, case=False)].copy()
        if sub_df.empty: return False
        
        # 必要な列を確保
        for orig_col in col_mapping.keys():
            if orig_col not in sub_df.columns: sub_df[orig_col] = ""
        
        st.table(sub_df[list(col_mapping.keys())].rename(columns=col_mapping))
        return True
    except: return False

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

# --- 結果表示エリア ---
if st.session_state.ad_result:
    # データパース
    df_all = None
    if "[DATA_START]" in st.session_state.ad_result:
        try:
            raw_csv = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            raw_csv = re.sub(r'```.*?(\n|$)', '', raw_csv).strip()
            df_all = pd.read_csv(io.StringIO(raw_csv))
            df_all.columns = df_all.columns.str.strip()
        except: pass

    # Excelボタン
    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            for s, t in [('②広告文','見出し'),('③説明文','説明文'),('④キーワード','キーワード')]:
                tmp = df_all[df_all['Type'].str.contains(t, na=False, case=False)]
                if not tmp.empty: tmp.to_excel(writer, index=False, sheet_name=s)
            tmp_a = df_all[df_all['Type'].str.contains('スニペット|コールアウト', na=False, case=False)]
            if not tmp_a.empty: tmp_a.to_excel(writer, index=False, sheet_name='⑤⑥アセット')
        st.download_button("📊 Excel形式でダウンロード", data=out.getvalue(), file_name="ad_strategy.xlsx")

    main_text = st.session_state.ad_result.split("[DATA_START]")[0]
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        c1 = main_text.split("②")[0] if "②" in main_text else main_text
        st.markdown(apply_decoration(c1), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("②広告文"), unsafe_allow_html=True)
        if not safe_table_display(df_all, '見出し', {'Content': '広告見出し案'}):
            st.info("※データの読み込み中、または形式不一致です。下の文章をご確認ください。")
        
        st.markdown(apply_decoration("③説明文"), unsafe_allow_html=True)
        if not safe_table_display(df_all, '説明文', {'Content': '広告説明文案'}):
            pass
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
        if not safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'}):
            pass
        
        st.markdown(apply_decoration("⑤構造化スニペット"), unsafe_allow_html=True)
        if not safe_table_display(df_all, 'スニペット', {'Content':'種類','Details':'値'}):
            pass

        st.markdown(apply_decoration("⑥コールアウトアセット"), unsafe_allow_html=True)
        c6 = main_text.split("⑥")[1] if "⑥" in main_text else ""
        st.markdown(apply_decoration(c6), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
