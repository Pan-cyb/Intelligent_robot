from langchain_openai import ChatOpenAI
from rosa import ROSA

from rosa_agent.action_tools import DEFAULT_TOOLS
from rosa_agent.config import llm_config


def create_llm() -> ChatOpenAI:
    config = llm_config()
    kwargs = {
        "model": config.model,
        "temperature": config.temperature,
        "api_key": config.api_key,
    }

    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)


def create_agent() -> ROSA:
    return ROSA(
        ros_version=2,
        llm=create_llm(),
        verbose=True,
        streaming=False,
        blacklist=["/rosout", "/parameter_events"],
        tools=DEFAULT_TOOLS,
    )

