"""
=============================================================
HYDA AQM – Automated Call Quality Monitoring
=============================================================
"""

import streamlit as st
from google import genai
from google.genai import types
import json, time, os, tempfile, hashlib, pathlib
import pandas as pd
from datetime import datetime

# ─────────────────────────────────────────────
# PATHS & STORAGE
# ─────────────────────────────────────────────
APP_DIR      = pathlib.Path(__file__).parent
USERS_FILE   = APP_DIR / "users.json"
HISTORY_FILE = APP_DIR / "call_history.json"
CONFIG_FILE  = APP_DIR / "config.json"

# ─────────────────────────────────────────────
# PAGE CONFIG  (must be first Streamlit call)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="HYDA AQM",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* Layout */
.block-container { padding-top: 1.2rem; }

/* Metrics */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, #1e3a5f 0%, #2d6a9f 100%);
    border-radius: 12px;
    padding: 16px 20px;
    border: 1px solid rgba(255,255,255,0.1);
}
div[data-testid="metric-container"] label,
div[data-testid="metric-container"] div { color: white !important; }

/* Section headers */
.section-header {
    font-size: 17px; font-weight: 700;
    color: #2d6a9f;
    border-bottom: 2px solid #2d6a9f;
    padding-bottom: 6px; margin-bottom: 14px;
}

