from rosa_agent.agent import create_agent
from rosa_agent.action_tools import (
    cancel_current_task,
    navigate_to_named_place,
    query_robot_state,
    speak_text,
    start_wakeup_task,
)


LOCATION_ALIASES = {
    "bedroom_bedside": ("bedroom_bedside", "卧室", "床边", "老人房", "卧室床边"),
    "livingroom_sofa": ("livingroom_sofa", "living_room_sofa", "客厅", "沙发", "客厅沙发"),
    "charger": ("charger", "充电", "充电桩", "回充", "回去充电", "去充电", "回到充电桩"),
    "kitchen": ("kitchen", "厨房"),
}


def _invoke_tool(tool_func, tool_input: str = "") -> str:
    return str(tool_func.invoke(tool_input))


def route_high_level_command(text: str) -> str | None:
    normalized = text.strip().lower().replace(" ", "").replace("-", "_")
    if not normalized:
        return None

    if any(word in normalized for word in ("取消", "停止", "停下", "cancel")):
        return _invoke_tool(cancel_current_task)

    if any(word in normalized for word in ("状态", "现在在哪", "当前任务", "忙不忙", "state", "status")):
        return _invoke_tool(query_robot_state)

    if any(word in normalized for word in ("叫醒", "起床", "wake")):
        return _invoke_tool(start_wakeup_task)

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

    while True:
        q = input("\nROSA> ").strip()

        if q in {"exit", "quit"}:
            break

        if q in {"/new", "new", "新对话"}:
            agent = create_agent()
            print("已开始新对话。")
            continue

        direct_reply = route_high_level_command(q)
        if direct_reply is not None:
            print(direct_reply)
            continue

        print(agent.invoke(q))


if __name__ == "__main__":
    main()
