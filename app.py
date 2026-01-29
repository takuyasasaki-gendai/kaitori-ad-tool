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
    .loss-text { color: #ff4b4b !important; font-weight: bold; text-decoration: underline; }
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

def dynamic_ad_display(df, type_keyword, label):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    if df is None or df.empty:
        st.info("データの解析に失敗しました。")
        return
    # フィルタ条件
    sub_df = df[df['Type'].astype(str).str.contains(type_keyword, na=False, case=False, regex=True)].copy()
    if sub_df.empty:
        st.write("（該当する具体的な案はありませんでした）")
        return
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        cols = st.columns([0.1, 0.7, 0.2])
        # Contentが空ならDetailsを代わりに表示する柔軟性
        main_content = clean_text(row.get('Content')) or clean_text(row.get('Details'))
        status = str(row.get('Status', '')).upper()
        
        cols[0].write(i)
        if "LOSS" in status or "改善" in status:
            cols[1].markdown(f"<span class='loss-text'>{main_content}</span>", unsafe_allow_html=True)
            with cols[2]:
                with st.popover("⚠️ 改善案"):
                    st.write(clean_text(row.get('Hint')) or clean_text(row.get('Details')) or "品質スコア向上のための調整が必要です")
        else:
            # デフォルトでWIN扱いにする
            cols[1].write(main_content)
            cols[2].write("✅ WIN")

def safe_table_display(df, type_keyword, col_mapping):
    if df is None or df.empty: return
    sub_df = df[df['Type'].astype(str).str.contains(type_keyword, na=False, case=False, regex=True)].copy()
    if sub_df.empty: return
    sub_df = sub_df.applymap(clean_text)
    sub_df.index = range(1, len(sub_df) + 1)
    # 存在するカラムだけを表示
    cols_to_show = [c for c in col_mapping.keys() if c in sub_df.columns]
    st.table(sub_df[cols_to_show].rename(columns=col_mapping))

# --- 4. スクレイピング & 生成 ---
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
        買取広告コンサルタントとして、品質スコア最大化プランを作成せよ。
        最初にサイト分析（①強み ②課題 ③改善案）を書き、その後に必ず [DATA_START] カンマ区切りCSV(Type,Content,Details,Other1,Other2,Status,Hint) [DATA_END] を出力せよ。
        CSV内では ** を使用禁止。
        内容: {site_text}
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
url_in = st.text_input("LPのURLを入力")

if st.button("生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略構築中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

# --- 6. パース & 表示 ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    main_text = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    
    df_all = None
    match = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match:
        csv_raw = match.group(1).strip()
        csv_raw = re.sub(r"```[a-z]*", "", csv_raw).replace("```", "").strip()
        
        # CSVの列不足を強制補完する堅牢なロジック
        valid_lines = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = line.split(",")
                # 7列になるまで空のカンマを追加
                while len(cols) < 7:
                    cols.append("")
                valid_lines.append(",".join(cols[:7]))
        
        if valid_lines:
            df_all = pd.read_csv(io.StringIO("\n".join(valid_lines)), on_bad_lines='skip', engine='python')
            df_all.columns = [c.strip() for c in df_all.columns]

    # Excel作成
    try:
        excel_io = io.BytesIO()
        with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
            pd.DataFrame([["解析結果", clean_text(main_text)]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_サイト解析")
            if df_all is not None:
                maps = [('見出し|LP改善|戦略','2_見出し・LP案'),('説明文','3_説明文案'),('キーワード','4_キーワード'),('アセット|コールアウト|スニペット','5_6_アセット')]
                for t, sn in maps:
                    sub = df_all[df_all['Type'].astype(str).str.contains(t, na=False, case=False, regex=True)]
                    if not sub.empty: sub.to_excel(writer, index=False, sheet_name=sn)
        st.download_button("📊 Excelダウンロード", excel_io.getvalue(), "ad_strategy.xlsx")
    except Exception as e: st.error(f"Excel作成エラー: {e}")

    t1, t2, t3 = st.tabs(["📋 ① 解析", "✍️ ②③ 広告・LP案", "🔍 ④⑤⑥ キーワード・アセット"])
    with t1: st.markdown(f'<div class="report-box">{apply_decoration(main_text)}</div>', unsafe_allow_html=True)
    with t2:
        if df_all is not None:
            # AIが「戦略」や「LP改善」として出したものも見出しタブに表示
            dynamic_ad_display(df_all, '見出し|LP改善|戦略', "② 広告・LP改善案")
            st.divider()
            dynamic_ad_display(df_all, '説明文', "③ 説明文案")
    with t3:
        if df_all is not None:
            safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'詳細','Other1':'推定CPC','Other2':'優先度'})
            st.divider()
            # アセットもContentが空の場合を考慮して表示
            dynamic_ad_display(df_all, 'アセット|コールアウト|スニペット', "⑤⑥ アセット（コールアウト等）")

    with st.expander("🛠 生データ確認"): st.code(res)
