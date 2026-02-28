import json
import os
import sys

from anthropic import Anthropic

from spend_tracking.lambdas.services.agent import (
    SYSTEM_PROMPT,
    build_tools,
    extract_text,
    run_agent,
)

# ANSI color codes
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


def _header(label: str, color: str = CYAN) -> str:
    return f"\n{color}{BOLD}── {label} {'─' * (50 - len(label))}{RESET}"


def _trace_tools(tools: list) -> None:
    """Wrap beta_tool functions to print results for debugging."""
    for tool in tools:
        if not hasattr(tool, "func"):
            continue
        original = tool.func
        name = tool.name

        def _make_traced(orig: object, tool_name: str):  # type: ignore[no-untyped-def]
            def traced(*args: object, **kwargs: object) -> object:
                result = orig(*args, **kwargs)  # type: ignore[operator]
                print(_header(f"Result: {tool_name}", YELLOW))
                try:
                    parsed = json.loads(result)  # type: ignore[arg-type]
                    print(f"{DIM}{json.dumps(parsed, indent=2, default=str)}{RESET}")
                except (json.JSONDecodeError, TypeError):
                    print(f"{DIM}{result}{RESET}")
                return result

            return traced

        tool.func = _make_traced(original, name)


def _print_message_trace(message: object) -> None:
    """Print detailed trace of a single agent message."""
    for block in message.content:  # type: ignore[attr-defined]
        block_type = getattr(block, "type", None)

        if block_type == "text":
            print(f"{_header('Response', GREEN)}")
            print(block.text)

        elif block_type == "tool_use":
            print(f"{_header(f'Tool: {block.name}', CYAN)}")
            formatted = json.dumps(block.input, indent=2, default=str)
            print(f"{DIM}{formatted}{RESET}")

        elif block_type == "tool_result":
            print(f"{_header('Result', YELLOW)}")
            content = getattr(block, "content", None)
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    print(f"{DIM}{json.dumps(parsed, indent=2, default=str)}{RESET}")
                except json.JSONDecodeError:
                    print(f"{DIM}{content}{RESET}")
            elif content is not None:
                print(f"{DIM}{content}{RESET}")

        elif block_type == "code_execution_tool_result":
            print(f"{_header('Code Execution', MAGENTA)}")
            stdout = getattr(block, "stdout", None)
            stderr = getattr(block, "stderr", None)
            if stdout:
                print(f"{DIM}{stdout}{RESET}")
            if stderr:
                print(f"{DIM}stderr: {stderr}{RESET}")

        elif block_type == "server_tool_use":
            print(_header(f"Tool: {getattr(block, 'name', block_type)}", CYAN))

    # Print usage metadata
    usage = getattr(message, "usage", None)
    model = getattr(message, "model", None)
    stop_reason = getattr(message, "stop_reason", None)
    if usage:
        input_t = getattr(usage, "input_tokens", "?")
        output_t = getattr(usage, "output_tokens", "?")
        print(
            f"\n{DIM}model: {model} | "
            f"tokens: {input_t} in / {output_t} out | "
            f"stop: {stop_reason}{RESET}"
        )


def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not db_url:
        print("Error: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY environment variable is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")

    client = Anthropic(api_key=api_key)
    tools = build_tools(db_url)
    _trace_tools(tools)
    messages: list[dict] = []

    print(f"{BOLD}Spend Tracking Agent{RESET}")
    print(
        f"{DIM}Model: {model} | "
        f"DB: {db_url.split('@')[-1] if '@' in db_url else '***'}{RESET}"
    )
    print(f"{DIM}System prompt:{RESET}")
    print(f"{DIM}{SYSTEM_PROMPT}{RESET}")
    print(f"{DIM}Type your message. Ctrl+C or Ctrl+D to exit.{RESET}\n")

    try:
        while True:
            try:
                user_input = input(f"{BOLD}You: {RESET}")
            except EOFError:
                break

            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})

            final_message = None
            try:
                for message in run_agent(client, model, tools, messages):
                    _print_message_trace(message)
                    final_message = message
            except Exception as e:
                print(f"\n{BOLD}Error:{RESET} {e}", file=sys.stderr)
                messages.pop()
                continue

            if final_message:
                reply = extract_text(final_message)
                messages.append({"role": "assistant", "content": reply})

            print()
    except KeyboardInterrupt:
        print(f"\n{DIM}Bye!{RESET}")


if __name__ == "__main__":
    main()
