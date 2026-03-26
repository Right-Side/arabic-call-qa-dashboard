# 📞 Automated Call QA Dashboard

> **AI-powered Quality Assurance for Arabic Call Centres**
> Powered by HYDA AQM

---

## ✨ Overview

Upload an Arabic call recording (MP3/WAV/AAC), define your KPIs, and get a full QA scorecard in under 30 seconds — in both Arabic and English.

The dashboard analyses:
- **KPI Compliance** — custom Pass/Fail criteria with Arabic reasoning
- **Sentiment** — agent vs. customer emotional tone (scored 1–10)
- **Compliance Flags** — critical issues flagged by severity
- **Coaching Tips** — prioritised recommendations for agent improvement
- **Export** — download reports as `.txt` or `.json`

---

## 🖼️ Dashboard Preview

```
┌─────────────────────────────────────────────────────────────┐
│  🎯 Score: 84/100  ⏱ ~5 min  📂 Complaint  ✅ Resolved     │
├───────────────────────────────┬─────────────────────────────┤
│  📝 Call Summary (EN + AR)    │  💭 Sentiment Analysis      │
│  ✅ KPI Scorecard Table       │  🚨 Compliance Flags        │
├───────────────────────────────┴─────────────────────────────┤
│  💡 Coaching Recommendations  (High / Medium / Low)         │
│  📥 Download Text Report  |  📥 Download JSON               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-org/arabic-call-qa-dashboard.git
cd arabic-call-qa-dashboard
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

```bash
streamlit run app.py
```

### 4. Open in your browser

The app opens automatically at `http://localhost:8501`

---

## 🔑 API Key

The app requires a **Google AI Studio API key** with access to Gemini 1.5 Pro.

1. Go to [https://aistudio.google.com/](https://aistudio.google.com/)
2. Click **Get API Key → Create API key**
3. Paste it into the sidebar when you run the app

> The key is **never stored** — it lives only in the Streamlit session.

---

## ⚙️ Features

| Feature | Details |
|---|---|
| **Dialects** | MSA, Egyptian, Gulf, Levantine, Maghrebi |
| **Departments** | Sales, Customer Service, Collections, Technical Support |
| **Code-switching** | Arabic + English mixed speech handled natively |
| **Custom KPIs** | Define any criteria — the prompt adapts dynamically |
| **Audio formats** | MP3, WAV, AAC, M4A, OGG, FLAC |
| **Export** | `.txt` (human-readable) + `.json` (structured data) |

---

## 📁 Project Structure

```
arabic-call-qa-dashboard/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

---

## 🔒 Security Notes

- API keys are entered at runtime and are **not persisted** anywhere
- Audio files are uploaded to the Gemini File API and automatically deleted after processing
- Do **not** commit `.env` files or `secrets.toml` containing API keys

---

## 📦 Dependencies

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | ≥ 1.35 | Web UI framework |
| `google-generativeai` | ≥ 0.7 | Gemini 1.5 Pro API |
| `pandas` | ≥ 2.0 | KPI scorecard table |

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "Add my feature"`
4. Push and open a Pull Request

---

## 📄 Licence

MIT Licence — free to use, modify, and distribute.

---

*Built as a client prototype. Subject to change based on feedback.*
