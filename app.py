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

# APIキーの取得
api_key = st.secrets.get("GEMINI_API_KEY")

@st.cache_resource
def install_playwright_binary():
    """Cloud環境でブラウザ本体を確実にインストール"""
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        print(f"Playwright installation skipped: {e}")

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

# --- 3. パスワード認証 (サイドバー) ---
with st.sidebar:
    st.title("Admin Access")
    if st.text_input("Password", type="password") != "password":
        st.warning("正しいパスワードを入力してください")
        st.stop()
    st.success("認証済み")

# --- 4. 生成ロジックの解説 ---
st.title("Google広告プラン自動生成ツール")
st.markdown("""
<div class="logic-box">
<h3>⚙️ セクション別・生成ロジックの解説</h3>
当ツールは、LP解析に基づき、Google広告の「品質スコア」を最大化させるため、各項目を以下のロジックで生成しています。
<table class="logic-table">
    <tr><th>セクション</th><th>生成ロジック（AIの思考プロセス）</th></tr>
    <tr><td><b>② 見出し(15案)</b></td><td>解析したUSPから検索意図に刺さるコピーを構成します。</td></tr>
    <tr><td><b>③ 説明文(4案)</b></td><td>LPの文脈を維持しつつ、ユーザーの不安を解消する詳細情報を文章化します。</td></tr>
    <tr><td><b>④ キーワード(20案)</b></td><td>ニーズと目的に合わせ、マッチタイプ別に戦略的選定を行います。</td></tr>
    <tr><td><b>⑤ スニペット</b></td><td>商品カテゴリを「ヘッダー」ごとに分類し、目的との一致度を高めます。</td></tr>
    <tr><td><b>⑥ コールアウト</b></td><td>LP内の重要な利点を短文で抽出し、クリック率を向上させます。</td></tr>
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
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content, details = clean_text(row.get('Content')), clean_text(row.get('Details'))
        cols = st.columns([0.1, 0.7, 0.2])
        cols[0].write(i)
        cols[1].write(content)
        
        # 「〇文字以内」などの不要な注釈を除去し、意味のある詳細のみ表示
        display_details = details if "文字以内" not in details else ""
        
        if is_asset or (display_details and not any(x in display_details for x in ["見出し", "説明文"])):
            with cols[2]:
                with st.popover("💡 詳細"):
                    st.write(display_details if display_details else "戦略的最適化済み")
        else:
            cols[2].write("✅ WIN")

# --- 6. ハイブリッド・スクレイピング ---
async def fetch_and_clean_content(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=45000)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
    except:
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
        except: return "解析エラー"
    for s in soup(["script", "style", "nav", "footer"]): s.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:4000]

def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"""
        あなたは日本最高峰の広告コンサルタントです。LPを分析し以下を厳守してください。
        
        【重要：⑤スニペット・⑥コールアウトの出力ルール】
        - ⑤Snippet: Contentに「値（カンマ区切り）」、Detailsに「ヘッダーの種類（種類/ブランド/サービス等）」、Other1に「戦略的理由」を記述。
        - ⑥Callout: Contentに「テキスト」、Detailsに「その訴求を選ぶ具体的メリット」、Other1に「理由」を記述。
        - 「〇文字以内」という注釈はDetailsには絶対に書かないこと。具体的・戦略的な内容を書くこと。

        【その他】
        - ④Keyword: 20個。Detailsにマッチタイプ、Other1に理由。
        - ②Headline: 15個。③Description: 4個。
        
        [DATA_START] と [DATA_END] でCSVを出力。
        CSVカラム: Type,Content,Details,Other1,Other2,Status,Hint
        サイト内容: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AIエラー: {str(e)}"

# --- 7. メイン実行 ---
url_in = st.text_input("LPのURLを入力してください")
if st.button("生成スタート"):
    if url_in and api_key:
        with st.spinner("🚀 戦略構築中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            if "エラー" not in cleaned:
                st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
                st.balloons()
            else: st.error(cleaned)

# --- 8. 表示 ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    analysis_raw = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    if "①" in analysis_raw: analysis_raw = analysis_raw[analysis_raw.find("①"):]
    cleaned_analysis = re.split(r'\n\s*(-{3,}|#{1,4}\s*[23]\.)', analysis_raw)[0].strip()
    
    df_all = None
    match_csv = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match_csv:
        csv_raw = match_csv.group(1).strip()
        parsed_data = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = [c.strip() for c in line.split(",")]
                while len(cols) < 7: cols.append("")
                parsed_data.append(cols[:7])
        df_all = pd.DataFrame(parsed_data, columns=["Type", "Content", "Details", "Other1", "Other2", "Status", "Hint"]).applymap(clean_text)

    # 表示セクション
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
    with tab5: flexible_display(df_all, "Snippet|スニペット", "⑤ 構造化スニペット", is_asset=True)
    with tab6: flexible_display(df_all, "Callout|コールアウト", "⑥ コールアウトアセット", is_asset=True)
