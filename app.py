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
    
    /* ポップオーバーボタンと中身の視認性向上 */
    div[data-testid="stPopover"] button p { color: #000000 !important; }
    div[data-testid="stPopoverBody"] p, div[data-testid="stPopoverBody"] span, div[data-testid="stPopoverBody"] div { color: #000000 !important; }
    
    section[data-testid="stSidebar"] { background-color: #1e1e1e !important; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; height: 3.5em; background-color: #D4AF37; color: #000000 !important; border: none; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #D4AF37; color: white !important; border: none; font-weight: bold; }
    
    /* ロジック解説ボックスの装飾 */
    .logic-box { padding: 25px; border-radius: 10px; background-color: #1e1e1e; border: 1px solid #D4AF37; margin-bottom: 25px; line-height: 1.6; }
    .logic-table { width: 100%; border-collapse: collapse; margin-top: 10px; color: #ffffff; }
    .logic-table th, .logic-table td { border: 1px solid #444; padding: 10px; text-align: left; font-size: 0.9em; }
    .logic-table th { background-color: #333; color: #D4AF37; }
    
    .report-box { padding: 20px; border-radius: 0px; background-color: transparent; margin-bottom: 25px; line-height: 1.8; border: 1px solid #333; }
    .section-heading { color: #ffffff !important; font-weight: bold !important; font-size: 1.25em !important; margin-top: 35px; border-left: 5px solid #D4AF37; padding-left: 15px; display: block; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. パスワード認証（サイドバー） ---
with st.sidebar:
    st.title("Admin Access")
    if st.text_input("Password", type="password") != "password":
        st.warning("パスワードを入力してください")
        st.stop()
    st.success("認証済み")

# --- 4. メインヘッダーとロジック解説 ---
st.title("検索広告プラン自動生成ツール")

st.markdown("""
<div class="logic-box">
<h3>⚙️ セクション別・生成ロジックの解説</h3>
当ツールは、LP解析結果（①）に基づき、Google広告の「品質スコア」を最大化させるため、各項目を以下のロジックで生成しています。
<table class="logic-table">
    <tr>
        <th>セクション</th>
        <th>生成ロジック（AIの思考プロセス）</th>
    </tr>
    <tr>
        <td><b>② 見出し(15案)</b></td>
        <td>解析した強みから「ブランド名」「ベネフィット」「信頼性」を抽出し、30文字以内の検索意図に刺さるコピーへ変換します。</td>
    </tr>
    <tr>
        <td><b>③ 説明文(4案)</b></td>
        <td>見出しでは伝えきれない「安心感」や「具体的サービス内容」を、LPの文脈を維持したまま90文字の文章に構成します。</td>
    </tr>
    <tr>
        <td><b>④ キーワード(20案)</b></td>
        <td>「地域名 × サービス」「高額ブランド名 × 買取」など、獲得効率の高い組み合わせをマッチタイプ別に戦略的に選定します。</td>
    </tr>
    <tr>
        <td><b>⑤ スニペット</b></td>
        <td>LP内の商品カテゴリや取扱ブランドを「種類」として分類し、ユーザーが探している商材との一致度を視覚的に高めます。</td>
    </tr>
    <tr>
        <td><b>⑥ コールアウト</b></td>
        <td>「送料無料」「即日現金」など、LP内に散らばる「選ばれる理由」を短文で抽出し、広告の占有面積とクリック率を向上させます。</td>
    </tr>
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

def flexible_display(df, filter_keywords, label, exclude_keywords=None):
    st.markdown(apply_decoration(label), unsafe_allow_html=True)
    if df is None or df.empty: return
    mask = df['Type'].astype(str).str.contains(filter_keywords, case=False, na=False, regex=True)
    sub_df = df[mask].copy()
    if sub_df.empty:
        st.write("（具体的案が出力されませんでした。再生成してください。）")
        return
    for i, (_, row) in enumerate(sub_df.iterrows(), 1):
        content, details = clean_text(row.get('Content')), clean_text(row.get('Details'))
        cols = st.columns([0.1, 0.7, 0.2])
        cols[0].write(i)
        cols[1].write(content)
        # 見出し・説明文の「詳細」がただのラベルなら非表示、中身があればポップオーバー
        if details and not any(x in details for x in ["広告見出し", "広告説明文", "コールアウト"]):
            with cols[2]:
                with st.popover("💡 詳細"): st.write(details)
        else: cols[2].write("✅ WIN")

# --- 6. スクレイピング & 生成ロジック ---
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
        あなたは日本最高峰の広告運用者です。LPを分析し、以下のノルマを【絶対】に遵守してプランを作成してください。

        【④ キーワード戦略の出力ルール（重要）】
        - 20個。Typeは 'Keyword'。
        - Contentカラム: キーワード本体。
        - Detailsカラム: 必ず '部分一致', 'フレーズ一致', '完全一致' のいずれか。
        - Other1カラム: そのマッチタイプを採用する具体的な「入札戦略・理由」。

        【その他個数ノルマ】
        - Headline: 15個。Type: 'Headline'。
        - Description: 4個。Type: 'Description'。
        - Snippet: 3種類。Type: 'Snippet'。
        - Callout: 10個。Type: 'Callout'。

        出力構成:
        1. サイト分析（①強み ②課題 ③改善案）のみを記述。
        2. その後 [DATA_START] と [DATA_END] で囲んでCSVを出力。
        CSVカラム: Type,Content,Details,Other1,Other2,Status,Hint
        サイト内容: {site_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"AI生成エラー: {str(e)}"

# --- 7. URL入力エリア ---
url_in = st.text_input("LPのURLを入力してください")

if st.button("生成スタート"):
    if url_in:
        with st.spinner("🚀 戦略・広告案を構築中..."):
            cleaned = asyncio.run(fetch_and_clean_content(url_in))
            st.session_state.ad_result = generate_ad_plan(cleaned, api_key)
            st.balloons()

# --- 8. 結果表示・Excel出力 ---
if st.session_state.ad_result:
    res = st.session_state.ad_result
    analysis_raw = res.split("[DATA_START]")[0].strip() if "[DATA_START]" in res else res
    if "①" in analysis_raw: analysis_raw = analysis_raw[analysis_raw.find("①"):]
    cleaned_analysis = re.split(r'\n\s*(-{3,}|#{1,4}\s*[23]\.)', analysis_raw)[0].strip()
    
    df_all = None
    match_csv = re.search(r"\[DATA_START\](.*?)\[DATA_END\]", res, re.DOTALL | re.IGNORECASE)
    if match_csv:
        csv_raw = match_csv.group(1).strip()
        csv_raw = re.sub(r"```[a-z]*", "", csv_raw).replace("```", "").strip()
        parsed_data = []
        for line in csv_raw.splitlines():
            if "," in line:
                cols = [c.strip() for c in line.split(",")]
                if len(cols) > 7:
                    fixed_row = [cols[0], cols[1], cols[2], " / ".join(cols[3:]), "", "", ""]
                    parsed_data.append(fixed_row[:7])
                else:
                    while len(cols) < 7: cols.append("")
                    parsed_data.append(cols[:7])
        if parsed_data:
            df_all = pd.DataFrame(parsed_data, columns=["Type", "Content", "Details", "Other1", "Other2", "Status", "Hint"]).applymap(clean_text)

    # --- Excelダウンロードボタン ---
    if df_all is not None:
        try:
            excel_io = io.BytesIO()
            with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
                pd.DataFrame([["① 解析結果", cleaned_analysis]], columns=["項目", "内容"]).to_excel(writer, index=False, sheet_name="1_解析")
                maps = [("Headline|見出し", "2_見出し"), ("Description|説明文", "3_説明文"), ("Keyword|キーワード", "4_キーワード"), ("Snippet|スニペット", "5_スニペット"), ("Callout|コールアウト", "6_コールアウト")]
                for k, s_name in maps:
                    sub_ex = df_all[df_all['Type'].astype(str).str.contains(k, case=False, na=False, regex=True)].copy()
                    if not sub_ex.empty:
                        sub_ex.index = range(1, len(sub_ex) + 1)
                        sub_ex.to_excel(writer, index=True, index_label="No", sheet_name=s_name)
            st.download_button("📊 広告プランをExcelでダウンロード", excel_io.getvalue(), "ad_plan.xlsx")
        except: pass

    # --- タブ表示 ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["① 解析", "② 見出し(15)", "③ 説明文(4)", "④ キーワード(20)", "⑤ スニペット", "⑥ コールアウト"])
    
    with tab1: st.markdown(f'<div class="report-box">{apply_decoration(cleaned_analysis)}</div>', unsafe_allow_html=True)
    with tab2: flexible_display(df_all, "Headline|見出し", "② 広告文（見出し15個）")
    with tab3: flexible_display(df_all, "Description|説明文", "③ 広告文（説明文4個）")
    with tab4:
        st.markdown(apply_decoration("④ キーワード戦略（20個・マッチタイプ別）"), unsafe_allow_html=True)
        if df_all is not None:
            sub = df_all[df_all['Type'].astype(str).str.contains("Keyword|キーワード", case=False, na=False)].copy()
            # 「ターゲットキーワード」救済とマッチタイプ自動補完
            for idx, row in sub.iterrows():
                if "ターゲット" in str(row['Details']):
                    h = str(row['Hint'])
                    if "部分" in h: sub.at[idx, 'Details'] = "部分一致"
                    elif "フレーズ" in h: sub.at[idx, 'Details'] = "フレーズ一致"
                    elif "完全" in h: sub.at[idx, 'Details'] = "完全一致"
                    else: sub.at[idx, 'Details'] = "部分一致" # デフォルト
                    if not row['Other1']: sub.at[idx, 'Other1'] = h
            
            sub.index = range(1, len(sub) + 1)
            st.table(sub[["Content", "Details", "Other1"]].rename(columns={"Content": "キーワード", "Details": "マッチタイプ", "Other1": "入札戦略・理由"}))
    
    with tab5: flexible_display(df_all, "Snippet|スニペット", "⑤ 構造化スニペット")
    with tab6: flexible_display(df_all, "Callout|コールアウト", "⑥ コールアウトアセット")

