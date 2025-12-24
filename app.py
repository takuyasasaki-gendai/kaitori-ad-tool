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

# --- 2. CSSデザイン (指示通りのUIを維持) ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    
    /* Excelボタン: 背景ゴールド・テキスト黒 */
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    /* 生成ボタン: 背景ゴールド・テキスト白 */
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }
    /* メインタイトル黄色背景: テキスト黒 */
    .plan-title {
        background-color: #ffff00; font-weight: bold; padding: 6px 12px;
        font-size: 1.3em; display: inline-block; border-radius: 2px;
        margin-bottom: 20px; color: #000000 !important;
    }
    /* ①〜⑥見出し: 白背景・黒文字 */
    .white-block-heading {
        background-color: #ffffff; color: #000000 !important;
        font-weight: bold; font-size: 1.15em; margin-top: 25px;
        margin-bottom: 15px; padding: 5px 15px; display: inline-block; border-radius: 2px;
    }
    .white-block-heading * { color: #000000 !important; }
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }
    .report-box {
        padding: 30px; border-radius: 10px; background-color: #262626;
        box-shadow: 0 4px 15px rgba(0,0,0,0.6); margin-bottom: 25px; line-height: 1.8;
    }
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    button[data-baseweb="tab"] p { color: #888 !important; }
    button[aria-selected="true"] p { color: #D4AF37 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 装飾適用関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="white-block-heading">\1\2</span>', text)
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
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
        target_model = ""
        for m_name in ["models/gemini-1.5-flash", "models/gemini-pro"]:
            if m_name in available_models:
                target_model = m_name
                break
        if not target_model: target_model = available_models[0]
        
        model = genai.GenerativeModel(target_model)
        prompt = f"""
        あなたは買取広告コンサルタントです。以下のサイトを分析し、Google検索広告プランを作成してください。
        
        【構成】
        冒頭：Google検索広告プラン：(サイト名)
        内容：①サイト解析結果、②広告文（DL）、③説明文（DL）、④キーワード（DL）、⑤構造化スニペット、⑥コールアウトアセット
        
        【重要】
        回答の最後に、以下のCSVデータを必ず含めてください。データの欠落は許されません。
        [DATA_START]
        Type,Content,Details,Other1,Other2
        見出し,(ここに15個の見出しを書く),,,
        説明文,(ここに4個の説明文を書く),,,
        キーワード,(キーワード),(マッチタイプ),(CPC),(優先度)
        スニペット,(種類),(値),,
        コールアウト,(内容),,,
        [DATA_END]
        
        解析サイト：{site_text}
        """
        return model.generate_content(prompt).text
    except Exception as e: return f"AI生成エラー: {str(e)}"

def create_excel_safe(text):
    """Excel作成時にシートが空にならないよう保護する関数"""
    try:
        if "[DATA_START]" not in text:
            return None
        
        raw = text.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
        df = pd.read_csv(io.StringIO(raw))
        
        # もしデータが読み込めても空なら中断
        if df.empty:
            return None

        out = io.BytesIO()
        # openpyxlで空のシートが作られないよう、各カテゴリが存在するか確認しながら書き込む
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            written_sheets = 0
            
            for sheet_name, type_filter in [('②広告文', '見出し'), ('③説明文', '説明文'), ('④キーワード', 'キーワード')]:
                sub_df = df[df['Type'] == type_filter]
                if not sub_df.empty:
                    sub_df.to_excel(writer, index=False, sheet_name=sheet_name)
                    written_sheets += 1
            
            # アセット用（スニペット・コールアウト）
            asset_df = df[df['Type'].isin(['スニペット', 'コールアウト'])]
            if not asset_df.empty:
                asset_df.to_excel(writer, index=False, sheet_name='⑤⑥アセット')
                written_sheets += 1
            
            # 【IndexError対策】1枚もシートが書かれなかった場合、ダミーシートを作成
            if written_sheets == 0:
                pd.DataFrame({"Message": ["解析データが見つかりませんでした。再度生成してください。"]}).to_excel(writer, sheet_name="注意")
        
        return out.getvalue()
    except:
        return None

# --- 5. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3524/3524659.png", width=60)
    st.title("Admin Menu")
    pwd = st.text_input("アクセスパスワード", type="password")
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

if st.session_state.ad_result:
    main_text = st.session_state.ad_result.split("[DATA_START]")[0]
    
    # Excel生成の実行（安全版）
    excel_bin = create_excel_safe(st.session_state.ad_result)
    
    if excel_bin:
        st.download_button("📊 Excel形式でダウンロード", data=excel_bin, file_name="ad_strategy.xlsx")
    else:
        st.warning("⚠️ Excel用データの抽出に失敗しました。解析結果は以下の画面でご確認ください。")

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

    # 表データ表示用のパース
    df_for_table = None
    if "[DATA_START]" in st.session_state.ad_result:
        try:
            raw_csv = st.session_state.ad_result.split("[DATA_START]")[1].split("[DATA_END]")[0].strip()
            df_for_table = pd.read_csv(io.StringIO(raw_csv))
        except: pass

    with tab1:
        content1 = main_text.split("②")[0] if "②" in main_text else main_text
        st.markdown(f'<div class="report-box">{apply_decoration(content1)}</div>', unsafe_allow_html=True)
    
    with tab2:
        content2 = get_section_text(main_text, "②", "④")
        st.markdown(f'<div class="report-box">{apply_decoration(content2)}</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration("④キーワード（一覧）"), unsafe_allow_html=True)
        if df_for_table is not None:
            kw_df = df_for_table[df_for_table['Type'] == 'キーワード'].copy()
            if not kw_df.empty:
                kw_df = kw_df.rename(columns={'Content': 'キーワード', 'Details': 'マッチタイプ', 'Other1': '推定CPC', 'Other2': '優先度'})
                st.table(kw_df[['キーワード', 'マッチタイプ', '推定CPC', '優先度']])
        
        st.markdown(apply_decoration("⑤構造化スニペット（一覧）"), unsafe_allow_html=True)
        if df_for_table is not None:
            snip_df = df_for_table[df_for_table['Type'] == 'スニペット'].copy()
            if not snip_df.empty:
                snip_df = snip_df.rename(columns={'Content': '種類', 'Details': '値'})
                st.table(snip_df[['種類', '値']])

        content3_rest = get_section_text(main_text, "⑥")
        st.markdown(apply_decoration(content3_rest), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
