"""
Tool registry: the one set of tools every agent uses (the chat assistant and its sub-agents).

A tool is a plain function plus what an agent loop needs to use it safely:
  - roles:   who may use it ("student", "faculty"); the model is only shown its role's tools
  - args:    a Pydantic model; the model's arguments are validated, and errors are sent back so
             the model can correct itself
  - confirm: changes data, so it runs only after the user approves it in the chat
  - label:   what the timeline shows while it runs ("Searching CC701 notes for 'cron'")
  - summary: what the approval card says ("Approve 3 questions: #12, #13, #14")
  - ui:      the result also drives a card in the chat (quiz, answer feedback, plan)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from daily10 import service

log = logging.getLogger(__name__)


@dataclass
class Context:
    """Who is chatting. Tools act only as this person."""

    role: str                       # student | faculty
    actor: str                      # display name, recorded on changes
    owner_id: int                   # student.id or faculty.id
    student_code: str | None = None
    llm_factory: Callable[[str], Any] | None = None     # JSON-mode models for one-shot jobs: "main" | "judge"
    model_factory: Callable[[str], Any] | None = None   # tool-calling models for sub-agents: "main" | "judge"
    scratch: dict = field(default_factory=dict)

    def llm(self, kind: str = "main"):
        if self.llm_factory is None:
            from daily10 import config
            from daily10.llm import get_json_llm

            return get_json_llm(models=[config.JUDGE_MODEL, *config.FALLBACK_MODELS]) if kind == "judge" else get_json_llm()
        return self.llm_factory(kind)

    def agent_model(self, kind: str = "main"):
        """A chat model a sub-agent binds its own tools to (.bind_tools(schemas, tool_choice=...))."""
        if self.model_factory is None:
            from daily10.llm import get_agent_model

            return get_agent_model(kind)
        return self.model_factory(kind)


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    roles: frozenset[str]
    fn: Callable[[Context, Any], dict]
    confirm: bool = False
    label: Callable[[Any], str] | None = None
    summary: Callable[[Any], str] | None = None
    ui: str | None = None

    def schema(self) -> dict:
        params = self.args.model_json_schema()
        _strip_titles(params)
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": params}}

    def describe_call(self, args) -> str:
        return self.label(args) if self.label else self.name.replace("_", " ")


TOOLS: dict[str, Tool] = {}


class NoArgs(BaseModel):
    pass


def tool(name: str, roles: set[str], args: type[BaseModel] = NoArgs, confirm: bool = False,
         label=None, summary=None, ui: str | None = None):
    """Register a function as an assistant tool. Its docstring is the model-facing description."""

    def wrap(fn):
        if name in TOOLS:
            raise ValueError(f"Tool {name} is already registered")
        TOOLS[name] = Tool(name=name, description=" ".join((fn.__doc__ or "").split()), args=args,
                          roles=frozenset(roles), fn=fn, confirm=confirm, label=label, summary=summary, ui=ui)
        return fn
    return wrap


def tools_for(role: str) -> dict[str, Tool]:
    return {t.name: t for t in TOOLS.values() if role in t.roles}


# --- Running a tool: shared by every agent loop ---------------------------------------------

def parse_args(tool: Tool, raw: dict) -> tuple[BaseModel | None, str | None]:
    """(validated args, None) or (None, an error the model can act on)."""
    try:
        return tool.args.model_validate(raw or {}), None
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}" for err in e.errors())
        return None, f"Invalid arguments ({problems}). Fix them and call again."


def execute(tool: Tool, ctx: Context, args) -> tuple[dict, bool]:
    """Run a tool. Expected failures become an error result for the model; nothing escapes."""
    try:
        return tool.fn(ctx, args), True
    except (service.NotFound, ValueError, PermissionError, LookupError) as e:
        return {"error": str(e)}, False
    except Exception as e:  # a bug or an outage in a sub-agent: report it, keep the caller alive
        log.exception(f"Tool {tool.name} failed")
        return {"error": f"{tool.name} failed ({type(e).__name__}). Try again or take another route."}, False


def summarize(result: dict) -> str:
    """One line for the timeline / a sub-agent's trace."""
    if "error" in result:
        return str(result["error"])[:160]
    if "declined" in result:
        return "declined"
    for key, noun in (("passages", "passage"), ("questions", "question"), ("subjects", "subject"), ("created", "draft")):
        if isinstance(result.get(key), list):
            n = len(result[key])
            return f"{n} {noun}{'' if n == 1 else 's'}" + (" saved" if key == "created" else "")
    if "recommendation" in result:
        return f"recommends: {result['recommendation']}"
    if "correct" in result:
        return "correct" if result["correct"] else "not quite"
    if "updated" in result:
        return f"{len(result['updated'])} updated"
    if "question" in result:
        return "question ready" if result["question"] else "no question available"
    return "done"


def _strip_titles(schema: Any) -> None:
    """Pydantic adds a "title" to every field; the model doesn't need them (fewer tokens)."""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for v in schema.values():
            _strip_titles(v)
    elif isinstance(schema, list):
        for v in schema:
            _strip_titles(v)
