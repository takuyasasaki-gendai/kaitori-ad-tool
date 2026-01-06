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
def generate_ad_plan(site_text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        
        prompt = f"""
        あなたは買取広告コンサルタントです。以下のサイトを分析し、Google広告の「品質スコア」と「広告ランク」を最大化するプランを作成してください。

        【分析対象】
        {site_text}

        【指示】
        1. キーワードを見出し1に含め、LPとの整合性を高めること。
        2. ユーザーの検索意図（早く売りたい、高く売りたい等）に合致する訴求を作成せよ。
        3. [STATUS]判定：具体的数値や強力なベネフィットがあるなら「WIN」、一般的すぎる表現なら「LOSS」とせよ。

        【構成】
        最初にサイト解析（強み・課題・改善案）を書き、その後に必ず[DATA_START]と[DATA_END]で囲んでCSVデータを出力してください。
        コードブロック(```)は使用禁止です。

        [DATA_START]
        Type,Content,Details,Other1,Other2,Status,Hint
        見出し,サンプルテキスト,,,WIN,
        説明文,サンプルテキスト,,,WIN,
        キーワード,単語,マッチ,150円,高,WIN,
        スニペット,種類,値,,,WIN,
        コールアウト,テキスト,,,,WIN,
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

# --- 結果表示（ここを差し替え） ---
if st.session_state.ad_result:
    res_text = st.session_state.ad_result
    df_all = None
    
    # 1. 解析テキストの抽出
    main_text = res_text.split("[DATA_START]")[0].strip() if "[DATA_START]" in res_text else res_text

    # 2. データのパース（正規表現で安全に抽出）
    pattern = re.compile(r"\[DATA_START\](.*?)\[DATA_END\]", re.DOTALL | re.IGNORECASE)
    match = pattern.search(res_text)
    if match:
        try:
            raw_csv = match.group(1).strip().replace("```csv", "").replace("```", "").strip()
            df_all = pd.read_csv(io.StringIO(raw_csv), on_bad_lines='skip')
            df_all.columns = [c.strip() for c in df_all.columns]
        except:
            st.warning("一部のデータ形式が正しく読み込めませんでした。")

# 3. Excelファイルの作成（シート名を標準文字に変更して確実性を高める）
    try:
        out = io.BytesIO()
        # サイト分析のテキストを事前に処理
        # HTMLタグを除去し、プレーンテキストにする
        clean_analysis_text = main_text.replace("<br>", "\n").replace("<b>", "").replace("</b>", "").strip()
        
        if not clean_analysis_text:
            clean_analysis_text = "解析結果の取得に失敗しました。"

        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            # --- 1. サイト解析シート (シート名から特殊文字 ① を除去) ---
            df_analysis = pd.DataFrame([["分析結果全文", clean_analysis_text]], columns=["項目", "内容"])
            df_analysis.to_excel(writer, index=False, sheet_name='1_サイト解析')
            
            # 列の幅を調整（見やすくするため）
            ws_analysis = writer.sheets['1_サイト解析']
            ws_analysis.column_dimensions['A'].width = 15
            ws_analysis.column_dimensions['B'].width = 100

            # --- 2. 広告文・キーワード・アセットシート ---
            if df_all is not None:
                # ② 広告文（見出し）
                df_h = df_all[df_all['Type'].astype(str).str.contains('見出し', na=False, case=False)].copy()
                if not df_h.empty:
                    df_h.to_excel(writer, index=False, sheet_name='2_広告文案_見出し')
                
                # ③ 説明文
                df_d = df_all[df_all['Type'].astype(str).str.contains('説明文', na=False, case=False)].copy()
                if not df_d.empty:
                    df_d.to_excel(writer, index=False, sheet_name='3_説明文案')
                
                # ④ キーワード
                df_k = df_all[df_all['Type'].astype(str).str.contains('キーワード', na=False, case=False)].copy()
                if not df_k.empty:
                    df_k.to_excel(writer, index=False, sheet_name='4_キーワード')
                
                # ⑤⑥ アセット（スニペット・コールアウト）
                df_a = df_all[df_all['Type'].astype(str).str.contains('スニペット|コールアウト', na=False, case=False)].copy()
                if not df_a.empty:
                    df_a.to_excel(writer, index=False, sheet_name='5_6_アセット')

        # ダウンロードボタンの表示（mimeタイプを明示）
        st.download_button(
            label="📊 解析結果(Excel)をダウンロード",
            data=out.getvalue(),
            file_name="ad_strategy_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        # 万が一エラーが出た場合に原因を表示
        st.error(f"Excel作成エラー: {e}")

    # 4. タブ表示
    tab1, tab2, tab3 = st.tabs(["📋 ① サイト解析", "✍️ ②③ 広告文案", "🔍 ④⑤⑥ アセット"])

    with tab1:
        st.markdown('<div class="report-box">', unsafe_allow_html=True)
        st.markdown(apply_decoration(main_text), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        if df_all is not None:
            dynamic_ad_display(df_all, '見出し', "②広告文案（見出し）")
            st.divider()
            dynamic_ad_display(df_all, '説明文', "③説明文案")
        else:
            st.info("広告文データが生成されませんでした。")

    with tab3:
        if df_all is not None:
            st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
            safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'})
            st.divider()
            dynamic_ad_display(df_all, 'コールアウト', "⑥コールアウトアセット")

    with st.expander("🛠 AIの生出力を確認"):
        st.code(res_text)



