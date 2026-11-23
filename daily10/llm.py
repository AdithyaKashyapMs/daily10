"""
LLM access (Groq): JSON mode, a model fallback chain, and reasoning text switched off.

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
