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
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; height: 3.5em; background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #D4AF37; color: white !important; border: none; font-weight: bold; }
    .report-box { padding: 20px; border-radius: 0px; background-color: transparent; margin-bottom: 25px; line-height: 1.8; border: 1px solid #333; }
    .section-heading { color: #ffffff !important; font-weight: bold !important; font-size: 1.25em !important; margin-top: 35px; border-left: 5px solid #D4AF37; padding-left: 15px; display: block; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 補助関数 ---
def clean_text(text):
    if not text or pd.isna(text): return ""
    return str(text).replace("**", "").replace("###", "").replace("`", "").replace('"', '').strip()

def apply_decoration(text):
    if not text: return ""
    text = clean_text(text)
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="section-heading">\1\2</span>', text)
    text = text.replace("\n", "<br>")
    return text

def flexible_display(df, filter_keywords, label, exclude_keywords=None):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    if df is None or df.empty:
        st.info("データの生成待ちです。")
        return
    
    # TypeまたはContentに含まれるキーワードでフィルタ
    mask = df.iloc[:, 0:3].apply(lambda row: row.astype(str).str.contains(filter_keywords, case=False, na=False).any(), axis=1)
    sub_df = df[mask].copy()
    
    if exclude_keywords:
        exclude_mask = sub_df.iloc[:, 0:3].apply(lambda row: row.astype(str).str.contains(exclude_keywords, case=False, na=False).any(), axis=1)
        sub_df = sub_df[~exclude_mask]

    if sub_df.empty:
        st.write("（具体的案が出力されませんでした。生成スタートをもう一度押してください。）")
        return
    
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content = clean_text(row.iloc[1])
        details = clean_text(row.iloc[2])
        cols = st.columns([0.1, 0.7, 0.2])
        cols[0].write(i)
        cols[1].write(content)
        if details:
            with cols[2]:
                with st.popover("💡 詳細"):
                    st.write(details)
        else:
            cols[2].write("✅ WIN")

# --- 4. 生成ロジック ---
async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            soup = BeautifulSoup(await page.content(), "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header"]): s.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:4000]
        except: return "解析エラー"
        finally: await browser.close()

def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = f"""
        あなたは日本最高峰のGoogle広告運用者です。提供されたLPを分析し、以下のノルマを【絶対】に守ってプランを作成してください。

        【重要ノルマ】
        1. サイト分析（①強み ②課題 ③改善案）をそれぞれ5項目以上詳しく記述。
        2. [DATA_START] と [DATA_END] で囲んでCSVを出力。
        3. 下記個数を【必ず】出力してください。不足は許されません：
           - 見出し: 【必ず15個】。具体的で魅力的な訴求を書くこと。
           - 説明文: 【必ず4個】。
           - キーワード: 【必ず20個】。
           - 構造化スニペット: 【必ず3種類】。
           - コールアウト: 【必ず8個】。
        
        CSVカラム: Type,Content,Details,Other1,Other2,Status,Hint

        LP内容: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"生成エラー: {str(e)}"

# --- 5. メインUI ---
st.set_page_config(page_title="広告ランク最適化ツール", layout="wide")
api_key = st.secrets.get("GEMINI_API_KEY")

with st.sidebar:
    st.title("Settings")
    if st.text_input("Password", type="password") != "password": st.stop()

st.title("広告プラン自動生成ツール")
url_in = st.text_input("LPのURLを入力してください")

if st.button("生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略・広告文・キーワード(15個/20個)を生成中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

# --- 6. 結果表示・パース ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    main_text = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    
    df_all = None
    match = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match:
        csv_raw = match.group(1).strip()
        csv_raw = re.sub(r"```[a-z]*", "", csv_raw).replace("```", "").strip()
        
        lines = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = line.split(",")
                while len(cols) < 7: cols.append("")
                lines.append(",".join(cols[:7]))
        
        if lines:
            df_all = pd.read_csv(io.StringIO("\n".join(lines)), on_bad_lines='skip', engine='python').applymap(clean_text)

    # Excel作成
    try:
        excel_io = io.BytesIO()
        with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
            pd.DataFrame([["サイト分析結果", clean_text(main_text)]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_サイト解析")
            if df_all is not None:
                sheet_maps = [('見出し|LP', '2_広告見出し(15案)'), ('説明文', '3_説明文(4案)'), ('キーワード', '4_キーワード(20案)'), ('スニペット', '5_構造化スニペット'), ('コールアウト', '6_コールアウト')]
                for t_key, s_name in sheet_maps:
                    mask = df_all.iloc[:, 0:2].apply(lambda row: row.astype(str).str.contains(t_key, case=False, na=False).any(), axis=1)
                    sub = df_all[mask]
                    if not sub.empty: sub.to_excel(writer, index=False, sheet_name=s_name)
        st.download_button("📊 Excel形式でダウンロード", excel_io.getvalue(), "ad_plan_full.xlsx")
    except Exception as e: st.error(f"Excel作成エラー: {e}")

    # --- ①〜⑥の順番でタブを表示 ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "① 解析", "② 見出し(15)", "③ 説明文(4)", "④ キーワード(20)", "⑤ スニペット", "⑥ コールアウト"
    ])
    
    with tab1:
        st.markdown(f'<div class="report-box">{apply_decoration(main_text)}</div>', unsafe_allow_html=True)
    
    with tab2:
        flexible_display(df_all, "見出し|LP", "② 広告文（見出し15個）")
        
    with tab3:
        flexible_display(df_all, "説明文", "③ 広告文（説明文4個）")
        
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個）"), unsafe_allow_html=True)
        if df_all is not None:
            mask = df_all.iloc[:, 0].astype(str).str.contains("キーワード", na=False)
            sub = df_all[mask]
            st.table(sub.iloc[:, [1, 2]].rename(columns={sub.columns[1]: "キーワード", sub.columns[2]: "詳細"}))
            
    with tab5:
        flexible_display(df_all, "スニペット", "⑤ 構造化スニペット")
        
    with tab6:
        flexible_display(df_all, "コールアウト", "⑥ コールアウトアセット")

    with st.expander("🛠 デバッグ（生データ）"):
        st.code(res)
