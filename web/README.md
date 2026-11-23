# Daily 10: web app (Next.js)

Same look as EventSnap (the AI Event Photo Discovery Platform): sticker cards and buttons,
flat colour blocks, Baloo 2 + Nunito, and the Snappy mascot with study poses.

**Two logins**
- **Students** (`/auth/student`): sign up with a name and reminder time, or log in with their
  6-character code. Mobile-first and installable (PWA): open in the phone browser and tap
  **Add to Home Screen**.
- **Faculty / university** (`/auth/faculty`): email + password accounts. Creating one needs
  the university invite code (`STUDY_ADMIN_KEY` on the server); passwords are scrypt-hashed and
  logins are expiring tokens.

**Student screens:** Today (concept card → one question at a time with instant feedback and
the quote from the notes → past exam question), Progress (streak, accuracy, syllabus covered,
topics to practise), Me (subjects and exam dates, reminder time, Telegram link, code).

**Faculty screens:** subjects dashboard and new subject; per subject, Topics (with how often each
was asked in past papers), Upload & generate (drag-and-drop notes and past papers, generate
summaries and questions in batches) and Review (approve / reject, with the quote from the notes).

```bash
# 1. Backend (repo root)
uvicorn app.main:app --port 8000

# 2. This app
cd web
npm install
npm run dev            # http://localhost:3000, also on your Wi-Fi: http://<laptop-ip>:3000
```

The browser only talks to this server: `/api/*` is proxied to the FastAPI backend
(`API_URL`, default `http://localhost:8000`), so phones on the same Wi-Fi need one address and
no CORS setup. Optional: `NEXT_PUBLIC_TELEGRAM_BOT=<bot username>` shows a one-tap Telegram link.

Installing as an app (service worker, full-screen) needs HTTPS, so on a phone it works once
deployed (e.g. Vercel for this app plus any host for the API) or through a tunnel such as
`cloudflared tunnel --url http://localhost:3000`. Over plain Wi-Fi it runs as a normal web page.


