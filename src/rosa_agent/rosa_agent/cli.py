from rosa_agent.agent import create_agent


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

        print(agent.invoke(q))


if __name__ == "__main__":
    main()

