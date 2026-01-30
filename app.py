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
    
    /* ポップオーバー（詳細ボタン）のラベル文字の視認性向上 */
    div[data-testid="stPopover"] button p {
        color: #000000 !important;
    }
    
    /* ポップオーバーの中身も黒に指定 */
    div[data-testid="stPopoverBody"] p, 
    div[data-testid="stPopoverBody"] span, 
    div[data-testid="stPopoverBody"] div { 
        color: #000000 !important; 
    }
    
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
        st.info("データの解析準備ができていません。")
        return
    
    mask = df['Type'].astype(str).str.contains(filter_keywords, case=False, na=False, regex=True) | \
           df['Content'].astype(str).str.contains(filter_keywords, case=False, na=False, regex=True)
    sub_df = df[mask].copy()
    
    if exclude_keywords:
        exclude_mask = sub_df['Type'].astype(str).str.contains(exclude_keywords, case=False, na=False, regex=True)
        sub_df = sub_df[~exclude_mask]

    if sub_df.empty:
        st.write("（このセクションの具体的案がAIから出力されませんでした。）")
        return
    
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content = clean_text(row.get('Content'))
        details = clean_text(row.get('Details'))
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
        あなたは日本最高峰の広告コンサルタントです。LPを分析し、以下のノルマを遵守してプランを作成してください。

        【出力構成】
        1. サイト分析（①強み ②課題 ③改善案）のみを記述。
        2. その後 [DATA_START] と [DATA_END] で囲んでCSVを出力。
        
        【個数ノルマ】
        - Headline (見出し): 15個。
        - Description (説明文): 4個。
        - Keyword (キーワード): 20個。
        - Snippet (構造化スニペット): 3種類以上。
        - Callout (コールアウト): 8個以上。
        
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
        with st.spinner("🚀 解析中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

# --- 6. 結果表示・パース ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    
    # --- 解析文のクレンジング (①強みから開始) ---
    analysis_raw = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    
    # 前口上を削除
    if "①" in analysis_raw:
        analysis_raw = analysis_raw[analysis_raw.find("①"):]
    
    # 末尾の不要なヘッダーや区切り線を削除
    cleaned_analysis = re.split(r'---|\n#+ \d\.|2\..*?\n', analysis_raw)[0].strip()
    
    df_all = None
    match_csv = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match_csv:
        csv_raw = match_csv.group(1).strip()
        csv_raw = re.sub(r"```[a-z]*", "", csv_raw).replace("```", "").strip()
        
        parsed_data = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = line.split(",")
                if len(cols) > 7:
                    fixed_row = [cols[0], cols[1], " / ".join(cols[2:]), "", "", "", ""]
                    parsed_data.append(fixed_row[:7])
                else:
                    while len(cols) < 7: cols.append("")
                    parsed_data.append(cols[:7])
        
        if parsed_data:
            df_all = pd.DataFrame(parsed_data, columns=["Type", "Content", "Details", "Other1", "Other2", "Status", "Hint"]).applymap(clean_text)

    # --- Excelダウンロード ---
    if df_all is not None:
        try:
            excel_io = io.BytesIO()
            with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
                pd.DataFrame([["① 解析結果", cleaned_analysis]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_解析")
                maps = [("Headline|見出し", "2_見出し(15案)"), ("Description|説明文", "3_説明文(4案)"), ("Keyword|キーワード", "4_キーワード(20案)"), ("Snippet|スニペット", "5_構造化スニペット"), ("Callout|コールアウト", "6_コールアウト")]
                for k, s_name in maps:
                    sub_ex = df_all[df_all['Type'].astype(str).str.contains(k, case=False, na=False, regex=True) | 
                                    df_all['Content'].astype(str).str.contains(k, case=False, na=False, regex=True)].copy()
                    if not sub_ex.empty:
                        sub_ex.index = range(1, len(sub_ex) + 1)
                        sub_ex.to_excel(writer, index=True, index_label="No", sheet_name=s_name)
            st.download_button("📊 Excel形式でダウンロード", excel_io.getvalue(), "ad_report.xlsx")
        except: pass

    # --- タブ表示 ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["① 解析", "② 見出し(15)", "③ 説明文(4)", "④ キーワード(20)", "⑤ スニペット", "⑥ コールアウト"])
    
    with tab1: 
        st.markdown(f'<div class="report-box">{apply_decoration(cleaned_analysis)}</div>', unsafe_allow_html=True)
    with tab2: flexible_display(df_all, "Headline|見出し|LP", "② 広告文（見出し15個）")
    with tab3: flexible_display(df_all, "Description|説明文", "③ 広告文（説明文4個）")
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個）"), unsafe_allow_html=True)
        if df_all is not None:
            sub = df_all[df_all['Type'].astype(str).str.contains("Keyword|キーワード", case=False, na=False)].copy()
            # 番号を 1 からにリセット
            sub.index = range(1, len(sub) + 1)
            st.table(sub[["Content", "Details"]].rename(columns={"Content": "キーワード", "Details": "マッチタイプ/理由"}))
    with tab5: flexible_display(df_all, "Snippet|スニペット", "⑤ 構造化スニペット")
    with tab6: flexible_display(df_all, "Callout|コールアウト", "⑥ コールアウトアセット")

    with st.expander("🛠 デバッグ（生データ）"): st.code(res)
