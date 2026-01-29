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

def section_display(df, section_id, label):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    if df is None or df.empty:
        st.info("データの生成待ちです。")
        return
    # Section IDでフィルタリング
    sub_df = df[df['Section'].astype(str) == str(section_id)].copy()
    if sub_df.empty:
        st.write("（このセクションの具体的案が出力されませんでした。再生成をお試しください。）")
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

# --- 4. 生成ロジック（個数と実戦的コピーを強制） ---
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
        # 利用可能な最新モデルを選択
        model = genai.GenerativeModel("gemini-1.5-flash") # 安定版を使用
        
        prompt = f"""
        あなたは日本最高峰のGoogle広告運用コンサルタントです。提供されたLPを分析し、品質スコア10/10を獲得するための究極の広告プランを作成してください。

        【重要：出力ノルマとルール】
        1. 最初に詳細なサイト解析（①強み ②課題 ③改善案）を記述してください。
        2. 次に必ず [DATA_START] と [DATA_END] で囲んで以下の4列CSVデータを出力してください。
        3. CSVのカラムは (Section, Type, Content, Details) です。
        4. 各セクションの個数を必ず守ってください：
           - Section 2 (見出し): 必ず15個。具体的で魅力的な訴求を書くこと（「見出し1案」などは禁止）。
           - Section 3 (説明文): 必ず4個。LPの強みを盛り込み、90文字ギリギリまで使うこと。
           - Section 4 (キーワード): 必ず20個。
           - Section 5 (構造化スニペット): 必ず3種類以上。
           - Section 6 (コールアウト): 必ず8個以上。

        【CSVフォーマット例】
        Section,Type,Content,Details
        2,見出し,ロレックス買取実績地域No1,54年の歴史がある質屋の信頼
        ...

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
        with st.spinner("🚀 戦略・広告文・キーワードを抽出中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

# --- 6. 結果表示・ダウンロード ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    main_text = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    
    df_all = None
    match = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match:
        csv_raw = match.group(1).strip()
        csv_raw = re.sub(r"```[a-z]*", "", csv_raw).replace("```", "").strip()
        
        # 4列に整形
        valid_lines = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = line.split(",")
                while len(cols) < 4: cols.append("")
                valid_lines.append(",".join(cols[:4]))
        
        if valid_lines:
            df_all = pd.read_csv(io.StringIO("\n".join(valid_lines)), on_bad_lines='skip', engine='python').applymap(clean_text)
            df_all.columns = ["Section", "Type", "Content", "Details"]

    # Excel作成
    try:
        excel_io = io.BytesIO()
        with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
            pd.DataFrame([["サイト分析結果", clean_text(main_text)]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_サイト解析")
            if df_all is not None:
                sheet_names = {
                    "2": "2_広告見出し(15案)",
                    "3": "3_説明文(4案)",
                    "4": "4_キーワード(20案)",
                    "5": "5_構造化スニペット",
                    "6": "6_コールアウト"
                }
                for s_id, s_name in sheet_names.items():
                    sub = df_all[df_all['Section'].astype(str) == s_id]
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
        section_display(df_all, "2", "② 広告文（見出し15個）")
        
    with tab3:
        section_display(df_all, "3", "③ 広告文（説明文4個）")
        
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個）"), unsafe_allow_html=True)
        if df_all is not None:
            sub = df_all[df_all['Section'].astype(str) == "4"]
            st.table(sub[["Content", "Details"]].rename(columns={"Content": "キーワード", "Details": "マッチタイプ/理由"}))
            
    with tab5:
        section_display(df_all, "5", "⑤ 構造化スニペット")
        
    with tab6:
        section_display(df_all, "6", "⑥ コールアウトアセット")

    with st.expander("🛠 生データ（デバッグ用）"):
        st.code(res)
