"""Tiny helpers that create the model clients. Imports are lazy so the offline
tests and the guardrail/tool demos run without an API key or the openai package."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional for offline use
    pass

MODEL = os.getenv("APEXDESK_MODEL", "gpt-4o-mini")


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing. Copy .env.example to .env and add your key.")
    return key


def get_client():
    """Plain OpenAI client: used for chat and tool calling."""
    key = _api_key()
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("The openai package is missing. Run: pip install -r requirements.txt")
    return OpenAI(api_key=key)


def get_structured_client():
    """OpenAI client wrapped by Instructor: used when you pass a Pydantic response_model."""
    client = get_client()
    try:
        import instructor
    except ImportError:
        raise RuntimeError("The instructor package is missing. Run: pip install -r requirements.txt")
    return instructor.from_openai(client)
