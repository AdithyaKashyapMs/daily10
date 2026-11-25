import os
import sys

os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.pop("STUDY_ADMIN_KEY", None)
os.environ.pop("STUDY_STUDENT_EMAIL_DOMAINS", None)
os.environ.pop("SMTP_HOST", None)
os.environ.pop("STUDY_ENV", None)
os.environ["STUDY_TIMEZONE"] = "local"   # tests compare with date.today()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Run the whole suite against Postgres with e.g.
#   TEST_DATABASE_URL=postgresql+psycopg://daily10:daily10@localhost:5433/daily10_test pytest -q tests
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")


def fresh_database():
    from daily10 import db

    db.init(TEST_DATABASE_URL, reset=not TEST_DATABASE_URL.startswith("sqlite://"))
