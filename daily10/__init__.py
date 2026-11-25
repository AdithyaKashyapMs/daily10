"""
Daily 10: ten minutes of study a day for the whole semester, instead of cramming.

Faculty upload a subject's notes (and past papers); the system splits them into daily
topics and generates questions grounded in the notes, which faculty approve. Each student
gets one short session a day (concept card, new questions, spaced-repetition reviews and a
past-paper question), scheduled so the whole syllabus is covered before the exam, and a
reminder at the time they choose.

  db.py         data model (SQLAlchemy; SQLite locally, Postgres via STUDY_DATABASE_URL)
  content.py    notes -> topics; past papers -> exam weight per topic
  generate.py   topic -> summary + questions (LLM, JSON schema), grounded in the notes
  scheduler.py  what to study today: coverage plan + Leitner spaced repetition
  service.py    the operations the API and UI use
  api.py        FastAPI routes under /study
  notify.py     Telegram reminders
  student_auth.py  student sign-in: college email + emailed code, device tokens
  mailer.py     sign-in code emails (SMTP)
  cli.py        setup commands for faculty/admins
  mcp_server.py faculty tools for MCP clients (Claude, Cursor): data, review, agentic RAG
  assistant/    agents: the chat assistant (engine.py) and its sub-agents (subagents.py)
  retrieval.py  passage search over notes and past papers
  insights.py   subject overview, question detail, class analytics
"""
