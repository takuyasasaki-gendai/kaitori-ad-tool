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
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except: pass

install_playwright_binary()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if "ad_result" not in st.session_state:
    st.session_state.ad_result = None

# --- 2. CSSデザイン (Logic Box含む) ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    div[data-testid="stPopover"] button p { color: #000000 !important; }
    div[data-testid="stPopoverBody"] p, div[data-testid="stPopoverBody"] span, div[data-testid="stPopoverBody"] div { color: #000000 !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; height: 3.5em; background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold; margin-top: 20px; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #D4AF37; color: white !important; border: none; font-weight: bold; }
    /* ロジックボックスのスタイル */
    .logic-box { padding: 25px; border-radius: 10px; background-color: #1e1e1e; border: 1px solid #D4AF37; margin-bottom: 25px; line-height: 1.6; }
    .logic-table { width: 100%; border-collapse: collapse; margin-top: 10px; color: #ffffff; }
    .logic-table th, .logic-table td { border: 1px solid #444; padding: 10px; text-align: left; font-size: 0.9em; }
    .logic-table th { background-color: #333; color: #D4AF37; }
    /* その他のスタイル */
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

# --- 4. メインヘッダー & 思考プロセス解説 (復活) ---
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
    if df is None or df.empty:
        st.write("（解析データがありません。再生成してください。）")
        return
    mask = df['Type'].astype(str).str.contains(filter_keywords, case=False, na=False, regex=True)
    sub_df = df[mask].copy()
    if sub_df.empty:
        st.write("（該当する広告案がありません）")
        return
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content, details = clean_text(row.get('Content')), clean_text(row.get('Details'))
        cols = st.columns([0.1, 0.7, 0.2])
        cols[0].write(i)
        cols[1].write(content)
        display_details = details if "文字以内" not in details else ""
        if is_asset or (display_details and not any(x in display_details for x in ["見出し", "説明文"])):
            with cols[2]:
                with st.popover("💡 詳細"): st.write(display_details if display_details else "戦略的に最適化済み")
        else: cols[2].write("✅ WIN")

# --- 6. スクレイピング ---
async def fetch_content(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
    except:
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
        Google広告プランを作成してください。業界問わずLPの内容を分析します。
        
        【1. サイト解析】①強み ②課題 ③改善案 を詳しく。
        【2. データセクション】[DATA_START] カラム(Type,Content,Details,Other1,Other2,Status,Hint)のCSV [DATA_END]
        
        Headline: 15個, Description: 4個, Keyword: 20個(マッチタイプと理由), Snippet: 3個, Callout: 10個。
        
        サイト内容: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AIエラー: {str(e)}"

# --- 7. 入力エリア ---
input_mode = st.radio("入力方法", ["URL読み込み", "直接入力"])
raw_text = ""

if input_mode == "URL読み込み":
    url_in = st.text_input("LPのURL")
    if st.button("生成開始"):
        if url_in:
            with st.spinner("🚀 LPを解析中..."):
                raw_text = asyncio.run(fetch_content(url_in))
                if not raw_text: st.error("読み込み失敗。直接入力をお試しください。")
else:
    raw_text = st.text_area("LPテキスト貼り付け", height=200)
    if st.button("生成開始"):
        if not raw_text: st.error("テキストを入力してください")

# --- 8. 表示 & 出力ロジック ---
if raw_text:
    with st.spinner("🚀 戦略プランを構築中..."):
        st.session_state.ad_result = generate_ad_plan(raw_text, api_key)
        st.balloons()

if st.session_state.ad_result:
    res = st.session_state.ad_result
    
    # ① 解析情報の抽出
    analysis_raw = res.split("[DATA_START]")[0].strip()
    if "①" in analysis_raw: analysis_raw = analysis_raw[analysis_raw.find("①"):]
    cleaned_analysis = re.split(r'(\[DATA_START\])', analysis_raw)[0].strip()
    
    # CSVパース (堅牢版)
    df_all = None
    match_csv = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match_csv:
        csv_block = re.sub(r"```[a-z]*", "", match_csv.group(1)).replace("```", "").strip()
        parsed_rows = []
        for line in csv_block.splitlines():
            parts = re.findall(r'([^,"]+|"[^"]*")+', line)
            parts = [p.strip().strip('"') for p in parts]
            if len(parts) >= 2:
                while len(parts) < 7: parts.append("")
                parsed_rows.append(parts[:7])
        if parsed_rows:
            df_all = pd.DataFrame(parsed_rows, columns=["Type", "Content", "Details", "Other1", "Other2", "Status", "Hint"]).applymap(clean_text)

    # Excelダウンロード機能 (復活)
    if df_all is not None:
        try:
            excel_io = io.BytesIO()
            with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
                pd.DataFrame([["① 解析結果", cleaned_analysis]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_解析")
                maps = [("Headline", "2_見出し"), ("Description", "3_説明文"), ("Keyword", "4_キーワード"), ("Snippet", "5_スニペット"), ("Callout", "6_コールアウト")]
                for key, s_name in maps:
                    sub = df_all[df_all['Type'].astype(str).str.contains(key, case=False, na=False)].copy()
                    if not sub.empty:
                        sub.index = range(1, len(sub) + 1)
                        sub.to_excel(writer, index=True, index_label="No", sheet_name=s_name)
            
            st.download_button(
                label="📊 完成したプランをExcelでダウンロード",
                data=excel_io.getvalue(),
                file_name="google_ad_plan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except: pass

    # タブ表示
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["① 解析", "② 見出し(15)", "③ 説明文(4)", "④ キーワード(20)", "⑤ スニペット", "⑥ コールアウト"])
    with tab1: st.markdown(f'<div class="report-box">{apply_decoration(cleaned_analysis)}</div>', unsafe_allow_html=True)
    with tab2: flexible_display(df_all, "Headline|見出し", "② 広告見出し15案")
    with tab3: flexible_display(df_all, "Description|説明文", "③ 広告説明文4案")
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個）"), unsafe_allow_html=True)
        if df_all is not None:
            sub = df_all[df_all['Type'].astype(str).str.contains("Keyword|キーワード", case=False, na=False)].copy()
            for idx, row in sub.iterrows():
                h = str(row['Hint']) + str(row['Other1'])
                if "ターゲット" in str(row['Details']) or not row['Details']:
                    sub.at[idx, 'Details'] = "部分一致" if "部分" in h else "フレーズ一致" if "フレーズ" in h else "完全一致" if "完全" in h else "部分一致"
            st.table(sub[["Content", "Details", "Other1"]].rename(columns={"Content": "キーワード", "Details": "マッチタイプ", "Other1": "入札戦略・理由"}))
    with tab5: flexible_display(df_all, "Snippet|スニペット|構造化", "⑤ 構造化スニペット", is_asset=True)
    with tab6: flexible_display(df_all, "Callout|コールアウト", "⑥ コールアウトアセット", is_asset=True)
