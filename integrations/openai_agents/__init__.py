"""Traccia integration for OpenAI Agents SDK."""

from typing import Optional

_installed = False


def install(enabled: Optional[bool] = None) -> bool:
    """
    Install Traccia tracing for OpenAI Agents SDK.
    
    This registers a TracingProcessor with the Agents SDK that captures
    agent runs, tool calls, handoffs, and LLM generations as Traccia spans.
    
    Args:
        enabled: If False, skip installation. If None, check config.
        
    Returns:
        True if installed successfully, False otherwise.
        
    Example:
        ```python
        from traccia import init
        from traccia.integrations.openai_agents import install
        
        init()
        install()  # Register Agents SDK tracing
        ```
    
    Note:
        This is automatically called by `traccia.init()` when the `openai-agents`
        package is installed, unless disabled via config.
    """
    global _installed
    
    if _installed:
        return True
    
    # Check if explicitly disabled
    if enabled is False:
        return False
    
    # Check config if not explicitly enabled
    if enabled is None:
        from traccia import runtime_config
        # Check if disabled in config
        if runtime_config.get_config_value("openai_agents") is False:
            return False
    
    try:
        # Import Agents SDK components
        from agents import add_trace_processor
        from agents.tracing import TracingProcessor
        
        # Import our processor
        from traccia.integrations.openai_agents.processor import TracciaAgentsTracingProcessor
        
        # Register the processor
        processor = TracciaAgentsTracingProcessor()
        add_trace_processor(processor)
        
        _installed = True
        return True
        
    except ImportError:
        # Agents SDK not installed, skip silently
        return False
    except Exception:
        # Other errors, fail silently to avoid breaking app startup
        return False


__all__ = ["install"]
