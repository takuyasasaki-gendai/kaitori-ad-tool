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
    .main { background-color: #f8f9fa; }
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white; border: none; font-weight: bold;
    }
    .plan-title {
        background-color: #ffff00; font-weight: bold; padding: 5px 10px;
        font-size: 1.3em; display: inline-block; border-radius: 3px;
        margin-bottom: 15px; color: #000;
    }
    .red-heading {
        color: #ff0000; font-weight: bold; font-size: 1.25em;
        margin-top: 15px; margin-bottom: 10px; display: block;
    }
    .underlined-keyword { text-decoration: underline; font-weight: bold; }
    .report-box {
        padding: 25px; border-radius: 10px; background-color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; line-height: 1.7;
    }
    /* テーブルの見た目調整 */
    .stTable { background-color: white; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 (HTMLを返す) ---
def apply_decoration(text):
    if not text: return ""
    # #を削除
    text = text.replace("#", "")
    # ①〜⑥を赤文字に
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="red-heading">\1\2</span>', text)
    # 強み・課題・改善案に下線
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    # タイトル行を黄色背景に
    text = re.sub(r'(Google検索広告プラン：[^\n<]+)', r'<span class="plan-title">\1</span>', text)
    # 改行対応
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
            await asyncio.sleep(3)
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
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        prompt = f"買取広告コンサルとして以下のサイトを分析し、①サイト解析結果、②広告文（DL）、③説明文（DL）、④キーワード（DL）、⑤構造化スニペット、⑥コールアウトアセットを詳細に作成してください。冒頭に「Google検索広告プラン：(サイト名)」を、末尾に[DATA_START]CSVデータ[DATA_END]を必ず含めてください。解析サイト：{site_text}"
        return model.generate_content(prompt).text
    except Exception as e: return f"AI生成エラー: {str(e)}"

# データ解析用関数（ExcelとUIテーブル両方で使用）
def parse_result_data(text):
    try:
        if "[DATA_START]" in text:
            raw = text.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            return pd.read_csv(io.StringIO(raw))
    except: return None
    return None

# --- 5. メインUI ---
st.set_page_config(page_title="検索（リスティング）広告案 自動生成ツール", layout="wide", page_icon="🚀")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/1995/1995531.png", width=100)
    st.title("Admin Menu")
    pwd = st.text_input("アクセスパスワード", type="password")
    if pwd != "password":
        if pwd != "": st.error("パスワードが違います")
        st.stop()

api_key = st.secrets.get("GEMINI_API_KEY")
st.title("🚀 検索（リスティング）広告案 自動生成ツール")

url_in = st.text_input("LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略構築中...") as status:
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            status.update(label="✅ 生成完了！", state="complete")
            st.balloons()

# --- 結果表示 ---
if st.session_state.ad_result:
    # データをパース
    df_all = parse_result_data(st.session_state.ad_result)
    main_text = st.session_state.ad_result.split("[DATA_START]")[0]
    
    # Excelボタン
    if df_all is not None:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_all[df_all['Type'] == '見出し'].to_excel(writer, index=False, sheet_name='②広告文')
            df_all[df_all['Type'] == '説明文'].to_excel(writer, index=False, sheet_name='③説明文')
            df_all[df_all['Type'] == 'キーワード'].to_excel(writer, index=False, sheet_name='④キーワード')
            df_all[df_all['Type'].isin(['スニペット', 'コールアウト'])].to_excel(writer, index=False, sheet_name='アセット')
        st.download_button("📊 Excel形式でダウンロード", data=out.getvalue(), file_name="ad_strategy.xlsx")

    # セクション分割用関数
    def get_section_text(full_text, start_num, end_num=None):
        try:
            if end_num:
                pattern = f"{start_num}(.*?){end_num}"
                match = re.search(pattern, full_text, re.DOTALL)
                return start_num + match.group(1) if match else ""
            pattern = f"{start_num}(.*)"
            match = re.search(pattern, full_text, re.DOTALL)
            return start_num + match.group(1) if match else ""
        except: return ""

    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        # #を除去して表示
        content1 = main_text.split("②")[0] if "②" in main_text else main_text
        st.markdown(f'<div class="report-box">{apply_decoration(content1)}</div>', unsafe_allow_html=True)
    
    with tab2:
        content2 = get_section_text(main_text, "②", "④")
        st.markdown(f'<div class="report-box">{apply_decoration(content2)}</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        # タイトル「④キーワード」を表示
        st.markdown(apply_decoration("④キーワード（一覧）"), unsafe_allow_html=True)
        
        # キーワードを綺麗なテーブルで表示
        if df_all is not None:
            kw_df = df_all[df_all['Type'] == 'キーワード'].copy()
            if not kw_df.empty:
                # 表を見やすく整形
                kw_df = kw_df.rename(columns={'Content': 'キーワード', 'Details': 'マッチタイプ', 'Other1': '推定CPC', 'Other2': '優先度'})
                st.table(kw_df[['キーワード', 'マッチタイプ', '推定CPC', '優先度']])
        
        # 残りの⑤⑥を表示
        content3_rest = get_section_text(main_text, "⑤")
        st.markdown(apply_decoration(content3_rest), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
