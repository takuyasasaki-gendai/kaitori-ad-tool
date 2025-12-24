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

# --- 2. CSSデザイン (ブラックテーマ & 白背景黒文字見出し) ---
st.markdown("""
    <style>
    /* 全体背景と基本テキストカラー */
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    
    /* 歯車アイコンを白く反転 */
    [data-testid="stSidebar"] img { filter: brightness(0) invert(1); }

    /* Excelダウンロードボタン: 背景ゴールド・テキスト黒 */
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    /* 生成ボタン: 背景ゴールド・テキスト白 */
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }

    /* メインタイトル黄色背景: テキスト黒を絶対強制 */
    .plan-title {
        background-color: #ffff00 !important;
        font-weight: bold !important;
        padding: 6px 12px !important;
        font-size: 1.3em !important;
        display: inline-block !important;
        border-radius: 2px !important;
        margin-bottom: 20px !important;
        color: #000000 !important;
    }

    /* ①〜⑥の見出し: 白背景・黒文字を絶対強制 */
    .white-block-heading {
        background-color: #ffffff !important;
        color: #000000 !important;
        font-weight: bold !important;
        font-size: 1.15em !important;
        margin-top: 25px !important;
        margin-bottom: 15px !important;
        padding: 5px 15px !important;
        display: inline-block !important;
        border-radius: 2px !important;
    }
    /* 見出し内の文字色を黒に固定 */
    .white-block-heading span, 
    .white-block-heading p { 
        color: #000000 !important; 
    }

    /* 強み・課題・改善案の下線 */
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }
    
    /* レポート容器 */
    .report-box {
        padding: 30px; border-radius: 10px; background-color: #262626;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); margin-bottom: 25px; line-height: 1.8;
    }

    /* テーブルデザイン */
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }

    /* タブ設定 */
    button[data-baseweb="tab"] p { color: #888 !important; }
    button[aria-selected="true"] p { color: #D4AF37 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    # ①〜⑥を白背景・黒文字に
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="white-block-heading">\1\2</span>', text)
    # 強み・課題・改善案に下線
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    # 黄色タイトルを黒文字で
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
        
        【重要ルール】
        1. 冒頭に「Google検索広告プラン：(サイト名)」を記載。
        2. ①サイト解析結果、②広告文（DL）、③説明文（DL）、④キーワード（DL）、⑤構造化スニペット、⑥コールアウトアセット の順で作成。
        3. 回答の最後に、以下のCSVデータを必ず含めてください。ヘッダーは必ず Type,Content,Details,Other1,Other2 です。
        [DATA_START]
        Type,Content,Details,Other1,Other2
        見出し,(広告見出しを15個書く),,,
        説明文,(説明文を4個書く),,,
        キーワード,(キーワード),(マッチタイプ),(推定CPC),(優先度)
        スニペット,(種類),(値),,
        コールアウト,(内容),,,
        [DATA_END]

        解析サイト：{site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AI生成エラー: {str(e)}"

# エラーを回避して表を表示するための安全な関数
def safe_table_display(df, type_name, col_mapping):
    try:
        # 指定されたTypeを含む行を抽出
        sub_df = df[df['Type'].str.contains(type_name, na=False, case=False)].copy()
        if sub_df.empty:
            return False
        
        # 必要な列がない場合は作成（エラー防止）
        display_cols = []
        for orig_col, new_name in col_mapping.items():
            if orig_col in sub_df.columns:
                display_cols.append(orig_col)
            else:
                sub_df[orig_col] = "" # 列がなければ空で作る
                display_cols.append(orig_col)
        
        # リネームして表示
        st.table(sub_df[display_cols].rename(columns=col_mapping))
        return True
    except:
        return False

# --- 5. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3524/3524659.png", width=60)
    pwd = st.text_input("パスワード", type="password")
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

# --- 結果表示 ---
if st.session_state.ad_result:
    # 1. データの準備（パース）
    df_all = None
    if "[DATA_START]" in st.session_state.ad_result:
        try:
            raw_csv = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            df_all = pd.read_csv(io.StringIO(raw_csv))
            df_all.columns = df_all.columns.str.strip() # ヘッダーの空白を削除
        except: pass

    # 2. Excelダウンロードボタン
    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            for s, t in [('②広告文','見出し'),('③説明文','説明文'),('④キーワード','キーワード')]:
                tmp = df_all[df_all['Type'].str.contains(t, na=False, case=False)]
                if not tmp.empty: tmp.to_excel(writer, index=False, sheet_name=s)
            tmp_a = df_all[df_all['Type'].str.contains('スニペット|コールアウト', na=False, case=False)]
            if not tmp_a.empty: tmp_a.to_excel(writer, index=False, sheet_name='⑤⑥アセット')
        st.download_button("📊 Excel形式でダウンロード", data=out.getvalue(), file_name="ad_strategy.xlsx")

    # 3. 画面表示
    full_raw_text = st.session_state.ad_result.split("[DATA_START]")[0]
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        c1 = full_raw_text.split("②")[0] if "②" in full_raw_text else full_raw_text
        st.markdown(apply_decoration(c1), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("②広告文（見出し15個）"), unsafe_allow_html=True)
        if df_all is not None:
            if not safe_table_display(df_all, '見出し', {'Content': '見出し案'}):
                st.write("（表の生成に失敗しました。下の全体テキストを確認してください）")
        
        st.markdown(apply_decoration("③説明文（4個）"), unsafe_allow_html=True)
        if df_all is not None:
            safe_table_display(df_all, '説明文', {'Content': '説明文案'})
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
        if df_all is not None:
            safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'})
        
        st.markdown(apply_decoration("⑤構造化スニペット"), unsafe_allow_html=True)
        if df_all is not None:
            safe_table_display(df_all, 'スニペット', {'Content':'種類','Details':'値'})

        st.markdown(apply_decoration("⑥コールアウトアセット"), unsafe_allow_html=True)
        c6 = full_raw_text.split("⑥")[1] if "⑥" in full_raw_text else ""
        st.markdown(apply_decoration(c6), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
