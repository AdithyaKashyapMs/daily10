import os
import sys

os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.pop("STUDY_ADMIN_KEY", None)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
