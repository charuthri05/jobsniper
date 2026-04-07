"""
AI provider abstraction layer.

Supports OpenAI and Anthropic as interchangeable backends.
Reads AI_PROVIDER, AI_MODEL, and the corresponding API key from environment.
"""

import os

from dotenv import load_dotenv
load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL = os.getenv("AI_MODEL", "")

# Smart defaults per provider
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5-20250514",
}

if AI_PROVIDER not in _DEFAULT_MODELS:
    raise ValueError(
        f"Invalid AI_PROVIDER='{AI_PROVIDER}'. Must be one of: {', '.join(_DEFAULT_MODELS)}"
    )

if not AI_MODEL:
    AI_MODEL = _DEFAULT_MODELS[AI_PROVIDER]


def _get_openai_client():
    """Lazily import and instantiate the OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Add it to your .env file or export it in your shell."
        )
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "The 'openai' package is not installed. Run: pip install openai"
        )
    return OpenAI(api_key=api_key)


def _get_anthropic_client():
    """Lazily import and instantiate the Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file or export it in your shell."
        )
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        )
    return anthropic.Anthropic(api_key=api_key)


# Cache the client so we don't re-instantiate on every call
_client_cache = {}


def _get_client():
    """Return the cached client for the configured provider."""
    if AI_PROVIDER not in _client_cache:
        if AI_PROVIDER == "openai":
            _client_cache[AI_PROVIDER] = _get_openai_client()
        else:
            _client_cache[AI_PROVIDER] = _get_anthropic_client()
    return _client_cache[AI_PROVIDER]


def chat_completion(system: str, user_message: str, max_tokens: int = 300) -> str:
    """
    Send a chat completion request to the configured AI provider.

    Args:
        system: The system prompt / persona.
        user_message: The user message content.
        max_tokens: Maximum tokens in the response.

    Returns:
        The raw text response from the model.
    """
    client = _get_client()

    if AI_PROVIDER == "openai":
        response = client.chat.completions.create(
            model=AI_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content.strip()

    else:  # anthropic
        response = client.messages.create(
            model=AI_MODEL,
            system=system,
            messages=[
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
        )
        return response.content[0].text.strip()


def get_provider_info() -> dict:
    """
    Return current AI provider configuration for display purposes.

    Returns:
        Dict with 'provider' and 'model' keys.
    """
    return {
        "provider": AI_PROVIDER,
        "model": AI_MODEL,
    }
