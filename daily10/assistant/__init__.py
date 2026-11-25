"""
The in-app assistant: one agent engine, two personas.

  Study Buddy (students)      tutoring from the notes, quizzes that feed spaced repetition,
                              "am I on track?" plans, exam prep from past papers, settings
  Faculty Copilot (faculty)   review queue with a reviewer sub-agent, class reports, remedial
                              questions with a writer sub-agent, coverage checks, subject setup

  registry.py       tools: role, arguments, approval, timeline label; validating and running them
  shared_tools.py   plan + retrieval (both roles)
  student_tools.py  / faculty_tools.py
  prompts.py        personas and workflows
  engine.py         the chat agent loop (streaming, approvals, citations, memory)
  subagents.py      headless specialist agents on the same tools: researcher, reviewer, writer
  citations.py      citation checks every agent shares
  store.py          conversations, messages, pending approvals
"""

from daily10.assistant.engine import Assistant, AssistantUnavailable  # noqa: F401
from daily10.assistant.registry import Context  # noqa: F401
