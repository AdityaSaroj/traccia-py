"""Traccia integration for CrewAI."""

from typing import Optional

_installed = False


def install(enabled: Optional[bool] = None) -> bool:
    """
    Install Traccia tracing for CrewAI.
    
    This instruments CrewAI's core components (Crew, Task, Agent, LLM) to capture
    crew executions, task runs, agent steps, and LLM calls as Traccia spans.
    
    Args:
        enabled: If False, skip installation. If None, check config.
        
    Returns:
        True if installed successfully, False otherwise.
        
    Example:
        ```python
        from traccia import init
        from traccia.integrations.crewai import install
        
        init()
        install()  # Register CrewAI tracing
        ```
    
    Note:
        This is automatically called by `traccia.init()` when the `crewai`
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
        if runtime_config.get_config_value("crewai") is False:
            return False
    
    try:
        # Check if CrewAI is installed
        import crewai
        
        # Import our instrumentation
        from traccia.integrations.crewai.instrumentation import instrument_crewai
        
        # Install the instrumentation
        instrument_crewai()
        
        _installed = True
        return True
        
    except ImportError:
        # CrewAI not installed, skip silently
        return False
    except Exception:
        # Other errors, fail silently to avoid breaking app startup
        return False


__all__ = ["install"]
