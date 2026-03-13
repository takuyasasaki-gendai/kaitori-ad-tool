import streamlit as st
import asyncio
import sys
import os
import pandas as pd
import io
import re
import subprocess
import requests
import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- 1. 初期設定 ---
st.set_page_config(page_title="Google広告プラン自動生成ツール", layout="wide")
api_key = st.secrets.get("GEMINI_API_KEY")

@st.cache_resource
def install_playwright_binary():
    try:
        # 確実にパスを通すため python -m 経由で実行
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except: pass

install_playwright_binary()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# --- 2. CSSデザイン ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    div[data-testid="stPopover"] button p { color: #000000 !important; }
    div[data-testid="stPopoverBody"] p, div[data-testid="stPopoverBody"] span, div[data-testid="stPopoverBody"] div { color: #000000 !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; height: 3.5em; background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #D4AF37; color: white !important; border: none; font-weight: bold; }
    .logic-box { padding: 25px; border-radius: 10px; background-color: #1e1e1e; border: 1px solid #D4AF37; margin-bottom: 25px; line-height: 1.6; }
    .logic-table { width: 100%; border-collapse: collapse; margin-top: 10px; color: #ffffff; }
    .logic-table th, .logic-table td { border: 1px solid #444; padding: 10px; text-align: left; font-size: 0.9em; }
    .logic-table th { background-color: #333; color: #D4AF37; }
    .report-box { padding: 20px; border-radius: 0px; background-color: transparent; margin-bottom: 25px; line-height: 1.8; border: 1px solid #333; }
    .section-heading { color: #ffffff !important; font-weight: bold !important; font-size: 1.25em !important; margin-top: 35px; border-left: 5px solid #D4AF37; padding-left: 15px; display: block; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. サイドバー認証 ---
with st.sidebar:
    st.title("Admin Access")
    if st.text_input("Password", type="password") != "password":
        st.warning("パスワードを入力してください")
        st.stop()
    st.success("認証済み")
    if st.button("キャッシュをクリアして再起動"):
        st.cache_resource.clear()
        st.rerun()

# --- 4. ロジック解説 ---
st.title("Google広告プラン自動生成ツール")
st.markdown("""
<div class="logic-box">
<h3>⚙️ 広告プラン構築の思考プロセス</h3>
<table class="logic-table">
    <tr><th>項目</th><th>生成ロジック</th></tr>
    <tr><td><b>② 見出し(15)</b></td><td>解析したUSPから検索意図に刺さる「ベネフィット」を抽出。</td></tr>
    <tr><td><b>④ キーワード(20)</b></td><td>ニーズ別にマッチタイプ（部分・フレーズ・完全）を戦略的に選定。</td></tr>
    <tr><td><b>⑤⑥ 詳細ボタン</b></td><td>設定に必要な「ヘッダー種別」や「具体的な戦略理由」を表示。</td></tr>
</table>
</div>
""", unsafe_allow_html=True)

# --- 5. 補助関数 ---
def clean_text(text):
    if not text or pd.isna(text): return ""
    return str(text).replace("**", "").replace("###", "").replace("`", "").replace('"', '').strip()

def apply_decoration(text):
    if not text: return ""
    text = clean_text(text)
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="section-heading">\1\2</span>', text)
    text = text.replace("\n", "<br>")
    return text

def flexible_display(df, filter_keywords, label, is_asset=False):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    if df is None or df.empty: return
    mask = df['Type'].astype(str).str.contains(filter_keywords, case=False, na=False, regex=True)
    sub_df = df[mask].copy()
    if sub_df.empty:
        st.write("（データがありません。再生成してください。）")
        return
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content, details = clean_text(row.get('Content')), clean_text(row.get('Details'))
        cols = st.columns([0.1, 0.7, 0.2])
        cols[0].write(i)
        cols[1].write(content)
        display_details = details if "文字以内" not in details else ""
        if is_asset or (display_details and not any(x in display_details for x in ["見出し", "説明文"])):
            with cols[2]:
                with st.popover("💡 詳細"): st.write(display_details if display_details else "戦略的最適化済み")
        else: cols[2].write("✅ WIN")

# --- 6. 超堅牢・ハイブリッド解析 ---
async def fetch_content(url):
    # 経路1: Playwright (JavaScript実行サイト用)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process", "--no-zygote"])
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        # 経路2: Requests (軽量・高速)
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
        except: return None

    if soup:
        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
        return " ".join(soup.get_text(separator=" ").split())[:4000]
    return None

def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"""
        あなたは日本最高峰の広告コンサルタントです。LPを業界問わず分析し以下を厳守してください。
        【出力】
        1. サイト解析（①強み ②課題 ③改善案）
        2. [DATA_START] CSVデータ [DATA_END]
        【CSVカラム】Type,Content,Details,Other1,Other2,Status,Hint
        - ④Keyword: 20個。Detailsにマッチタイプ、Other1に理由。
        - ⑤Snippet: Detailsにヘッダー種別。⑥Callout: Detailsに訴求メリット。注釈禁止。
        内容: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AIエラー: {str(e)}"

# --- 7. 入力エリア ---
input_mode = st.radio("入力方法を選択してください", ["URLを読み込む", "テキストを直接入力する"])
input_data = ""

if input_mode == "URLを読み込む":
    url_in = st.text_input("LPのURLを入力してください")
    if st.button("生成スタート"):
        if url_in:
            with st.spinner("🚀 サイトを解析中..."):
                input_data = asyncio.run(fetch_content(url_in))
                if not input_data: st.error("サイトを読み込めませんでした。直接入力をお試しください。")
else:
    input_data = st.text_area("LPのテキスト（強みやサービス内容）を貼り付けてください", height=200)
    if st.button("解析・生成スタート"):
        if not input_data: st.error("テキストを入力してください")

# --- 8. 生成と表示 ---
if input_data and "生成" in st.session_state.get("last_clicked", "生成"):
    with st.spinner("🚀 広告戦略を構築中..."):
        st.session_state.ad_result = generate_ad_plan(input_data, api_key)
        st.balloons()

if st.session_state.ad_result:
    res = st.session_state.ad_result
    
    # ①解析情報の復旧
    analysis_raw = res.split("[DATA_START]")[0].strip()
    if "①" in analysis_raw: analysis_raw = analysis_raw[analysis_raw.find("①"):]
    cleaned_analysis = re.split(r'\n\s*(\[DATA_START\])', analysis_raw)[0].strip()
    
    # CSVパース
    df_all = None
    match_csv = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match_csv:
        csv_raw = match_csv.group(1).strip()
        parsed_data = []
        for line in csv_raw.splitlines():
            # カンマ区切りの堅牢な分割
            parts = re.findall(r'([^,"]+|"[^"]*")+', line)
            parts = [p.strip().strip('"') for p in parts]
            if len(parts) >= 2:
                while len(parts) < 7: parts.append("")
                parsed_data.append(parts[:7])
        df_all = pd.DataFrame(parsed_data, columns=["Type", "Content", "Details", "Other1", "Other2", "Status", "Hint"]).applymap(clean_text)

    # 表示
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["① 解析", "② 見出し(15)", "③ 説明文(4)", "④ キーワード(20)", "⑤ スニペット", "⑥ コールアウト"])
    with tab1: st.markdown(f'<div class="report-box">{apply_decoration(cleaned_analysis)}</div>', unsafe_allow_html=True)
    with tab2: flexible_display(df_all, "Headline|見出し", "② 広告見出し15案")
    with tab3: flexible_display(df_all, "Description|説明文", "③ 広告説明文4案")
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個・マッチタイプ別）"), unsafe_allow_html=True)
        if df_all is not None:
            sub = df_all[df_all['Type'].astype(str).str.contains("Keyword|キーワード", case=False, na=False)].copy()
            for idx, row in sub.iterrows():
                h = str(row['Hint']) + str(row['Other1'])
                if "ターゲット" in str(row['Details']) or not row['Details']:
                    sub.at[idx, 'Details'] = "部分一致" if "部分" in h else "フレーズ一致" if "フレーズ" in h else "完全一致" if "完全" in h else "部分一致"
            st.table(sub[["Content", "Details", "Other1"]].rename(columns={"Content": "キーワード", "Details": "マッチタイプ", "Other1": "入札戦略・理由"}))
    with tab5: flexible_display(df_all, "Snippet|スニペット|構造化", "⑤ 構造化スニペット", is_asset=True)
    with tab6: flexible_display(df_all, "Callout|コールアウト", "⑥ コールアウトアセット", is_asset=True)