/* Arabic RTL */
.arabic-text {
    direction: rtl; text-align: right;
    font-size: 15px; line-height: 1.8;
    font-family: 'Segoe UI','Arial',sans-serif;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#0d1b2a 0%,#1b2a3b 100%);
}
section[data-testid="stSidebar"] * { color: #e0e8f0 !important; }

/* Hero banner */
.hero-banner {
    background: linear-gradient(135deg,#0d1b2a 0%,#1e3a5f 50%,#2d6a9f 100%);
    border-radius: 14px;
    padding: 24px 32px; color: white; margin-bottom: 20px;
}
.hero-banner h1 { color: white; font-size: 26px; margin:0; }
.hero-banner p  { color: #a8c8e8; margin:4px 0 0; font-size: 13px; }

/* Login card */
.login-card {
    max-width: 420px; margin: 60px auto;
    padding: 36px 40px;
    background: #0d1b2a;
    border-radius: 16px;
    border: 1px solid #2d6a9f;
}
.login-card h2 { color: #e0e8f0; text-align: center; margin-bottom: 6px; }
.login-card p  { color: #a8c8e8; text-align: center; margin-bottom: 24px; font-size: 13px; }

/* Badge */
.badge-admin    { background:#1e4d8c; color:#a8d4ff; padding:3px 10px; border-radius:12px; font-size:12px; }
.badge-super    { background:#3b1f6e; color:#d0b4ff; padding:3px 10px; border-radius:12px; font-size:12px; }

/* Call row score colouring (applied via pandas Styler) */
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# DATA HELPERS
# ═══════════════════════════════════════════════════════════

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    # seed default accounts on first run
    defaults = {
        "superadmin": {"password_hash": _hash("Hyda@2024"), "role": "superadmin",
                       "name": "Super Admin", "created_at": datetime.now().isoformat()},
        "admin":      {"password_hash": _hash("Hyda@2024"), "role": "admin",
                       "name": "Admin",       "created_at": datetime.now().isoformat()},
    }
    USERS_FILE.write_text(json.dumps(defaults, indent=2, ensure_ascii=False), encoding="utf-8")
    return defaults


def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def load_history() -> list:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(history: list):
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"api_key": ""}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def append_call(record: dict):
    history = load_history()
    history.append(record)
    save_history(history)


# ═══════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════

def authenticate(username: str, password: str):
    """Return user dict on success, None on failure."""
    users = load_users()
    user = users.get(username.strip().lower())
    if user and user["password_hash"] == _hash(password):
        return {"username": username.strip().lower(), **user}
    return None


def require_login():
    if not st.session_state.get("logged_in"):
        show_login_page()
        st.stop()


# ═══════════════════════════════════════════════════════════
# ANALYSIS CORE
# ═══════════════════════════════════════════════════════════

def score_label(score: int) -> str:
    if score >= 80: return "Excellent ✨"
    if score >= 60: return "Good 👍"
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
                file=f, config=types.UploadFileConfig(mime_type=mime))
        for _ in range(40):
            file_info = client.files.get(name=uploaded.name)
            if file_info.state.name == "ACTIVE":
                return file_info
            if file_info.state.name == "FAILED":
                raise RuntimeError("Audio processing failed — please try a different format.")
            time.sleep(3)
        raise TimeoutError("Audio processing timed out. Please try again.")
    finally:
        os.unlink(tmp_path)


def build_system_prompt(department: str, dialect: str, kpis: str) -> str:
    meta         = lang_meta(dialect)
    lang_instr   = meta["instruction"]
    native_name  = meta["native"]
    is_arabic    = meta["rtl"] and "Arabic" in dialect
    is_urdu      = dialect == "Urdu – اردو"
    is_english   = dialect == "English"

    # Code-switching note adapts per language family
    if is_arabic:
        codesw = "Handle Arabic-English code-switching naturally (agents frequently mix Arabic with English technical terms)."
    elif is_english:
        codesw = "The call is in English. Evaluate clarity, professionalism, and communication quality."
    else:
        codesw = f"Handle natural code-switching between {lang_instr} and English — this is common in Indian call centres."

    # The "_ar" suffix fields are kept for JSON schema stability; content must be in the target language
    native_placeholder = f"[Write this in {lang_instr}]"

    return f"""You are an expert Quality Assurance Auditor specialising in call centres.
Your analysis must be precise, culturally aware, and sensitive to local communication norms.

DEPARTMENT: {department}
LANGUAGE / DIALECT: {lang_instr}

ANALYSIS GUIDELINES:
- {codesw}
- Distinguish clearly between agent behaviour and customer behaviour.
- Evaluate both verbal content and tonal/emotional delivery.
- Be concise yet specific; cite moments or exact phrases as evidence where possible.
- All fields labelled _ar (overview_ar, description_ar, reasoning_ar, tip_ar) MUST be written in {lang_instr}. Do NOT use Arabic for these fields unless the dialect is Arabic or Urdu.
- The field overview_en must always be in English regardless of language.

KPIs TO EVALUATE:
{kpis}

RESPOND ONLY with a single valid JSON object — no markdown fences, no explanatory text:
{{
    "call_summary": {{
        "overview_ar": "{native_placeholder} — summary of the call (2-3 sentences)",
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
            "description_ar": "{native_placeholder} — detailed agent sentiment description"
        }},
        "customer_sentiment": {{
            "score": <integer 1-10>,
            "label": "Positive | Neutral | Negative",
            "description_ar": "{native_placeholder} — detailed customer sentiment description"
        }},
        "sentiment_trend": "Improving | Declining | Stable",
        "key_moments": [
            {{"timestamp": "~01:30", "event": "brief description in English"}}
        ]
    }},
    "kpi_scorecard": [
        {{
            "kpi_name": "KPI short name",
            "status": "Pass | Fail | N/A",
            "score": <null or integer 1-10>,
            "reasoning_ar": "{native_placeholder} — detailed KPI evaluation",
            "evidence": "quoted moment or phrase from the call"
        }}
    ],
    "coaching_tips": [
        {{
            "priority": "High | Medium | Low",
            "area": "e.g. Empathy, Compliance, Communication",
            "tip_ar": "{native_placeholder} — coaching tip",
            "tip_en": "Coaching tip in English"
        }}
    ],
    "compliance_flags": [
        {{
            "flag": "short flag title",
            "severity": "Critical | Warning | Info",
            "description_ar": "{native_placeholder} — description of the compliance issue"
        }}
    ]
}}"""


def call_analysis_api(client: genai.Client, audio_file, system_prompt: str) -> dict:
    _PRIORITY_PATTERNS = [
        "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro",
        "gemini-2.5-flash", "gemini-2.5-pro", "gemini-flash",
        "gemini-pro", "gemini-2.5", "gemini-3",
    ]
    try:
        all_model_names = [m.name for m in client.models.list()]
    except Exception:
        all_model_names = []

    ordered, seen = [], set()
    for pattern in _PRIORITY_PATTERNS:
        for name in all_model_names:
            if pattern in name.lower() and name not in seen:
                ordered.append(name); seen.add(name)
    if not ordered:
        ordered = ["models/gemini-2.0-flash-001", "models/gemini-1.5-flash-001"]

    last_exc, skipped = None, []
    for model_name in ordered:
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
            last_exc = exc
            err_str = str(exc).lower()
            if any(k in err_str for k in ("429","resource_exhausted","quota",
                                           "not found","404","unavailable")):
                skipped.append(model_name); continue
            raise RuntimeError(f"Analysis engine error: {exc}") from exc

    if any("quota" in str(e).lower() or "429" in str(e) for e in [last_exc]):
        raise RuntimeError(
            "Analysis quota exceeded on this API key.\n\n"
            "🔑 Please enter a valid HYDA AQM API key in settings.\n"
            f"Models tried: {skipped}"
        ) from last_exc
    raise RuntimeError(
        f"No working analysis model found.\nTried: {skipped}\nLast error: {last_exc}"
    ) from last_exc


DEPT_KPIS = {
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


# ─────────────────────────────────────────────────────────
# LANGUAGE CONFIGURATION
# All supported languages/dialects with metadata
# ─────────────────────────────────────────────────────────

LANGUAGE_OPTIONS = [
    # ── Arabic dialects ──────────────────────────────────
    "Arabic – Modern Standard (MSA)",
    "Arabic – Egyptian",
    "Arabic – Gulf",
    "Arabic – Levantine",
    "Arabic – Maghrebi",
    # ── English ──────────────────────────────────────────
    "English",
    # ── Hindi & Hinglish ─────────────────────────────────
    "Hindi – हिंदी",
    "Hinglish – Hindi-English Mix",
    # ── South Indian languages ────────────────────────────
    "Tamil – தமிழ்",
    "Telugu – తెలుగు",
    "Kannada – ಕನ್ನಡ",
    "Malayalam – മലയാളം",
    # ── West & Central Indian languages ──────────────────
    "Marathi – मराठी",
    "Gujarati – ગુજરાતી",
    # ── East Indian languages ─────────────────────────────
    "Bengali – বাংলা",
    "Odia – ଓଡ଼ିଆ",
    "Assamese – অসমীয়া",
    # ── North Indian languages ────────────────────────────
    "Punjabi – ਪੰਜਾਬੀ",
    "Urdu – اردو",
]

# Per-language metadata
#   native   : human-readable native script name (for tab label)
#   rtl      : True = right-to-left rendering
#   instruction : phrase sent to the AI describing the target language
LANGUAGE_META: dict[str, dict] = {
    "Arabic – Modern Standard (MSA)": {
        "native": "العربية", "rtl": True,
        "instruction": "Modern Standard Arabic (الفصحى)"},
    "Arabic – Egyptian": {
        "native": "العربية", "rtl": True,
        "instruction": "Egyptian Arabic (العامية المصرية)"},
    "Arabic – Gulf": {
        "native": "العربية", "rtl": True,
        "instruction": "Gulf Arabic (اللهجة الخليجية)"},
    "Arabic – Levantine": {
        "native": "العربية", "rtl": True,
        "instruction": "Levantine Arabic (الشامي)"},
    "Arabic – Maghrebi": {
        "native": "العربية", "rtl": True,
        "instruction": "Maghrebi Arabic (الدارجة)"},
    "English": {
        "native": "English", "rtl": False,
        "instruction": "English"},
    "Hindi – हिंदी": {
        "native": "हिंदी", "rtl": False,
        "instruction": "Hindi (हिंदी)"},
    "Hinglish – Hindi-English Mix": {
        "native": "Hinglish", "rtl": False,
        "instruction": "Hinglish (a natural conversational blend of Hindi and English)"},
    "Tamil – தமிழ்": {
        "native": "தமிழ்", "rtl": False,
        "instruction": "Tamil (தமிழ்)"},
    "Telugu – తెలుగు": {
        "native": "తెలుగు", "rtl": False,
        "instruction": "Telugu (తెలుగు)"},
    "Kannada – ಕನ್ನಡ": {
        "native": "ಕನ್ನಡ", "rtl": False,
        "instruction": "Kannada (ಕನ್ನಡ)"},
    "Malayalam – മലയാളം": {
        "native": "മലയാളം", "rtl": False,
        "instruction": "Malayalam (മലയാളം)"},
    "Marathi – मराठी": {
        "native": "मराठी", "rtl": False,
        "instruction": "Marathi (मराठी)"},
    "Gujarati – ગુજરાતી": {
        "native": "ગુજરાતી", "rtl": False,
        "instruction": "Gujarati (ગુજરાતી)"},
    "Bengali – বাংলা": {
        "native": "বাংলা", "rtl": False,
        "instruction": "Bengali (বাংলা)"},
    "Odia – ଓଡ଼ିଆ": {
        "native": "ଓଡ଼ିଆ", "rtl": False,
        "instruction": "Odia (ଓଡ଼ିଆ)"},
    "Assamese – অসমীয়া": {
        "native": "অসমীয়া", "rtl": False,
        "instruction": "Assamese (অসমীয়া)"},
    "Punjabi – ਪੰਜਾਬੀ": {
        "native": "ਪੰਜਾਬੀ", "rtl": False,
        "instruction": "Punjabi (ਪੰਜਾਬੀ)"},
    "Urdu – اردو": {
        "native": "اردو", "rtl": True,
        "instruction": "Urdu (اردو)"},
}


def lang_meta(dialect: str) -> dict:
    """Return metadata for the selected language, with safe fallback."""
    return LANGUAGE_META.get(dialect, {"native": dialect, "rtl": False, "instruction": dialect})


def native_div(text: str, dialect: str) -> str:
    """Wrap text in a div with correct direction for the selected language."""
    meta      = lang_meta(dialect)
    direction = "rtl" if meta["rtl"] else "ltr"
    align     = "right" if meta["rtl"] else "left"
    return (
        f'<div style="direction:{direction}; text-align:{align}; '
        f'font-size:15px; line-height:1.8; '
        f'font-family:\'Segoe UI\',\'Noto Sans\',\'Arial\',sans-serif;">'
        f'{text}</div>'
    )


# ═══════════════════════════════════════════════════════════
# PAGE: LOGIN
# ═══════════════════════════════════════════════════════════

def show_login_page():
    st.markdown("""
    <div style="text-align:center; padding: 40px 0 10px;">
        <div style="font-size:48px;">📊</div>
        <h1 style="color:#2d6a9f; margin:8px 0 2px; font-size:32px;">HYDA AQM</h1>
        <p style="color:#6c8fa8; font-size:14px;">Automated Quality Monitoring</p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        with st.container(border=True):
            st.markdown("### 🔐 Sign In")
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")

            if st.button("Sign In", type="primary", use_container_width=True):
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    user = authenticate(username, password)
                    if user:
                        st.session_state["logged_in"]  = True
                        st.session_state["user"]       = user
                        st.session_state["page"]       = "dashboard"
                        st.rerun()
                    else:
                        st.error("❌ Invalid username or password.")

            st.caption("Contact your Super Admin if you need access.")


# ═══════════════════════════════════════════════════════════
# PAGE: DASHBOARD (call history)
# ═══════════════════════════════════════════════════════════

def show_dashboard():
    import plotly.express as px
    import plotly.graph_objects as go
    from collections import Counter

    st.markdown("""
    <div class="hero-banner">
        <h1>📊 HYDA AQM · Call Quality Dashboard</h1>
        <p>Real-time quality insights across all analysed calls</p>
    </div>
    """, unsafe_allow_html=True)

    history = load_history()

    if not history:
        st.info("No calls have been analysed yet. Use **New Analysis** to upload and analyse a call.")
        return

    # ═══════════════════════════════════════════════════════
    # GLOBAL FILTERS (applied to all tabs)
    # ═══════════════════════════════════════════════════════
    with st.expander("🔍 Filters", expanded=True):
        gf1, gf2, gf3, gf4, gf5 = st.columns(5)

        all_depts    = sorted(set(r.get("department","") for r in history))
        all_statuses = sorted(set(r.get("resolution_status","") for r in history if r.get("resolution_status")))
        all_agents   = sorted(set(r.get("agent_name","Unknown") for r in history))

        sel_dept   = gf1.multiselect("Department",  all_depts,    default=all_depts)
        sel_status = gf2.multiselect("Resolution",  all_statuses, default=all_statuses)
        sel_agent  = gf3.multiselect("Agent",       all_agents,   default=all_agents)
        sel_score  = gf4.slider("Min Score", 0, 100, 0)

        # Date range
        timestamps = [r.get("timestamp","")[:10] for r in history if r.get("timestamp")]
        min_date   = pd.to_datetime(min(timestamps)).date() if timestamps else datetime.now().date()
        max_date   = pd.to_datetime(max(timestamps)).date() if timestamps else datetime.now().date()
        date_range = gf5.date_input("Date Range", value=(min_date, max_date))
        d_from = date_range[0] if len(date_range) >= 1 else min_date
        d_to   = date_range[1] if len(date_range) == 2 else max_date

    # Apply all filters
    filtered = [
        r for r in history
        if r.get("department","")           in sel_dept
        and (not sel_status or r.get("resolution_status","") in sel_status)
        and r.get("agent_name","Unknown")   in sel_agent
        and r.get("overall_score", 0)       >= sel_score
        and d_from <= pd.to_datetime(r.get("timestamp","1970")[:10]).date() <= d_to
    ]

    if not filtered:
        st.warning("No calls match the current filters.")
        return

    # ═══════════════════════════════════════════════════════
    # PRE-COMPUTE AGGREGATES
    # ═══════════════════════════════════════════════════════
    scores        = [r.get("overall_score", 0) for r in filtered]
    avg_score     = sum(scores) / len(scores)
    high_count    = sum(1 for s in scores if s >= 80)
    low_count     = sum(1 for s in scores if s < 60)
    resolved_count= sum(1 for r in filtered if r.get("resolution_status","") == "Resolved")

    # Compliance flags across all calls
    all_flags     = []
    all_tips_area = []
    for r in filtered:
        analysis = r.get("analysis", {})
        all_flags    += analysis.get("compliance_flags", [])
        all_tips_area += [t.get("area","") for t in analysis.get("coaching_tips", []) if t.get("area")]

    critical_flags = sum(1 for f in all_flags if f.get("severity") == "Critical")
    warning_flags  = sum(1 for f in all_flags if f.get("severity") == "Warning")
    info_flags     = sum(1 for f in all_flags if f.get("severity") == "Info")

    # ═══════════════════════════════════════════════════════
    # TABS
    # ═══════════════════════════════════════════════════════
    tab_ov, tab_an, tab_calls, tab_agents = st.tabs(
        ["📈 Overview", "📊 Analytics", "📋 All Calls", "🏆 Agent Leaderboard"]
    )

    # ───────────────────────────────────────────────────────
    # TAB 1 — OVERVIEW
    # ───────────────────────────────────────────────────────
    with tab_ov:

        # Top metrics
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("📋 Total Calls",      len(filtered))
        m2.metric("🎯 Avg Score",         f"{avg_score:.1f}/100")
        m3.metric("✅ High Performing",   high_count,    f"{high_count/len(filtered)*100:.0f}%")
        m4.metric("⚠️ Needs Attention",   low_count,     f"{low_count/len(filtered)*100:.0f}%")
        m5.metric("✔ Resolved",           resolved_count,f"{resolved_count/len(filtered)*100:.0f}%")
        m6.metric("🚨 Critical Flags",    critical_flags)

        st.divider()

        # ── Compliance flags summary ───────────────────────
        st.markdown('<div class="section-header">🚨 Compliance Flags Summary</div>', unsafe_allow_html=True)
        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            with st.container(border=True):
                st.markdown(f"<h2 style='color:#e53935; text-align:center; margin:0'>{critical_flags}</h2>"
                            f"<p style='text-align:center; color:#888; margin:0'>Critical Flags</p>",
                            unsafe_allow_html=True)
        with cf2:
            with st.container(border=True):
                st.markdown(f"<h2 style='color:#fb8c00; text-align:center; margin:0'>{warning_flags}</h2>"
                            f"<p style='text-align:center; color:#888; margin:0'>Warning Flags</p>",
                            unsafe_allow_html=True)
        with cf3:
            with st.container(border=True):
                st.markdown(f"<h2 style='color:#1e88e5; text-align:center; margin:0'>{info_flags}</h2>"
                            f"<p style='text-align:center; color:#888; margin:0'>Info Flags</p>",
                            unsafe_allow_html=True)

        # Show individual critical flags
        crit_flags = [f for f in all_flags if f.get("severity") == "Critical"]
        if crit_flags:
            with st.expander(f"🔴 View {len(crit_flags)} Critical Flag(s)", expanded=False):
                for f in crit_flags:
                    st.error(f"**{f.get('flag','')}** — {f.get('description_ar','')}")

        st.divider()

        # ── Top coaching areas ─────────────────────────────
        st.markdown('<div class="section-header">💡 Top Coaching Areas Needed</div>', unsafe_allow_html=True)
        if all_tips_area:
            area_counts  = Counter(all_tips_area).most_common(8)
            area_df      = pd.DataFrame(area_counts, columns=["Area", "Count"])
            fig_coach    = px.bar(
                area_df, x="Count", y="Area", orientation="h",
                color="Count",
                color_continuous_scale=["#2d6a9f","#e53935"],
                labels={"Count":"No. of Calls", "Area":"Coaching Area"},
            )
            fig_coach.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=280, showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False,
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_coach, use_container_width=True)
        else:
            st.info("No coaching data yet.")

        st.divider()

        # ── Score trend over time ──────────────────────────
        st.markdown('<div class="section-header">📈 Quality Score Trend Over Time</div>', unsafe_allow_html=True)
        trend_df = pd.DataFrame([{
            "Date":  r.get("timestamp","")[:10],
            "Score": r.get("overall_score", 0),
            "Dept":  r.get("department",""),
        } for r in filtered])
        trend_df["Date"] = pd.to_datetime(trend_df["Date"])
        daily_avg = trend_df.groupby("Date")["Score"].mean().reset_index()
        daily_avg.columns = ["Date","Average Score"]
        fig_trend = px.line(
            daily_avg, x="Date", y="Average Score",
            markers=True,
            color_discrete_sequence=["#2d6a9f"],
        )
        fig_trend.add_hline(y=80, line_dash="dot", line_color="#1a6b2e",
                            annotation_text="Excellent threshold (80)")
        fig_trend.add_hline(y=60, line_dash="dot", line_color="#fb8c00",
                            annotation_text="Good threshold (60)")
        fig_trend.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=300, yaxis=dict(range=[0,105]),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    # ───────────────────────────────────────────────────────
    # TAB 2 — ANALYTICS
    # ───────────────────────────────────────────────────────
    with tab_an:
        row1_l, row1_r = st.columns(2)

        # Department avg score
        with row1_l:
            st.markdown('<div class="section-header">🏢 Avg Score by Department</div>', unsafe_allow_html=True)
            dept_df = (
                pd.DataFrame([{"Department": r.get("department",""), "Score": r.get("overall_score",0)}
                               for r in filtered])
                .groupby("Department")["Score"].mean().reset_index()
                .sort_values("Score", ascending=True)
            )
            dept_df.columns = ["Department","Avg Score"]
            fig_dept = px.bar(
                dept_df, x="Avg Score", y="Department", orientation="h",
                color="Avg Score", color_continuous_scale=["#e53935","#fb8c00","#1a6b2e"],
                range_color=[0, 100],
                text=dept_df["Avg Score"].apply(lambda x: f"{x:.1f}"),
            )
            fig_dept.update_traces(textposition="outside")
            fig_dept.update_layout(
                margin=dict(l=0, r=20, t=10, b=0), height=300,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                coloraxis_showscale=False, xaxis=dict(range=[0,110]),
            )
            st.plotly_chart(fig_dept, use_container_width=True)

        # Call type distribution
        with row1_r:
            st.markdown('<div class="section-header">📂 Call Type Distribution</div>', unsafe_allow_html=True)
            type_counts = Counter(r.get("call_type","Other") for r in filtered)
            type_df     = pd.DataFrame(list(type_counts.items()), columns=["Type","Count"])
            fig_type    = px.pie(
                type_df, names="Type", values="Count", hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_type.update_traces(textposition="outside", textinfo="label+percent")
            fig_type.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=300,
                showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_type, use_container_width=True)

        st.divider()

        row2_l, row2_r = st.columns(2)

        # Resolution breakdown
        with row2_l:
            st.markdown('<div class="section-header">✅ Resolution Status Breakdown</div>', unsafe_allow_html=True)
            res_counts = Counter(r.get("resolution_status","—") for r in filtered)
            res_df     = pd.DataFrame(list(res_counts.items()), columns=["Status","Count"])
            color_map  = {"Resolved":"#1a6b2e","Partially Resolved":"#fb8c00","Unresolved":"#e53935"}
            fig_res    = px.pie(
                res_df, names="Status", values="Count", hole=0.5,
                color="Status", color_discrete_map=color_map,
            )
            fig_res.update_traces(textposition="outside", textinfo="label+percent")
            fig_res.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=300,
                showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_res, use_container_width=True)

        # Score distribution histogram
        with row2_r:
            st.markdown('<div class="section-header">📊 Score Distribution</div>', unsafe_allow_html=True)
            score_df = pd.DataFrame({"Score": scores})
            fig_hist = px.histogram(
                score_df, x="Score", nbins=10,
                color_discrete_sequence=["#2d6a9f"],
                labels={"Score":"Quality Score","count":"No. of Calls"},
            )
            fig_hist.add_vline(x=avg_score, line_dash="dash", line_color="#fb8c00",
                               annotation_text=f"Avg {avg_score:.1f}")
            fig_hist.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=300,
                bargap=0.05,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_hist, use_container_width=True)

    # ───────────────────────────────────────────────────────
    # TAB 3 — ALL CALLS
    # ───────────────────────────────────────────────────────
    with tab_calls:
        # Search bar
        search = st.text_input("🔎 Search by filename or agent name", placeholder="Type to filter…")
        if search:
            s = search.lower()
            display_list = [
                r for r in filtered
                if s in r.get("filename","").lower()
                or s in r.get("agent_name","").lower()
            ]
        else:
            display_list = filtered

        st.markdown(f'<div class="section-header">📋 Call Records ({len(display_list)} calls)</div>',
                    unsafe_allow_html=True)

        for i, record in enumerate(reversed(display_list)):
            idx   = len(display_list) - 1 - i
            score = record.get("overall_score", 0)
            score_color = "#1a6b2e" if score >= 80 else "#7d5a00" if score >= 60 else "#8b1a1a"
            badge_html  = (
                f'<span style="background:{score_color}; color:white; padding:3px 10px; '
                f'border-radius:10px; font-size:13px; font-weight:600;">{score}/100</span>'
            )
            res      = record.get("resolution_status","—")
            res_icon = {"Resolved":"✅","Unresolved":"❌","Partially Resolved":"🟡"}.get(res,"➖")
            agent    = record.get("agent_name","—")
            aid      = f" · {record.get('agent_id','')}" if record.get("agent_id") else ""

            with st.container(border=True):
                c1,c2,c3,c4,c5,c6,c7,c8,c9 = st.columns([0.35,1.8,1.2,1.0,1.0,0.9,1.0,1.3,1.0])
                c1.markdown(f"**#{record.get('call_id','—')}**")
                c2.markdown(f"🎙️ `{record.get('filename','—')}`")
                c3.markdown(f"👤 {agent}{aid}")
                c4.markdown(f"🏢 {record.get('department','—')}")
                c5.markdown(f"🕐 {record.get('timestamp','—')[:10]}")
                c6.markdown(f"⏱ {record.get('duration','—')}")
                c7.markdown(badge_html, unsafe_allow_html=True)
                c8.markdown(f"{res_icon} {res}")
                if c9.button("📄 Report", key=f"view_c_{idx}", use_container_width=True):
                    st.session_state["selected_call"] = record
                    st.session_state["page"] = "call_detail"
                    st.rerun()

        # Export
        st.divider()
        rows = []
        for r in display_list:
            rows.append({
                "Call ID":      r.get("call_id",""),
                "Filename":     r.get("filename",""),
                "Agent Name":   r.get("agent_name",""),
                "Agent ID":     r.get("agent_id",""),
                "Department":   r.get("department",""),
                "Language":     r.get("dialect",""),
                "Date/Time":    r.get("timestamp","")[:16],
                "Duration":     r.get("duration","—"),
                "Overall Score":r.get("overall_score",""),
                "Call Type":    r.get("call_type",""),
                "Resolution":   r.get("resolution_status",""),
                "Uploaded By":  r.get("uploaded_by",""),
            })
        df  = pd.DataFrame(rows)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Export Filtered Records (CSV)",
            data=csv,
            file_name=f"HYDA_AQM_Calls_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    # ───────────────────────────────────────────────────────
    # TAB 4 — AGENT LEADERBOARD
    # ───────────────────────────────────────────────────────
    with tab_agents:
        st.markdown('<div class="section-header">🏆 Agent Performance Leaderboard</div>',
                    unsafe_allow_html=True)

        agent_rows = {}
        for r in filtered:
            name  = r.get("agent_name","Unknown")
            score = r.get("overall_score", 0)
            res   = r.get("resolution_status","")
            if name not in agent_rows:
                agent_rows[name] = {
                    "Agent":       name,
                    "Agent ID":    r.get("agent_id",""),
                    "Department":  r.get("department",""),
                    "Calls":       0,
                    "_scores":     [],
                    "Resolved":    0,
                }
            agent_rows[name]["Calls"]    += 1
            agent_rows[name]["_scores"].append(score)
            if res == "Resolved":
                agent_rows[name]["Resolved"] += 1

        leaderboard = []
        for name, d in agent_rows.items():
            sc   = d["_scores"]
            avg  = sum(sc) / len(sc)
            best = max(sc)
            worst= min(sc)
            res_rate = d["Resolved"] / d["Calls"] * 100
            leaderboard.append({
                "Agent":           name,
                "Agent ID":        d["Agent ID"],
                "Department":      d["Department"],
                "Calls Analysed":  d["Calls"],
                "Avg Score":       round(avg, 1),
                "Best Score":      best,
                "Worst Score":     worst,
                "Resolution Rate": f"{res_rate:.0f}%",
            })

        leaderboard.sort(key=lambda x: x["Avg Score"], reverse=True)

        # Rank + medal
        for rank, row in enumerate(leaderboard, 1):
            medal = {1:"🥇", 2:"🥈", 3:"🥉"}.get(rank, f"#{rank}")
            row["Rank"] = medal

        lb_df = pd.DataFrame(leaderboard)[
            ["Rank","Agent","Agent ID","Department","Calls Analysed",
             "Avg Score","Best Score","Worst Score","Resolution Rate"]
        ]

        st.dataframe(
            lb_df,
            use_container_width=True, hide_index=True,
            column_config={
                "Avg Score":  st.column_config.ProgressColumn(
                    "Avg Score", min_value=0, max_value=100, format="%d"),
                "Best Score": st.column_config.NumberColumn("Best Score"),
                "Worst Score":st.column_config.NumberColumn("Worst Score"),
            },
        )

        st.divider()

        # Agent score bar chart
        st.markdown('<div class="section-header">📊 Agent Average Scores</div>', unsafe_allow_html=True)
        agent_chart_df = pd.DataFrame([
            {"Agent": row["Agent"], "Avg Score": row["Avg Score"]}
            for row in leaderboard
        ])
        fig_agents = px.bar(
            agent_chart_df.sort_values("Avg Score"),
            x="Avg Score", y="Agent", orientation="h",
            color="Avg Score", color_continuous_scale=["#e53935","#fb8c00","#1a6b2e"],
            range_color=[0, 100],
            text=agent_chart_df.sort_values("Avg Score")["Avg Score"].apply(lambda x: f"{x:.1f}"),
        )
        fig_agents.add_vline(x=80, line_dash="dot", line_color="#1a6b2e",
                             annotation_text="Excellent (80)")
        fig_agents.add_vline(x=60, line_dash="dot", line_color="#fb8c00",
                             annotation_text="Good (60)")
        fig_agents.update_traces(textposition="outside")
        fig_agents.update_layout(
            margin=dict(l=0, r=30, t=10, b=0),
            height=max(250, len(leaderboard)*50),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            coloraxis_showscale=False, xaxis=dict(range=[0,115]),
        )
        st.plotly_chart(fig_agents, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# PAGE: NEW ANALYSIS
# ═══════════════════════════════════════════════════════════

def show_new_analysis():
    st.markdown("""
    <div class="hero-banner">
        <h1>📞 New Call Analysis</h1>
        <p>Upload a call recording → HYDA AQM analyses it → Full QA scorecard in Arabic &amp; English</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Settings columns ──────────────────────────────────
    user_role = st.session_state.get("user", {}).get("role", "admin")

    # Super Admin gets 3 columns (dept / dialect / api key)
    # Admin gets 2 columns (dept / dialect only — no API section)
    if user_role == "superadmin":
        s1, s2, s3 = st.columns(3)
    else:
        s1, s2 = st.columns(2)

    department = s1.selectbox(
        "🏢 Department",
        list(DEPT_KPIS.keys()),
    )
    dialect = s2.selectbox(
        "🌍 Language / Dialect",
        LANGUAGE_OPTIONS,
    )

    # Load API key: Super Admin can view/edit; Admin uses stored key silently
    cfg = load_config()
    api_key = st.session_state.get("api_key", cfg.get("api_key", ""))

    if user_role == "superadmin":
        with s3:
            api_key_input = st.text_input(
                "🔑 API Key",
                value=api_key,
                type="password",
                placeholder="Enter HYDA AQM API key…",
            )
            if api_key_input and api_key_input != api_key:
                st.session_state["api_key"] = api_key_input
                cfg["api_key"] = api_key_input
                save_config(cfg)
                api_key = api_key_input
            elif api_key_input:
                api_key = api_key_input

        # Test connection — Super Admin only
        with st.expander("🔍 Test API Connection", expanded=False):
            if st.button("Run Connection Test", type="secondary"):
                if not api_key:
                    st.warning("Enter an API key above first.")
                else:
                    with st.spinner("Checking…"):
                        try:
                            _tc  = genai.Client(api_key=api_key)
                            _all = list(_tc.models.list())
                            _gem = [m.name for m in _all
                                    if "gemini" in m.name.lower()
                                    and "generateContent" in (
                                        getattr(m, "supported_actions", [])
                                        or getattr(m, "supported_generation_methods", [])
                                    )]
                            if _gem:
                                st.success(f"✅ Connection successful — {len(_gem)} analysis models available.")
                            else:
                                st.warning("⚠️ Key valid but no analysis models found.")
                        except Exception as _e:
                            st.error(f"❌ Connection failed: {str(_e)}")

    # ── Agent details row ─────────────────────────────────
    a1, a2 = st.columns(2)
    agent_name = a1.text_input("👤 Agent Name", placeholder="e.g. Ahmed Al-Rashidi")
    agent_id   = a2.text_input("🪪 Agent ID (optional)", placeholder="e.g. AGT-042")

    with st.expander("📋 KPI Criteria (editable)", expanded=False):
        kpis = st.text_area(
            "Success Criteria / KPIs",
            value=DEPT_KPIS.get(department, DEPT_KPIS["Customer Service"]),
            height=220,
            label_visibility="collapsed",
        )
    st.divider()

    # ── File uploader ─────────────────────────────────────
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
            process_btn = st.button(
                "🔍  Analyse Call with HYDA AQM",
                type="primary", use_container_width=True,
            )

        if process_btn:
            if not api_key:
                if user_role == "superadmin":
                    st.error("❌ Please enter the HYDA AQM API Key in the field above or in User Management → API Key.")
                else:
                    st.error("❌ System is not configured yet. Please contact your Super Admin.")
                st.stop()

            client     = genai.Client(api_key=api_key)
            suffix     = uploaded_file.name.rsplit(".", 1)[-1].lower()
            file_bytes = uploaded_file.read()

            _error_msg, _error_detail, data = None, None, None

            with st.status("⏳ Processing…", expanded=True) as status:
                st.write("📤 Uploading audio for processing…")
                try:
                    audio_file = upload_audio(client, file_bytes, suffix)
                except Exception as e:
                    status.update(label="❌ Upload failed", state="error")
                    _error_msg, _error_detail = f"Upload error: {str(e)}", e

                if _error_msg is None:
                    st.write("🧠 Running HYDA AQM quality analysis…")
                    system_prompt = build_system_prompt(department, dialect, kpis)
                    try:
                        data = call_analysis_api(client, audio_file, system_prompt)
                    except json.JSONDecodeError as e:
                        status.update(label="❌ Parse error", state="error")
                        _error_msg, _error_detail = f"Could not parse analysis response: {str(e)}", e
                    except Exception as e:
                        status.update(label="❌ Analysis failed", state="error")
                        _error_msg, _error_detail = str(e), e

                if _error_msg is None:
                    status.update(label="✅ Analysis complete!", state="complete", expanded=False)

            if _error_msg:
                st.error(f"❌ {_error_msg}")
                with st.expander("🔍 Technical details"):
                    st.exception(_error_detail)
                st.stop()

            # ── Save to history ───────────────────────────
            history = load_history()
            call_id = len(history) + 1
            cs = data["call_summary"]
            record = {
                "call_id":           call_id,
                "filename":          uploaded_file.name,
                "department":        department,
                "dialect":           dialect,
                "timestamp":         datetime.now().isoformat(),
                "overall_score":     cs["overall_score"],
                "duration":          cs.get("duration_estimate","—"),
                "call_type":         cs.get("call_type","—"),
                "resolution_status": cs.get("resolution_status","—"),
                "uploaded_by":       st.session_state["user"]["username"],
                "agent_name":        agent_name.strip() or "Unknown",
                "agent_id":          agent_id.strip(),
                "analysis":          data,
            }
            append_call(record)

            # ── Render results ────────────────────────────
            _render_call_report(record)

    else:
        # landing state
        st.markdown("### 👆 Upload a call recording above to get started")
        cols = st.columns(4)
        features = [
            ("🌍","Multi-Dialect Arabic",
             "MSA, Egyptian, Gulf, Levantine & Maghrebi — including code-switching."),
            ("📋","Custom KPI Engine",
             "Define your own criteria. Get Pass/Fail results with Arabic reasoning."),
            ("📊","Rich QA Dashboard",
             "Sentiment scores, compliance flags, key moments & coaching tips."),
            ("📥","Export Reports",
             "Download full QA reports as .txt or structured .json."),
        ]
        for col, (icon, title, desc) in zip(cols, features):
            with col:
                with st.container(border=True):
                    st.markdown(f"#### {icon} {title}")
                    st.write(desc)


# ═══════════════════════════════════════════════════════════
# PAGE: CALL DETAIL
# ═══════════════════════════════════════════════════════════

def show_call_detail():
    record = st.session_state.get("selected_call")
    if not record:
        st.warning("No call selected. Go back to the Dashboard.")
        if st.button("← Back to Dashboard"):
            st.session_state["page"] = "dashboard"
            st.rerun()
        return

    data  = record.get("analysis", {})
    cs    = data.get("call_summary", {})
    sa    = data.get("sentiment_analysis", {})
    score = cs.get("overall_score", 0)

    # ── Header ────────────────────────────────────────────
    back_col, title_col = st.columns([1, 8])
    with back_col:
        if st.button("← Back"):
            st.session_state["page"] = "dashboard"
            st.rerun()
    with title_col:
        st.markdown(
            f'<div class="hero-banner">'
            f'<h1>📄 Call Report — {record.get("filename","")}</h1>'
            f'<p>Call #{record.get("call_id","")} · '
            f'{record.get("department","")} · '
            f'{record.get("timestamp","")[:16]} · '
            f'Uploaded by: {record.get("uploaded_by","")}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

    _render_call_report(record)


def _render_call_report(record: dict):
    """Shared rendering function for both new analysis and call detail pages."""
    data    = record.get("analysis", {})
    cs      = data.get("call_summary", {})
    sa      = data.get("sentiment_analysis", {})
    kpi_list = data.get("kpi_scorecard", [])
    tips     = data.get("coaching_tips", [])
    flags    = data.get("compliance_flags", [])
    score    = cs.get("overall_score", 0)
    dialect  = record.get("dialect", "English")
    native   = lang_meta(dialect)["native"]   # native script tab label

    # ── Metric row ────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🎯 Overall Score",  f"{score}/100",  score_label(score))
    m2.metric("⏱ Duration",        cs.get("duration_estimate","—"))
    m3.metric("📂 Call Type",       cs.get("call_type","—"))
    m4.metric("✅ Resolution",      cs.get("resolution_status","—"))
    m5.metric("😊 Agent Sentiment",
              f"{sa.get('agent_sentiment',{}).get('score','—')}/10",
              sa.get('agent_sentiment',{}).get('label',''))
    st.divider()

    # ── Two-column body ───────────────────────────────────
    left, right = st.columns([3, 2], gap="large")

    with left:
        # Summary
        st.markdown('<div class="section-header">📝 Call Summary</div>', unsafe_allow_html=True)
        tab_en, tab_native = st.tabs(["English", native])
        with tab_en:
            st.info(cs.get("overview_en","—"))
        with tab_native:
            st.markdown(
                native_div(cs.get("overview_ar","—"), dialect),
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
                    "KPI":               kpi["kpi_name"],
                    "Result":            f"{icon} {kpi['status']}",
                    "Score":             score_disp,
                    "Reasoning (AR)":    kpi.get("reasoning_ar",""),
                    "Evidence":          kpi.get("evidence",""),
                })
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True, hide_index=True,
                column_config={
                    "Reasoning (AR)": st.column_config.TextColumn(width="large"),
                    "Evidence":       st.column_config.TextColumn(width="medium"),
                },
            )
        else:
            st.info("No KPI data returned.")

    with right:
        # Sentiment
        st.markdown('<div class="section-header">💭 Sentiment Analysis</div>', unsafe_allow_html=True)
        agent_s    = sa.get("agent_sentiment", {})
        customer_s = sa.get("customer_sentiment", {})

        st.markdown("**🎧 Agent**")
        agent_score = agent_s.get("score", 0) or 0
        st.progress(agent_score / 10, text=f"{agent_s.get('label','')} ({agent_score}/10)")
        st.markdown(
            native_div(agent_s.get("description_ar",""), dialect),
            unsafe_allow_html=True)

        st.markdown("**👤 Customer**")
        cust_score = customer_s.get("score", 0) or 0
        st.progress(cust_score / 10, text=f"{customer_s.get('label','')} ({cust_score}/10)")
        st.markdown(
            native_div(customer_s.get("description_ar",""), dialect),
            unsafe_allow_html=True)

        trend_icon = {"Improving":"📈","Declining":"📉","Stable":"➡️"}.get(sa.get("sentiment_trend",""),"➡️")
        st.markdown(f"**Trend:** {trend_icon} {sa.get('sentiment_trend','')}")

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
                    + flag.get("description_ar","")
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
                        native_div(tip["tip_ar"], dialect),
                        unsafe_allow_html=True)
                    st.caption(f"🇬🇧 {tip['tip_en']}")
    else:
        st.info("No coaching tips returned.")

    # ── Export ────────────────────────────────────────────
    st.divider()
    st.markdown("### 📥 Export Report")
    base      = record.get("filename","call").rsplit(".",1)[0]
    timestamp = record.get("timestamp","")[:16].replace("T","_").replace(":","")
    txt_report  = _generate_text_report(data, record.get("department",""),
                                        record.get("dialect",""), record.get("filename",""))
    json_report = json.dumps(data, ensure_ascii=False, indent=2)

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "📄 Download Text Report (.txt)",
            data=txt_report,
            file_name=f"HYDA_AQM_{base}_{timestamp}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            "🗂 Download JSON Data (.json)",
            data=json_report,
            file_name=f"HYDA_AQM_{base}_{timestamp}.json",
            mime="application/json",
            use_container_width=True,
        )


def _generate_text_report(data: dict, department: str, dialect: str, filename: str) -> str:
    cs    = data.get("call_summary", {})
    sa    = data.get("sentiment_analysis", {})
    score = cs.get("overall_score", 0)
    lines = [
        "=" * 60,
        "  HYDA AQM — CALL QUALITY ASSURANCE REPORT",
        "=" * 60,
        f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"System    : HYDA Automated Quality Monitoring",
        f"Department: {department}",
        f"Language  : {dialect}",
        f"File      : {filename}",
        "",
        f"OVERALL SCORE : {score} / 100  ({score_label(score)})",
        "",
        "─" * 60, "CALL SUMMARY", "─" * 60,
        cs.get("overview_en",""),
        f"\nNative Summary: {cs.get('overview_ar','')}",
        f"\nCall Type  : {cs.get('call_type','')}",
        f"Duration   : {cs.get('duration_estimate','')}",
        f"Resolution : {cs.get('resolution_status','')}",
        "",
        "─" * 60, "SENTIMENT ANALYSIS", "─" * 60,
        f"Agent    : {sa.get('agent_sentiment',{}).get('label','')} ({sa.get('agent_sentiment',{}).get('score','')} /10)",
        sa.get("agent_sentiment",{}).get("description_ar",""),
        f"\nCustomer : {sa.get('customer_sentiment',{}).get('label','')} ({sa.get('customer_sentiment',{}).get('score','')} /10)",
        sa.get("customer_sentiment",{}).get("description_ar",""),
        f"\nTrend    : {sa.get('sentiment_trend','')}",
        "",
        "─" * 60, "KPI SCORECARD", "─" * 60,
    ]
    for kpi in data.get("kpi_scorecard",[]):
        s = f"  Score: {kpi['score']}/10" if kpi.get("score") is not None else ""
        lines += [f"\n• {kpi['kpi_name']}", f"  Status : {kpi['status']}{s}",
                  f"  {kpi.get('reasoning_ar','')}"]
        if kpi.get("evidence"):
            lines.append(f'  Evidence: "{kpi["evidence"]}"')

    lines += ["", "─" * 60, "COACHING RECOMMENDATIONS", "─" * 60]
    for tip in data.get("coaching_tips",[]):
        lines += [f"\n[{tip['priority']}] {tip['area']}",
                  f"  AR: {tip['tip_ar']}", f"  EN: {tip['tip_en']}"]

    if data.get("compliance_flags"):
        lines += ["", "─" * 60, "COMPLIANCE FLAGS", "─" * 60]
        for flag in data["compliance_flags"]:
            lines += [f"\n[{flag['severity']}] {flag['flag']}",
                      f"  {flag.get('description_ar','')}"]

    lines += ["","=" * 60,"RAW JSON DATA","=" * 60,
              json.dumps(data, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# PAGE: USER MANAGEMENT  (Super Admin only)
# ═══════════════════════════════════════════════════════════

def show_user_management():
    st.markdown("""
    <div class="hero-banner">
        <h1>👥 User Management</h1>
        <p>Add, edit, or remove Admin accounts</p>
    </div>
    """, unsafe_allow_html=True)

    users = load_users()

    # ── Existing users table ──────────────────────────────
    st.markdown('<div class="section-header">Current Users</div>', unsafe_allow_html=True)
    for uname, udata in users.items():
        role = udata.get("role","admin")
        badge = (f'<span class="badge-super">Super Admin</span>' if role == "superadmin"
                 else f'<span class="badge-admin">Admin</span>')
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        c1.markdown(f"**{uname}**")
        c2.markdown(f"👤 {udata.get('name','')}")
        c3.markdown(badge, unsafe_allow_html=True)
        # Don't allow deleting the superadmin account
        if role != "superadmin":
            if c4.button("🗑 Remove", key=f"del_{uname}"):
                del users[uname]
                save_users(users)
                st.success(f"User '{uname}' removed.")
                st.rerun()
        else:
            c4.caption("(protected)")

    st.divider()

    # ── Add new user ──────────────────────────────────────
    st.markdown('<div class="section-header">➕ Add New User</div>', unsafe_allow_html=True)
    with st.form("add_user_form", clear_on_submit=True):
        na1, na2 = st.columns(2)
        new_name     = na1.text_input("Full Name")
        new_username = na2.text_input("Username (login ID)")
        nb1, nb2 = st.columns(2)
        new_pw       = nb1.text_input("Password", type="password")
        new_role     = nb2.selectbox("Role", ["admin", "superadmin"])
        submitted = st.form_submit_button("Create User", type="primary")

        if submitted:
            if not new_name or not new_username or not new_pw:
                st.error("Please fill in all fields.")
            elif new_username.lower() in users:
                st.error(f"Username '{new_username}' already exists.")
            else:
                users[new_username.lower()] = {
                    "password_hash": _hash(new_pw),
                    "role":          new_role,
                    "name":          new_name,
                    "created_at":    datetime.now().isoformat(),
                }
                save_users(users)
                st.success(f"✅ User '{new_username}' created successfully.")
                st.rerun()

    st.divider()

    # ── API Key Configuration ─────────────────────────────
    st.markdown('<div class="section-header">🔑 API Key Configuration</div>', unsafe_allow_html=True)
    st.caption("This key is used by all users for call analysis. Admins never see it.")

    cfg = load_config()
    current_key = cfg.get("api_key", "")
    with st.form("api_key_form", clear_on_submit=False):
        new_api_key = st.text_input(
            "HYDA AQM API Key",
            value=current_key,
            type="password",
            placeholder="Enter API key…",
        )
        ak1, ak2 = st.columns([2, 1])
        save_key = ak1.form_submit_button("💾 Save API Key", type="primary")
        test_key = ak2.form_submit_button("🔍 Test Connection")

        if save_key:
            if not new_api_key:
                st.error("API key cannot be empty.")
            else:
                cfg["api_key"] = new_api_key
                save_config(cfg)
                st.session_state["api_key"] = new_api_key
                st.success("✅ API key saved successfully.")

        if test_key:
            key_to_test = new_api_key or current_key
            if not key_to_test:
                st.warning("Enter an API key first.")
            else:
                with st.spinner("Checking connection…"):
                    try:
                        _tc  = genai.Client(api_key=key_to_test)
                        _all = list(_tc.models.list())
                        _gem = [m.name for m in _all
                                if "gemini" in m.name.lower()
                                and "generateContent" in (
                                    getattr(m, "supported_actions", [])
                                    or getattr(m, "supported_generation_methods", [])
                                )]
                        if _gem:
                            st.success(f"✅ Connection successful — {len(_gem)} analysis models available.")
                        else:
                            st.warning("⚠️ Key valid but no analysis models found.")
                    except Exception as _e:
                        st.error(f"❌ Connection failed: {str(_e)}")

    st.divider()

    # ── Change Password ───────────────────────────────────
    st.markdown('<div class="section-header">🔑 Change Password</div>', unsafe_allow_html=True)
    with st.form("change_pw_form", clear_on_submit=True):
        target_user = st.selectbox("Select User", list(users.keys()))
        cp1, cp2   = st.columns(2)
        new_pw1    = cp1.text_input("New Password", type="password")
        new_pw2    = cp2.text_input("Confirm Password", type="password")
        if st.form_submit_button("Update Password", type="primary"):
            if not new_pw1:
                st.error("Password cannot be empty.")
            elif new_pw1 != new_pw2:
                st.error("Passwords do not match.")
            else:
                users[target_user]["password_hash"] = _hash(new_pw1)
                save_users(users)
                st.success(f"✅ Password updated for '{target_user}'.")


# ═══════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═══════════════════════════════════════════════════════════

def render_sidebar():
    user = st.session_state.get("user", {})
    role = user.get("role","admin")

    with st.sidebar:
        # Logo + brand
        st.markdown("""
        <div style="text-align:center; padding: 10px 0 16px;">
            <div style="font-size:36px;">📊</div>
            <div style="font-size:20px; font-weight:700; letter-spacing:1px;">HYDA AQM</div>
            <div style="font-size:11px; color:#a8c8e8;">Automated Quality Monitoring</div>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        # User info
        badge_html = (
            '<span class="badge-super">Super Admin</span>' if role == "superadmin"
            else '<span class="badge-admin">Admin</span>'
        )
        st.markdown(
            f"👤 **{user.get('name', user.get('username',''))}**<br>"
            f"{badge_html}",
            unsafe_allow_html=True,
        )
        st.divider()

        # Navigation
        st.markdown("### Navigation")
        current_page = st.session_state.get("page","dashboard")

        if st.button("📊  Dashboard", use_container_width=True,
                     type="primary" if current_page=="dashboard" else "secondary"):
            st.session_state["page"] = "dashboard"
            st.rerun()

        if st.button("➕  New Analysis", use_container_width=True,
                     type="primary" if current_page=="new_analysis" else "secondary"):
            st.session_state["page"] = "new_analysis"
            st.rerun()

        if role == "superadmin":
            if st.button("👥  User Management", use_container_width=True,
                         type="primary" if current_page=="user_management" else "secondary"):
                st.session_state["page"] = "user_management"
                st.rerun()

        st.divider()

        # API key status
        _cfg_key = load_config().get("api_key", "") or st.session_state.get("api_key", "")
        _user_role = st.session_state.get("user", {}).get("role", "admin")
        if _cfg_key:
            st.success("🟢 System Ready")
        elif _user_role == "superadmin":
            st.warning("⚠️ API Key not configured\n\nSet it in **User Management → API Key**.")
        else:
            st.warning("⚠️ System not ready\n\nContact your Super Admin.")

        st.divider()

        # Logout
        if st.button("🚪 Sign Out", use_container_width=True):
            for key in ["logged_in","user","page","selected_call","api_key"]:
                st.session_state.pop(key, None)
            st.rerun()

        st.caption("v2.0 · HYDA AQM · Arabic QA")


# ═══════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════

def main():
    # Initialise session state
    if "page" not in st.session_state:
        st.session_state["page"] = "dashboard"

    # Not logged in → show login page
    if not st.session_state.get("logged_in"):
        show_login_page()
        return

    # Logged in → render sidebar + page
    render_sidebar()

    page = st.session_state.get("page","dashboard")
    user_role = st.session_state.get("user",{}).get("role","admin")

    if page == "dashboard":
        show_dashboard()
    elif page == "new_analysis":
        show_new_analysis()
    elif page == "call_detail":
        show_call_detail()
    elif page == "user_management":
        if user_role == "superadmin":
            show_user_management()
        else:
            st.error("⛔ Access denied. Super Admin only.")
    else:
        show_dashboard()


if __name__ == "__main__" or True:
    main()
