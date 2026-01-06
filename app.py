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

# --- 2. CSSデザイン ---
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #ffffff !important; }
    .stApp p, .stApp span, .stApp div, .stApp li { color: #ffffff !important; }
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    .stDownloadButton>button {
        width: 100%; border-radius: 5px; height: 3.5em;
        background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold;
    }
    .stButton>button {
        width: 100%; border-radius: 5px; height: 3em;
        background-color: #D4AF37; color: white !important; border: none; font-weight: bold;
    }
    .plan-title {
        color: #ffff00 !important; font-size: 1.5em !important; font-weight: bold !important;
        margin-bottom: 25px !important; display: block !important; border-bottom: 2px solid #ffff00; padding-bottom: 10px;
    }
    .section-heading {
        color: #ffffff !important; font-weight: bold !important; font-size: 1.25em !important;
        margin-top: 35px !important; margin-bottom: 15px !important; display: block !important; border-left: 5px solid #D4AF37; padding-left: 15px;
    }
    .underlined-keyword { text-decoration: underline; font-weight: bold; color: #ffd700 !important; }
    .report-box { padding: 20px; border-radius: 0px; background-color: transparent; margin-bottom: 25px; line-height: 1.8; }
    .loss-text { color: #ff4b4b !important; font-weight: bold; text-decoration: underline; }
    div[data-testid="stTable"] table { background-color: #1e1e1e !important; color: white !important; border: 1px solid #444; width: 100%; }
    th { color: #D4AF37 !important; background-color: #333 !important; }
    td { color: #ffffff !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 補助関数 ---
def apply_decoration(text):
    if not text: return ""
    text = text.replace("#", "")
    text = re.sub(r'(①|②|③|④|⑤|⑥)([^\n<]+)', r'<span class="section-heading">\1\2</span>', text)
    for kw in ["強み", "課題", "改善案"]:
        text = text.replace(kw, f"<span class='underlined-keyword'>{kw}</span>")
    text = re.sub(r'(Google検索広告プラン：[^\n<]+)', r'<span class="plan-title">\1</span>', text)
    text = text.replace("\n", "<br>")
    return text

def dynamic_ad_display(df, type_name, label):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    sub_df = df[df['Type'].astype(str).str.contains(type_name, na=False, case=False)].copy()
    if sub_df.empty:
        st.info(f"{type_name}のデータはありません。")
        return
    
    for i, (idx, row) in enumerate(sub_df.iterrows(), 1):
        cols = st.columns([0.1, 0.7, 0.2])
        is_loss = str(row.get('Status', '')).upper() == 'LOSS'
        
        # 内容のクリーニング（** を除去）
        content = str(row['Content']).replace("**", "").strip()
        
        cols[0].write(i)
        if is_loss:
            cols[1].markdown(f"<span class='loss-text'>{content}</span>", unsafe_allow_html=True)
            with cols[2]:
                with st.popover("⚠️ 改善案"):
                    st.write(str(row.get('Hint', '品質スコア向上のため修正が必要です')).replace("**", ""))
        else:
            cols[1].write(content)
            cols[2].write("✅ WIN")

def safe_table_display(df, type_name, col_mapping):
    try:
        if df is None or df.empty: return False
        sub_df = df[df['Type'].astype(str).str.contains(type_name, na=False, case=False)].copy()
        if sub_df.empty: return False
        sub_df.index = range(1, len(sub_df) + 1)
        # データのクリーニング
        for col in sub_df.columns:
            sub_df[col] = sub_df[col].astype(str).str.replace("**", "", regex=False)
        
        display_cols = [c for c in col_mapping.keys() if c in sub_df.columns]
        st.table(sub_df[display_cols].rename(columns=col_mapping))
        return True
    except: return False

async def fetch_and_clean_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            html = await page.content()
            await browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header", "aside"]): s.decompose()
            return " ".join(soup.get_text(separator=" ").split())[:4500]
        except Exception as e:
            await browser.close()
            return f"Error: {str(e)}"

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
        2. [STATUS]判定：具体的数値や強力なベネフィットがあるなら「WIN」、一般的すぎる表現なら「LOSS」とせよ。
        3. CSVデータ内には ** などの装飾記号は絶対に入れないこと。

        【構成】
        最初にサイト解析（強み・課題・改善案）を書き、その後に必ず[DATA_START]と[DATA_END]で囲んでCSVデータを出力してください。
        Type,Content,Details,Other1,Other2,Status,Hint の7列固定です。

        [DATA_START]
        Type,Content,Details,Other1,Other2,Status,Hint
        見出し,サンプルテキスト,,,WIN,
        [DATA_END]
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI生成エラー: {str(e)}"

# --- 4. メインUI ---
st.set_page_config(page_title="検索広告案 自動生成ツール", layout="wide")

with st.sidebar:
    st.markdown("<h1 style='text-align: center; font-size: 50px;'>⚙️</h1>", unsafe_allow_html=True)
    pwd = st.text_input("パスワード", type="password")
    if pwd != "password":
        if pwd != "" : st.error("パスワードが違います")
        st.stop()

api_key = st.secrets.get("GEMINI_API_KEY")
st.title("検索（リスティング）広告案 自動生成ツール")

url_in = st.text_input("LPのURLを入力してください", placeholder="https://********.com")

if st.button("分析＆生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略構築中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            res = generate_ad_plan(cleaned, api_key)
            st.session_state.ad_result = res
            st.balloons()
            
# --- 5. 結果表示ロジック (不具合を完全に解消する強化版) ---
if st.session_state.ad_result:
    res_text = st.session_state.ad_result
    df_all = None
    
    # 1. 解析テキストの抽出（[DATA_START]の前を確実に取得）
    main_text = ""
    if "[DATA_START]" in res_text:
        main_text = res_text.split("[DATA_START]")[0].strip()
    else:
        main_text = res_text # タグがない場合は全文

    # 2. CSVデータのパース（柔軟性を最大化）
    pattern = re.compile(r"\[DATA_START\](.*?)\[DATA_END\]", re.DOTALL | re.IGNORECASE)
    match = pattern.search(res_text)
    if match:
        try:
            raw_csv = match.group(1).strip()
            raw_csv = raw_csv.replace("```csv", "").replace("```", "").strip()
            
            # AIがカンマの数を間違えても読み込めるように io.StringIO を前処理
            lines = raw_csv.splitlines()
            cleaned_lines = []
            for line in lines:
                # 行に含まれるアスタリスクを除去
                line = line.replace("**", "")
                # カンマが少ない行にカンマを補填（列数を7列に固定）
                comma_count = line.count(",")
                if comma_count < 6:
                    line += "," * (6 - comma_count)
                cleaned_lines.append(line)
            
            final_csv = "\n".join(cleaned_lines)
            df_all = pd.read_csv(io.StringIO(final_csv), on_bad_lines='skip', engine='python')
            df_all.columns = [c.strip() for c in df_all.columns]
            
            # 全データから不要な装飾を除去
            df_all = df_all.applymap(lambda x: str(x).replace("**", "").strip() if pd.notnull(x) else "")
        except Exception as e:
            st.warning(f"データ解析中に一部不備が見つかりました: {e}")

    # --- 3. Excel作成 (確実に全シートを出力) ---
    try:
        excel_out = io.BytesIO()
        # openpyxlを直接制御してシートを作成
        with pd.ExcelWriter(excel_out, engine='openpyxl') as writer:
            # 1枚目: サイト解析 (データフレームを介さず書き込む方式)
            clean_analysis = main_text.replace("<br>", "\n").replace("<b>", "").replace("</b>", "").strip()
            df_tmp_analysis = pd.DataFrame([["分析結果全文", clean_analysis]], columns=["項目", "内容"])
            df_tmp_analysis.to_excel(writer, index=False, sheet_name='1_サイト解析')
            
            # シートの列幅を調整
            ws = writer.sheets['1_サイト解析']
            ws.column_dimensions['B'].width = 100

            if df_all is not None:
                # 2枚目以降: 広告文・キーワード・アセット
                targets = [
                    ('見出し', '2_広告文案_見出し'),
                    ('説明文', '3_説明文案'),
                    ('キーワード', '4_キーワード'),
                    ('スニペット|コールアウト', '5_6_アセット')
                ]
                for search_key, sheet_name in targets:
                    mask = df_all['Type'].astype(str).str.contains(search_key, na=False, case=False)
                    tmp_df = df_all[mask].copy()
                    if not tmp_df.empty:
                        tmp_df.to_excel(writer, index=False, sheet_name=sheet_name)
                    else:
                        # データが空でもシートだけは作成してエラーを防ぐ
                        pd.DataFrame([["なし"]]).to_excel(writer, index=False, sheet_name=sheet_name)

        # ダウンロードボタンの表示
        st.download_button(
            label="📊 解析結果(Excel)をダウンロード",
            data=excel_out.getvalue(),
            file_name="ad_strategy_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"Excel出力エラー: {e}")

    # --- 4. 画面表示（タブ） ---
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
            st.info("広告文のデータが生成されませんでした。")

    with tab3:
        if df_all is not None:
            st.markdown(apply_decoration("④キーワード"), unsafe_allow_html=True)
            safe_table_display(df_all, 'キーワード', {'Content':'キーワード','Details':'マッチタイプ','Other1':'推定CPC','Other2':'優先度'})
            st.divider()
            # コールアウトアセットの表示（フィルタを「コールアウト」に限定せず広く取る）
            dynamic_ad_display(df_all, 'コールアウト', "⑥コールアウトアセット")
        else:
            st.info("キーワード・アセットのデータがありません。")

    # デバッグ：AIが本当に何を出したかを確認
    with st.expander("🛠 AIからの生レスポンス（不具合調査用）"):
        st.code(res_text)
