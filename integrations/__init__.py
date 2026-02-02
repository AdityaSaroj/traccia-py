"""Traccia integrations for frameworks like LangChain, OpenAI Agents SDK."""

__all__ = []

# Lazy imports for optional dependencies
def _import_langchain():
    try:
        from traccia.integrations.langchain import TracciaCallbackHandler
        return TracciaCallbackHandler
    except ImportError as e:
        raise ModuleNotFoundError(
            "LangChain integration requires langchain-core. "
            "Install with: pip install traccia[langchain]"
        ) from e


def _import_openai_agents():
    try:
        from traccia.integrations.openai_agents import install
        return install
    except ImportError as e:
        raise ModuleNotFoundError(
            "OpenAI Agents integration requires openai-agents. "
            "Install with: pip install openai-agents"
        ) from e


# Make available if imported
try:
    from traccia.integrations.langchain import TracciaCallbackHandler
    __all__.append("TracciaCallbackHandler")
except ImportError:
    pass

try:
    from traccia.integrations.openai_agents import install as install_openai_agents
    __all__.append("install_openai_agents")
except ImportError:
    pass
