from langchain_core.messages import HumanMessage, SystemMessage

from rosa_agent.agent import create_agent, create_llm
from rosa_agent.action_tools import (
    cancel_current_task,
    get_weather_advice,
    navigate_to_named_place,
    query_robot_state,
    dispense_medicine,
    speak_text,
    start_following_task,
    start_inspection_task,
    start_wakeup_task,
)


LOCATION_ALIASES = {
    "bedroom_bedside": ("bedroom_bedside", "卧室", "床边", "老人房", "卧室床边"),
    "livingroom_sofa": ("livingroom_sofa", "living_room_sofa", "客厅", "沙发", "客厅沙发"),
    "charger": ("charger", "充电", "充电桩", "回充", "回去充电", "去充电", "回到充电桩"),
    "kitchen": ("kitchen", "厨房"),
}

DEFAULT_WEATHER_LOCATION = "成都"

GENERAL_CHAT_SYSTEM_PROMPT = (
    "你是养老陪伴机器人 ROSA 的自然语言对话模块。"
    "当用户只是问候、闲聊、表达情绪、询问你的感受、让你陪聊、讲故事或回答常识问题时，"
    "请像普通语义大模型一样自然、简洁、温和地中文回复。"
    "不要声称已经查询机器人状态，不要提到 ROS 工具、节点或系统日志，"
    "也不要主动建议启动机器人任务，除非用户明确提出机器人任务需求。"
)

GENERAL_CHAT_KEYWORDS = (
    "你好",
    "您好",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "晚安",
    "谢谢",
    "感谢",
    "辛苦",
    "感觉怎么样",
    "你怎么样",
    "你好吗",
    "你还好吗",
    "你是谁",
    "介绍一下你",
    "陪我聊",
    "聊天",
    "讲个故事",
    "讲笑话",
    "开心",
    "难过",
    "无聊",
    "害怕",
    "想你",
)

ROBOT_CONTEXT_KEYWORDS = (
    "机器人",
    "小车",
    "底盘",
    "导航",
    "任务",
    "状态",
    "节点",
    "日志",
    "启动",
    "运行",
    "系统",
    "服务",
    "ros",
    "ros2",
    "rviz",
    "nav2",
    "雷达",
    "地图",
    "定位",
    "跟随",
    "巡检",
    "叫醒",
    "取消",
    "停止",
    "充电",
    "药",
    "药盒",
    "吃药",
    "取药",
    "天气",
    "气温",
    "下雨",
)


def _extract_weather_location(text: str) -> str:
    cleaned = text.strip()
    for token in (
        "今天",
        "明天",
        "现在",
        "当前",
        "天气",
        "气温",
        "温度",
        "下雨",
        "降雨",
        "会不会",
        "怎么样",
        "如何",
        "吗",
        "？",
        "?",
    ):
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.strip(" ，,。.")
    return cleaned or DEFAULT_WEATHER_LOCATION


def _extract_medicine_name(text: str) -> str:
    cleaned = text.strip()
    for token in (
        "小智",
        "小志",
        "请",
        "帮我",
        "给我",
        "拿",
        "取",
        "打开",
        "转到",
        "需要",
        "我要",
        "吃",
        "药盒",
        "药物",
        "药品",
        "药",
        "一下",
        "。",
        "，",
        ",",
        "？",
        "?",
    ):
        cleaned = cleaned.replace(token, "")
    return cleaned.strip(" ：:，,。.")


def _invoke_tool(tool_func, tool_input: str = "") -> str:
    return str(tool_func.invoke(tool_input))


def _normalize_text(text: str) -> str:
    return text.strip().lower().replace(" ", "").replace("-", "_")


def is_general_chat(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    if any(word in normalized for word in ROBOT_CONTEXT_KEYWORDS):
        return False

    if any(word in normalized for word in GENERAL_CHAT_KEYWORDS):
        return True

    if len(normalized) <= 18 and any(word in normalized for word in ("你", "我")):
        return True

    return False


def should_use_tool_agent(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(word in normalized for word in ROBOT_CONTEXT_KEYWORDS)


def reply_general_chat(text: str, llm=None) -> str:
    chat_llm = llm or create_llm()
    response = chat_llm.invoke(
        [
            SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT),
            HumanMessage(content=text),
        ]
    )
    return str(response.content).strip()


def reply_to_user(text: str, agent=None, llm=None) -> str:
    direct_reply = route_high_level_command(text)
    if direct_reply is not None:
        return direct_reply

    if is_general_chat(text) or not should_use_tool_agent(text):
        return reply_general_chat(text, llm=llm)

    tool_agent = agent or create_agent()
    return str(tool_agent.invoke(text))


def route_high_level_command(text: str) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    if any(word in normalized for word in ("取消", "停止", "停下", "cancel")):
        return _invoke_tool(cancel_current_task)

    if any(word in normalized for word in ("状态", "现在在哪", "当前任务", "忙不忙", "state", "status")):
        return _invoke_tool(query_robot_state)

    if any(word in normalized for word in ("叫醒", "起床", "wake")):
        return _invoke_tool(start_wakeup_task)

    if any(word in normalized for word in ("跟随", "跟着", "follow")):
        return _invoke_tool(start_following_task)

    if any(word in normalized for word in ("巡检", "找人", "找老人", "inspection")):
        return _invoke_tool(start_inspection_task)

    if any(word in normalized for word in ("药", "药盒", "吃药", "取药", "拿药")):
        medicine_name = _extract_medicine_name(text)
        if medicine_name:
            return _invoke_tool(dispense_medicine, medicine_name)
        return "请告诉我需要哪一种药。"

    if any(word in normalized for word in ("天气", "气温", "温度", "下雨", "降雨", "雨")):
        return _invoke_tool(get_weather_advice, _extract_weather_location(text))

    if normalized.startswith(("说", "播报", "告诉")):
        for prefix in ("播报", "告诉", "说"):
            if normalized.startswith(prefix):
                speech = text.strip()[len(prefix):].strip(" ：:，,")
                if speech:
                    return _invoke_tool(speak_text, speech)
        return None

    if any(word in normalized for word in ("去", "到", "导航", "回")):
        for place_name, aliases in LOCATION_ALIASES.items():
            if any(alias.lower().replace(" ", "").replace("-", "_") in normalized for alias in aliases):
                return _invoke_tool(navigate_to_named_place, place_name)

    return None


def main() -> None:
    agent = create_agent()
    llm = create_llm()

    while True:
        q = input("\nROSA> ").strip()

        if q in {"exit", "quit"}:
            break

        if q in {"/new", "new", "新对话"}:
            agent = create_agent()
            llm = create_llm()
            print("已开始新对话。")
            continue

        print(reply_to_user(q, agent=agent, llm=llm))


if __name__ == "__main__":
    main()
