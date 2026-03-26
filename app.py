"""
=============================================================
Automated Call Quality Assurance Dashboard
Powered by HYDA AQM
=============================================================
"""

import streamlit as st
from google import genai
from google.genai import types
import json
import time
import os
import tempfile
import pandas as pd
from datetime import datetime
import pathlib

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Automated Call QA Dashboard",
    page_icon="📞",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }

    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d6a9f 100%);
        border-radius: 12px;
        padding: 16px 20px;
        border: 1px solid rgba(255,255,255,0.1);
    }
    div[data-testid="metric-container"] label,
    div[data-testid="metric-container"] div { color: white !important; }

    .section-header {
        font-size: 18px;
        font-weight: 700;
        color: #2d6a9f;
        border-bottom: 2px solid #2d6a9f;
        padding-bottom: 6px;
        margin-bottom: 14px;
    }
    .arabic-text {
        direction: rtl;
        text-align: right;
        font-size: 15px;
        line-height: 1.8;
        font-family: 'Segoe UI', 'Arial', sans-serif;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1b2a 0%, #1b2a3b 100%);
    }
    section[data-testid="stSidebar"] * { color: #e0e8f0 !important; }
    .hero-banner {
        background: linear-gradient(135deg, #0d1b2a 0%, #1e3a5f 50%, #2d6a9f 100%);
        border-radius: 14px;
        padding: 28px 36px;
        color: white;
        margin-bottom: 24px;
    }
    .hero-banner h1 { color: white; font-size: 28px; margin: 0; }
    .hero-banner p  { color: #a8c8e8; margin: 4px 0 0; font-size: 14px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def score_label(score: int) -> str:
    if score >= 80:  return "Excellent ✨"
    if score >= 60:  return "Good 👍"
    return "Needs Improvement ⚠️"

def priority_emoji(p: str) -> str:
    return {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(p, "⚪")

def severity_fn(sev: str):
    return {"Critical": st.error, "Warning": st.warning}.get(sev, st.info)

def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def upload_audio(client: genai.Client, file_bytes: bytes, suffix: str):
    """Upload audio bytes to Gemini Files API and wait until ACTIVE."""
    mime_map = {
        "mp3": "audio/mpeg", "wav": "audio/wav",  "aac": "audio/aac",
        "m4a": "audio/mp4",  "ogg": "audio/ogg",  "flac": "audio/flac",
    }
    mime = mime_map.get(suffix.lower(), "audio/mpeg")

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            uploaded = client.files.upload(
                file=f,
                config=types.UploadFileConfig(mime_type=mime),
            )

        # Poll until ready (max ~2 minutes)
        for _ in range(40):
            file_info = client.files.get(name=uploaded.name)
            if file_info.state.name == "ACTIVE":
                return file_info
            if file_info.state.name == "FAILED":
                raise RuntimeError("Gemini file processing FAILED.")
            time.sleep(3)

        raise TimeoutError("File did not become ACTIVE within 2 minutes.")
    finally:
        os.unlink(tmp_path)


def build_system_prompt(department: str, dialect: str, kpis: str) -> str:
    return f"""You are an expert Quality Assurance Auditor specialising in call centres.
Your analysis must be precise, culturally aware, and sensitive to Arabic communication norms.

DEPARTMENT: {department}
DIALECT: {dialect}

ANALYSIS GUIDELINES:
- Handle Arabic-English code-switching naturally (agents frequently mix Arabic with English technical terms).
- Distinguish clearly between agent behaviour and customer behaviour.
- Evaluate both verbal content and tonal/emotional delivery.
- Be concise yet specific; cite moments or exact phrases as evidence where possible.
- All reasoning/description fields MUST be written in Arabic (العربية).

KPIs TO EVALUATE:
{kpis}

RESPOND ONLY with a single valid JSON object — no markdown fences, no explanatory text:
{{
    "call_summary": {{
        "overview_ar": "ملخص عربي للمكالمة (2-3 جمل)",
        "overview_en": "English summary of the call (2-3 sentences)",
        "duration_estimate": "estimated duration e.g. ~4 mins",
        "call_type": "Complaint | Inquiry | Sales | Technical | Collections | Other",
        "resolution_status": "Resolved | Unresolved | Partially Resolved",
        "overall_score": <integer 0-100>
    }},
    "sentiment_analysis": {{
        "agent_sentiment": {{
            "score": <integer 1-10>,
            "label": "Positive | Neutral | Negative",
            "description_ar": "وصف مفصّل بالعربية"
        }},
        "customer_sentiment": {{
            "score": <integer 1-10>,
            "label": "Positive | Neutral | Negative",
            "description_ar": "وصف مفصّل بالعربية"
        }},
        "sentiment_trend": "Improving | Declining | Stable",
        "key_moments": [
            {{"timestamp": "~01:30", "event": "brief description"}}
        ]
    }},
    "kpi_scorecard": [
        {{
            "kpi_name": "KPI short name",
            "status": "Pass | Fail | N/A",
            "score": <null or integer 1-10>,
            "reasoning_ar": "تفاصيل التقييم بالعربية",
            "evidence": "quoted moment or phrase from the call"
        }}
    ],
    "coaching_tips": [
        {{
            "priority": "High | Medium | Low",
            "area": "e.g. Empathy, Compliance, Communication",
            "tip_ar": "نصيحة تدريبية بالعربية",
            "tip_en": "Coaching tip in English"
        }}
    ],
    "compliance_flags": [
        {{
            "flag": "short flag title",
            "severity": "Critical | Warning | Info",
            "description_ar": "وصف المشكلة بالعربية"
        }}
    ]
}}"""


def get_best_model(client: genai.Client) -> str:
    """Dynamically pick the best available Gemini model for audio analysis.

    Returns the exact model name as reported by the API (e.g. 'models/gemini-2.0-flash-001')
    so the generate_content call never gets a 404.
    """
    # Substring patterns checked in order of preference
    _PRIORITY_PATTERNS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-flash",
        "gemini-pro",
        "gemini-2.5",
        "gemini-3",
    ]
    try:
        all_names = [m.name for m in client.models.list()]
        # all_names are like "models/gemini-2.0-flash-001" — use them as-is
        for pattern in _PRIORITY_PATTERNS:
            for name in all_names:
                if pattern in name.lower():
                    return name          # full name, e.g. "models/gemini-2.0-flash-001"
        # last resort — any gemini model
        for name in all_names:
            if "gemini" in name.lower():
                return name
    except Exception:
        pass
    return "models/gemini-2.0-flash-001"  # absolute fallback


def call_gemini(client: genai.Client, audio_file, system_prompt: str) -> dict:
    """Send uploaded audio + system prompt to Gemini and return parsed JSON."""
    model_name = get_best_model(client)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[
                audio_file,
                "Analyse this call recording according to your system instructions. "
                "Return ONLY the JSON object.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        return json.loads(clean_json(response.text))
    except Exception as exc:
        raise RuntimeError(
            f"Gemini model '{model_name}' failed.\n"
            f"Error: {exc}\n\n"
            "👉 Click 'Test API Connection' in the sidebar and expand 'Available models' "
            "to verify your key has access."
        ) from exc


def generate_text_report(data: dict, department: str, dialect: str, filename: str) -> str:
    cs    = data["call_summary"]
    sa    = data["sentiment_analysis"]
    score = cs["overall_score"]
    lines = [
        "=" * 60,
        "  ARABIC CALL QUALITY ASSURANCE REPORT",
        "=" * 60,
        f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Model     : Google Gemini 2.0 Flash",
        f"Department: {department}",
        f"Dialect   : {dialect}",
        f"File      : {filename}",
        "",
        f"OVERALL SCORE : {score} / 100  ({score_label(score)})",
        "",
        "─" * 60, "CALL SUMMARY", "─" * 60,
        cs.get("overview_en", ""),
        f"\nملخص: {cs.get('overview_ar', '')}",
        f"\nCall Type  : {cs.get('call_type', '')}",
        f"Duration   : {cs.get('duration_estimate', '')}",
        f"Resolution : {cs.get('resolution_status', '')}",
        "",
        "─" * 60, "SENTIMENT ANALYSIS", "─" * 60,
        f"Agent    : {sa['agent_sentiment']['label']} ({sa['agent_sentiment']['score']}/10)",
        sa['agent_sentiment']['description_ar'],
        f"\nCustomer : {sa['customer_sentiment']['label']} ({sa['customer_sentiment']['score']}/10)",
        sa['customer_sentiment']['description_ar'],
        f"\nTrend    : {sa['sentiment_trend']}",
        "",
        "─" * 60, "KPI SCORECARD", "─" * 60,
    ]
    for kpi in data.get("kpi_scorecard", []):
        s = f"  Score: {kpi['score']}/10" if kpi.get("score") is not None else ""
        lines += [f"\n• {kpi['kpi_name']}", f"  Status : {kpi['status']}{s}",
                  f"  {kpi.get('reasoning_ar','')}"]
        if kpi.get("evidence"):
            lines.append(f'  Evidence: "{kpi["evidence"]}"')

    lines += ["", "─" * 60, "COACHING RECOMMENDATIONS", "─" * 60]
    for tip in data.get("coaching_tips", []):
        lines += [f"\n[{tip['priority']}] {tip['area']}",
                  f"  AR: {tip['tip_ar']}", f"  EN: {tip['tip_en']}"]

    if data.get("compliance_flags"):
        lines += ["", "─" * 60, "COMPLIANCE FLAGS", "─" * 60]
        for flag in data["compliance_flags"]:
            lines += [f"\n[{flag['severity']}] {flag['flag']}", f"  {flag.get('description_ar','')}"]

    lines += ["", "=" * 60, "RAW JSON DATA", "=" * 60,
              json.dumps(data, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📞 QA Dashboard")
    st.markdown("*Automated Call Analytics*")
    st.divider()

    st.markdown("### 🔑 API Configuration")
    api_key = st.text_input(
        "Google AI Studio API Key",
        type="password",
        placeholder="AIza...",
        help="Free key at https://aistudio.google.com/",
    )

    st.divider()
    st.markdown("### ⚙️ Analysis Settings")

    department = st.selectbox(
        "🏢 Department",
        ["Sales", "Customer Service", "Collections", "Technical Support"],
    )
    dialect = st.selectbox(
        "🌍 Arabic Dialect",
        ["Modern Standard Arabic (MSA)", "Egyptian", "Gulf", "Levantine", "Maghrebi"],
    )

    st.divider()
    st.markdown("### 📋 Evaluation KPIs")
    st.caption("Enter each criterion on a new line.")

    dept_kpis = {
        "Sales": (
            "1. Did the agent open with the mandatory brand greeting?\n"
            "2. Did the agent clearly introduce themselves by name?\n"
            "3. Did the agent identify and confirm the customer's need?\n"
            "4. Did the agent present product benefits persuasively?\n"
            "5. Did the agent handle objections professionally?\n"
            "6. Did the agent attempt to close the sale or schedule a follow-up?\n"
            "7. Rate overall sales effectiveness (1-10)\n"
            "8. Was the agent's tone enthusiastic and positive?"
        ),
        "Customer Service": (
            "1. Did the agent greet the customer warmly in Arabic?\n"
            "2. Did the agent verify the customer's identity?\n"
            "3. Did the agent listen actively without interrupting?\n"
            "4. Was the issue resolved to the customer's satisfaction?\n"
            "5. Did the agent show empathy throughout the call?\n"
            "6. Did the agent summarise next steps or resolution?\n"
            "7. Did the agent offer further assistance before closing?\n"
            "8. Rate customer satisfaction likelihood (1-10)"
        ),
        "Collections": (
            "1. Did the agent verify the customer's identity before discussing the account?\n"
            "2. Did the agent clearly state the outstanding balance?\n"
            "3. Did the agent offer a payment plan or settlement option?\n"
            "4. Was the tone firm but respectful throughout?\n"
            "5. Did the agent comply with collections regulations?\n"
            "6. Did the agent document commitments made by the customer?\n"
            "7. Rate the agent's negotiation effectiveness (1-10)"
        ),
        "Technical Support": (
            "1. Did the agent greet and introduce themselves?\n"
            "2. Did the agent collect all necessary technical details?\n"
            "3. Did the agent follow the correct troubleshooting steps?\n"
            "4. Did the agent explain the solution clearly in Arabic?\n"
            "5. Did the agent confirm the issue was resolved?\n"
            "6. Did the agent provide a reference/ticket number?\n"
            "7. Rate technical competency (1-10)"
        ),
    }

    kpis = st.text_area(
        "Success Criteria / KPIs",
        value=dept_kpis.get(department, dept_kpis["Customer Service"]),
        height=260,
    )

    st.divider()

    # ── API Connection Test ───────────────────────────────
    if api_key:
        if st.button("🔍 Test API Connection", use_container_width=True,
                     help="Lists the Gemini models available on your API key"):
            with st.spinner("Checking…"):
                try:
                    _tc = genai.Client(api_key=api_key)
                    _all = list(_tc.models.list())
                    _gem = [m.name for m in _all
                            if "gemini" in m.name.lower()
                            and "generateContent" in (getattr(m, "supported_actions", [])
                                                       or getattr(m, "supported_generation_methods", []))]
                    if _gem:
                        st.success(f"✅ Valid key! {len(_gem)} Gemini models available.")
                        with st.expander("📋 Available models"):
                            for _m in _gem:
                                st.code(_m)
                    else:
                        _all_names = [m.name for m in _all if "gemini" in m.name.lower()]
                        st.warning(f"⚠️ Key valid but no generateContent-capable Gemini models found. "
                                   f"All Gemini entries: {_all_names}")
                except Exception as _e:
                    st.error(f"❌ {str(_e)}")

    st.divider()
    st.caption("v1.0.1 · Gemini API · Arabic QA")


# ─────────────────────────────────────────────
# HERO BANNER
# ─────────────────────────────────────────────
st.markdown("""
<div class="hero-banner">
    <h1>📞 Automated Call QA Dashboard</h1>
    <p>Upload a call recording → Gemini analyses it in seconds → Full QA scorecard in Arabic &amp; English</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# FILE UPLOADER
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "📁 Upload Call Recording",
    type=["mp3", "wav", "aac", "m4a", "ogg", "flac"],
    help="Supported: MP3, WAV, AAC, M4A, OGG, FLAC",
)

if uploaded_file:
    st.audio(uploaded_file, format=f"audio/{uploaded_file.name.rsplit('.', 1)[-1]}")
    st.caption(f"📄 **{uploaded_file.name}** · {uploaded_file.size / 1024:.1f} KB")

    _, col_btn, _ = st.columns([1, 2, 1])
    with col_btn:
        process_btn = st.button("🔍  Analyse Call with HYDA AQM",
                                type="primary", use_container_width=True)

    if process_btn:
        if not api_key:
            st.error("❌ Please enter your Google AI Studio API Key in the sidebar.")
            st.stop()

        client = genai.Client(api_key=api_key)
        suffix = uploaded_file.name.rsplit(".", 1)[-1].lower()
        file_bytes = uploaded_file.read()

        # ── Upload + Analyse ──────────────────────────────────
        _error_msg = None
        _error_detail = None
        data = None

        with st.status("⏳ Processing…", expanded=True) as status:
            st.write("📤 Uploading audio to Gemini Files API…")
            try:
                audio_file = upload_audio(client, file_bytes, suffix)
            except Exception as e:
                status.update(label="❌ Upload failed", state="error")
                _error_msg = f"Upload error: {str(e)}"
                _error_detail = e

            if _error_msg is None:
                _model_used = get_best_model(client)
                st.write(f"🧠 Analysing with **{_model_used}**…")
                system_prompt = build_system_prompt(department, dialect, kpis)
                try:
                    data = call_gemini(client, audio_file, system_prompt)
                except json.JSONDecodeError as e:
                    status.update(label="❌ JSON parse error", state="error")
                    _error_msg = f"Could not parse Gemini response as JSON: {str(e)}"
                    _error_detail = e
                except Exception as e:
                    status.update(label="❌ Analysis failed", state="error")
                    _error_msg = (
                        f"Gemini API error: {str(e)}\n\n"
                        "💡 Common fixes:\n"
                        "• Make sure your API key is valid (get one at aistudio.google.com)\n"
                        "• Check you haven't exceeded the free-tier quota\n"
                        "• Try a different audio file format (WAV or MP3 work best)"
                    )
                    _error_detail = e

            if _error_msg is None:
                status.update(label="✅ Analysis complete!", state="complete", expanded=False)

        # Show errors OUTSIDE the status widget so they're always visible
        if _error_msg:
            st.error(f"❌ {_error_msg}")
            with st.expander("🔍 Full error details (share this when reporting a bug)"):
                st.exception(_error_detail)
            st.stop()

        # ── Extract sections ──────────────────────────────────
        cs         = data["call_summary"]
        sa         = data["sentiment_analysis"]
        kpi_list   = data.get("kpi_scorecard", [])
        tips       = data.get("coaching_tips", [])
        flags      = data.get("compliance_flags", [])
        score      = cs["overall_score"]

        st.divider()

        # ── Metric row ────────────────────────────────────────
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("🎯 Overall Score",   f"{score}/100",      score_label(score))
        m2.metric("⏱ Duration",         cs.get("duration_estimate", "—"))
        m3.metric("📂 Call Type",        cs.get("call_type", "—"))
        m4.metric("✅ Resolution",       cs.get("resolution_status", "—"))
        m5.metric("😊 Agent Sentiment",
                  f"{sa['agent_sentiment']['score']}/10",
                  sa['agent_sentiment']['label'])

        st.divider()

        # ── Two-column body ───────────────────────────────────
        left, right = st.columns([3, 2], gap="large")

        with left:
            # Summary
            st.markdown('<div class="section-header">📝 Call Summary</div>', unsafe_allow_html=True)
            tab_en, tab_ar = st.tabs(["English", "العربية"])
            with tab_en:
                st.info(cs.get("overview_en", "—"))
            with tab_ar:
                st.markdown(
                    f'<div class="arabic-text" dir="rtl">{cs.get("overview_ar", "—")}</div>',
                    unsafe_allow_html=True)

            st.markdown("")
            # KPI Scorecard
            st.markdown('<div class="section-header">✅ KPI Scorecard</div>', unsafe_allow_html=True)
            if kpi_list:
                rows = []
                for kpi in kpi_list:
                    icon = "✅" if kpi["status"] == "Pass" else "❌" if kpi["status"] == "Fail" else "➖"
                    score_disp = f"{kpi['score']}/10" if kpi.get("score") is not None else "—"
                    rows.append({
                        "KPI": kpi["kpi_name"],
                        "Result": f"{icon} {kpi['status']}",
                        "Score": score_disp,
                        "Reasoning (Arabic)": kpi.get("reasoning_ar", ""),
                        "Evidence": kpi.get("evidence", ""),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                             column_config={
                                 "Reasoning (Arabic)": st.column_config.TextColumn(width="large"),
                                 "Evidence": st.column_config.TextColumn(width="medium"),
                             })
            else:
                st.info("No KPI data returned.")

        with right:
            # Sentiment
            st.markdown('<div class="section-header">💭 Sentiment Analysis</div>', unsafe_allow_html=True)

            agent_s    = sa["agent_sentiment"]
            customer_s = sa["customer_sentiment"]

            st.markdown("**🎧 Agent**")
            st.progress(agent_s["score"] / 10,
                        text=f"{agent_s['label']}  ({agent_s['score']}/10)")
            st.markdown(
                f'<div class="arabic-text">{agent_s["description_ar"]}</div>',
                unsafe_allow_html=True)

            st.markdown("**👤 Customer**")
            st.progress(customer_s["score"] / 10,
                        text=f"{customer_s['label']}  ({customer_s['score']}/10)")
            st.markdown(
                f'<div class="arabic-text">{customer_s["description_ar"]}</div>',
                unsafe_allow_html=True)

            trend_icon = {"Improving": "📈", "Declining": "📉", "Stable": "➡️"}.get(
                sa["sentiment_trend"], "➡️")
            st.markdown(f"**Trend:** {trend_icon} {sa['sentiment_trend']}")

            if sa.get("key_moments"):
                with st.expander("⏱ Key Moments"):
                    for m in sa["key_moments"]:
                        st.markdown(f"- **{m.get('timestamp','?')}** — {m.get('event','')}")

            # Compliance Flags
            if flags:
                st.markdown("")
                st.markdown('<div class="section-header">🚨 Compliance Flags</div>', unsafe_allow_html=True)
                for flag in flags:
                    severity_fn(flag["severity"])(
                        f"**[{flag['severity']}] {flag['flag']}**\n\n"
                        + flag.get("description_ar", "")
                    )

        # ── Coaching Tips ─────────────────────────────────────
        st.divider()
        st.markdown('<div class="section-header">💡 Coaching Recommendations</div>', unsafe_allow_html=True)

        if tips:
            tip_cols = st.columns(min(len(tips), 3))
            for i, tip in enumerate(tips):
                with tip_cols[i % len(tip_cols)]:
                    with st.container(border=True):
                        st.markdown(
                            f"{priority_emoji(tip['priority'])} "
                            f"**{tip['priority']} Priority · {tip['area']}**"
                        )
                        st.markdown(
                            f'<div class="arabic-text">{tip["tip_ar"]}</div>',
                            unsafe_allow_html=True)
                        st.caption(f"🇬🇧 {tip['tip_en']}")
        else:
            st.info("No coaching tips returned.")

        # ── Export ────────────────────────────────────────────
        st.divider()
        st.markdown("### 📥 Export Report")

        base      = uploaded_file.name.rsplit(".", 1)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        txt_report  = generate_text_report(data, department, dialect, uploaded_file.name)
        json_report = json.dumps(data, ensure_ascii=False, indent=2)

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📄 Download Text Report (.txt)",
                data=txt_report,
                file_name=f"QA_Report_{base}_{timestamp}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "🗂 Download JSON Data (.json)",
                data=json_report,
                file_name=f"QA_Data_{base}_{timestamp}.json",
                mime="application/json",
                use_container_width=True,
            )

# ─────────────────────────────────────────────
# LANDING STATE
# ─────────────────────────────────────────────
else:
    st.markdown("### 👆 Upload a call recording above to get started")
    st.markdown("")

    cols = st.columns(4)
    features = [
        ("🌍", "Multi-Dialect Arabic",
         "MSA, Egyptian, Gulf, Levantine & Maghrebi — including Arabic-English code-switching."),
        ("📋", "Custom KPI Engine",
         "Define your own criteria. Get Pass/Fail results with Arabic-language reasoning."),
        ("📊", "Rich QA Dashboard",
         "Sentiment scores, compliance flags, key moments & prioritised coaching tips."),
        ("📥", "Export Reports",
         "Download full QA reports as .txt or structured .json — ready for your QA system."),
    ]
    for col, (icon, title, desc) in zip(cols, features):
        with col:
            with st.container(border=True):
                st.markdown(f"#### {icon} {title}")
                st.write(desc)

    st.divider()
    st.markdown("""
**Quick Start:**
1. Paste your **Google AI Studio API key** in the sidebar → [Get one free here](https://aistudio.google.com/)
2. Select **Department** and **Arabic Dialect**
3. Customise the **KPI criteria** for your QA framework
4. Upload an **MP3 / WAV / AAC** call recording
5. Click **Analyse Call** and wait ~15–30 seconds
    """)
