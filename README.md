# Personal Super Agent V1

Build a device-agnostic "Super Agent" (V1) that manages family logistics, complex tasks, and "Deep Context" (Custody Schedules) via Voice (Twilio) and Text.

## Technical Stack

- **Frontend/API:** Next.js 14+ (App Router) on Vercel
- **Backend Logic:** Python 3.11+ with LangGraph (for the Agent State Machine)
- **Database:** Supabase (Postgres + pgvector)
- **Voice/Text:** Twilio API + OpenAI Whisper (via Vercel Blob for storage)
- **LLM:** Anthropic Claude 3.5 Sonnet (Logic) + GPT-4o-Mini (Routing)

## Project Structure

```
/
├── src/                    # Next.js source code
│   ├── app/               # Next.js App Router pages
│   └── components/        # React components
├── lib/
│   ├── agent/            # Python LangGraph agent code
│   └── skills/           # Skill Registry (modular tools)
│       ├── weather/      # Example: Weather skill
│       └── custody/      # Example: Custody schedule skill
└── requirements.txt       # Python dependencies
```

## Getting Started

### Frontend (Next.js)

```bash
npm install
npm run dev
```

### Backend (Python Agent)

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env.local` and fill in your API keys.
