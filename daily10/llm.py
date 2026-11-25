"""
LLM access (Groq): a model fallback chain and reasoning text switched off, in two forms:
JSON mode for one-shot jobs (generation, checks) and native tool calling for agents.

JSON mode makes the provider return one JSON object, which Pydantic then validates.
Reasoning models (gpt-oss, Qwen) can put their chain of thought in the reply; it is turned
off so callers get only the answer.
"""

from langchain_groq import ChatGroq

from daily10 import config


def _reasoning_off(model: str) -> dict:
    name = model.lower()
    if "gpt-oss" in name:
        return {"model_kwargs": {"include_reasoning": False}}
    if any(k in name for k in ("qwen", "deepseek")):
        return {"reasoning_format": "hidden"}
    return {}


def _models(models: list[str], temperature: float) -> list[ChatGroq]:
    keys = [k for k in (config.GROQ_API_KEY, config.GROQ_FALLBACK_API_KEY) if k]
    if not keys:
        raise RuntimeError("Set GROQ_API_KEY in .env (free key from console.groq.com).")
    chain = list(dict.fromkeys(models))
    return [ChatGroq(api_key=k, model=m, temperature=temperature, max_retries=1, **_reasoning_off(m))
            for m in chain for k in keys]


def get_json_llm(models: list[str] | None = None, temperature: float = 0.0):
    """Chat model in JSON mode, falling back across keys and models."""
    bound = [m.bind(response_format={"type": "json_object"})
             for m in _models(models or [config.MODEL, *config.FALLBACK_MODELS], temperature)]
    return bound[0] if len(bound) == 1 else bound[0].with_fallbacks(bound[1:])


class AgentModel:
    """A fallback chain of chat models that an agent binds its own tools to."""

    def __init__(self, models: list[ChatGroq]):
        self.models = models

    def bind_tools(self, tools: list[dict], tool_choice: str | None = None):
        bound = [m.bind_tools(tools, tool_choice=tool_choice) for m in self.models]
        return bound[0] if len(bound) == 1 else bound[0].with_fallbacks(bound[1:])


def get_agent_model(kind: str = "main", temperature: float = 0.0) -> AgentModel:
    """Tool-calling models for an agent. "judge" leads with a different model family (independent review)."""
    first = config.JUDGE_MODEL if kind == "judge" else config.MODEL
    return AgentModel(_models([first, *config.FALLBACK_MODELS], temperature))


def get_tool_llm(tools: list[dict], temperature: float = 0.0):
    """Chat model with native tool calling (for the assistant), falling back across keys and models."""
    return get_agent_model("main", temperature).bind_tools(tools)
