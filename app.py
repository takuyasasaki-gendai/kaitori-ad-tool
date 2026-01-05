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
from google.api_core import exceptions

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

# --- 2. CSSデザイン (指示通りのUIを維持) ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }

    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    .stDownloadButton>button p { color: #000000 !important; }

    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }

    .plan-title {
        color: #ffff00 !important;
        font-size: 1.5em !important;
        font-weight: bold !important;
        margin-bottom: 25px !important;
        display: block !important;
        border-bottom: 2px solid #ffff00;
        padding-bottom: 10px;
    }

    .section-heading {
        color: #ffffff !important;
        font-weight: bold !important;
        font-size: 1.25em !important;
        margin-top: 35px !important;
        margin-bottom: 15px !important;
        display: block !important;
        border-left: 5px solid #D4AF37;
        padding-left: 15px;
    }

    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }
    .report-box { padding: 20px; border-radius: 0px; background-color: transparent; margin-bottom: 25px; line-height: 1.8; }
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }
    button[data-baseweb="tab"] p { color: #888 !important; }
    button[aria-selected="true"] p { color: #D4AF37 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="section-heading">\1\2</span>', text)
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    text = re.sub(r'(Google検索広告プラン：[^\n<]+)', r'<span class="plan-title">\1</span>', text)
    text = text.replace("\n", "<br>")
    return text

# --- 4. ロジック関数 (スワイプ型LP対応のスクレイピング) ---
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
        # スワイプ形式LPはモバイル表示が多いため、iPhoneとしてシミュレート
        context = await browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # 【重要】スワイプ/スクロール形式LPの全コンテンツを読み込ませるためのシミュレーション
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header", "aside"]): s.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:4500]
        except Exception as e:
            await browser.close()
            return f"Error: {str(e)}"

# --- 4. ロジック関数 (プロンプトをより厳格に修正) ---
def generate_ad_plan(own_text, comp_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        
        # プロンプトをより構造化し、ミスを防ぐ
        prompt = f"""
        あなたは買取広告コンサルタントです。自社サイトと競合サイトを比較分析し、Google検索広告プランを作成してください。

        【解析対象】
        自社サイト: {own_text}
        競合サイト: {comp_text}

        【指示】
        1. 広告ランク最大化のため、キーワードを見出し1に含め、競合と差別化した訴求を優先せよ。
        2. 判定(Status): 競合より劣る・平凡なら「LOSS」、勝っているなら「WIN」とせよ。
        3. 改善案(Hint): LOSSの場合、どう書き換えれば広告ランクが上がるか具体的に。

        【出力形式】
        最初にサイト解析文章を書き、その後に必ず以下の形式でデータを書き出してください。
        ※コードブロック（```）は使わず、直接テキストで書いてください。

        [DATA_START]
        Type,Content,Details,Other1,Other2,Status,Hint
        見出し,(30文字以内),,,WIN,
        見出し,(30文字以内),,,LOSS,(改善案)
        説明文,(90文字以内),,,WIN,
        キーワード,(単語),(マッチタイプ),(CPC数値),(優先度),WIN,
        スニペット,(種類),(値),,,WIN,
        コールアウト,(内容),,,,WIN,
        [DATA_END]
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI生成エラー: {str(e)}"

# --- 結果表示部分のパース処理（より頑丈に） ---
if st.session_state.ad_result:
    res_text = st.session_state.ad_result
    df_all = None

    # [DATA_START] を探す。なければ「Type,Content」などの文字列を探す
    start_tag = "[DATA_START]"
    end_tag = "[DATA_END]"
    
    if start_tag in res_text and end_tag in res_text:
        try:
            raw_csv = res_text.split(start_tag)[1].split(end_tag)[0].strip()
            # 余計なバッククォートやマークダウン記法を除去
            raw_csv = re.sub(r'```.*?(\n|$)', '', raw_csv).strip()
            df_all = pd.read_csv(io.StringIO(raw_csv))
        except Exception as e:
            st.warning(f"データの読み込みに失敗しました（形式エラー）。生データを確認してください。")

def safe_table_display(df, type_name, col_mapping):
    try:
        if df is None or df.empty: return False
        sub_df = df[df['Type'].astype(str).str.contains(type_name, na=False, case=False)].copy()
        if sub_df.empty: return False
        
        # インデックスを1から始まる形にリセット
        sub_df.index = range(1, len(sub_df) + 1)
        
        display_cols = []
        for orig_col in col_mapping.keys():
            if orig_col not in sub_df.columns: sub_df[orig_col] = ""
            display_cols.append(orig_col)
        
        st.table(sub_df[display_cols].rename(columns=col_mapping))
        return True
    except: return False

# --- 5. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.markdown("<h1 style='text-align: center; font-size: 50px;'>⚙️</h1>", unsafe_allow_html=True)
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
            res = generate_ad_plan(cleaned, api_key)
            if "ERROR_429" in res:
                st.error("⚠️ API制限に達しました。時間を置いてからお試しください。")
            else:
                st.session_state.ad_result = res
                st.balloons()

# --- 結果表示 ---
if st.session_state.ad_result:
    df_all = None
    if "[DATA_START]" in st.session_state.ad_result:
        try:
            raw_csv = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            raw_csv = re.sub(r'```.*?(\n|$)', '', raw_csv).strip()
            df_all = pd.read_csv(io.StringIO(raw_csv))
            df_all.columns = df_all.columns.str.strip()
        except: pass

    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            for s, t in [('②広告文','見出し'),('③説明文','説明文'),('④キーワード','キーワード')]:
                tmp = df_all[df_all['Type'].astype(str).str.contains(t, na=False, case=False)].copy()
                if not tmp.empty:
                    tmp.index = range(1, len(tmp) + 1)
                    tmp.to_excel(writer, index=True, index_label="No", sheet_name=s)
            tmp_a = df_all[df_all['Type'].astype(str).str.contains('スニペット|コールアウト', na=False, case=False)].copy()
            if not tmp_a.empty:
                tmp_a.index = range(1, len(tmp_a) + 1)
                tmp_a.to_excel(writer, index=True, index_label="No", sheet_name='⑤⑥アセット')
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
        st.markdown(apply_decoration("②広告文案（見出し）"), unsafe_allow_html=True)
        safe_table_display(df_all, '見出し', {'Content': '広告見出し案'})
        st.markdown(apply_decoration("③説明文案"), unsafe_allow_html=True)
        safe_table_display(df_all, '説明文', {'Content': '説明文案'})
        st.markdown('</div>', unsafe_allow_html=True)

with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        
        # ④ キーワード
        if df_all is not None:
            st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
            safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'})
            
            st.divider() # 区切り線
            
            # ⑤ 構造化スニペット
            st.markdown(apply_decoration("⑤構造化スニペット"), unsafe_allow_html=True)
            safe_table_display(df_all, 'スニペット', {'Content':'種類','Details':'値'})
            
            st.divider() # 区切り線
            
            # ⑥ コールアウトアセット（ここを修正）
            # 文章から抜き出すのではなく、見出し等と同様に判定付き表示(dynamic_ad_display)を使う
            dynamic_ad_display(df_all, 'コールアウト', "⑥コールアウトアセット")
            
        st.markdown('</div>', unsafe_allow_html=True)
