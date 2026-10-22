#!/usr/bin/env python3
"""Day-1 spike: start the official GitHub MCP server and probe its tools.

The default transport is Docker stdio, matching production. For local
development without a working Docker engine, pass a native
``github-mcp-server`` binary with ``--server-command``.

Examples:
    uv run python scripts/spike_github_mcp.py --repo owner/name --pr 1
    uv run python scripts/spike_github_mcp.py --repo owner/name --pr 1 \\
        --post-comment
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

DEFAULT_IMAGE = "ghcr.io/github/github-mcp-server"
DEFAULT_TOOLSETS = "default"


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-command",
        default=os.getenv("SPIKE_MCP_COMMAND", "docker"),
        help="'docker', docker.exe, or a native github-mcp-server binary",
    )
    parser.add_argument(
        "--server-arg",
        action="append",
        default=[],
        help="extra argument for a custom server command (repeatable)",
    )
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--toolsets", default=DEFAULT_TOOLSETS)
    parser.add_argument("--repo", default=os.getenv("SPIKE_REPO", ""))
    parser.add_argument("--pr", type=int, default=_env_int("SPIKE_PR"))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--tools-json", type=Path, help="write the full tool inventory")
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="post one harmless probe comment on the PR",
    )
    parser.add_argument(
        "--comment",
        default="Day-1 MCP spike: this is an automated test comment. Safe to ignore.",
    )
    parser.add_argument("--full-output", action="store_true")
    return parser.parse_args()


def _resolve_token() -> tuple[str, str]:
    for name in ("GITHUB_PERSONAL_ACCESS_TOKEN", "GITHUB_TOKEN"):
        value = os.getenv(name)
        if value:
            return name, value
    raise SystemExit("Set GITHUB_PERSONAL_ACCESS_TOKEN (PAT) or GITHUB_TOKEN before running.")


def _server_params(args: argparse.Namespace, token: str) -> StdioServerParameters:
    env = os.environ.copy()
    # The official server reads a PAT from this variable. In Actions the
    # workflow token is passed through the same variable for the spike.
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    env["GITHUB_TOOLSETS"] = args.toolsets

    command = Path(args.server_command)
    is_native = command.name.startswith("github-mcp-server")
    if is_native:
        return StdioServerParameters(
            command=str(command),
            args=["stdio", *args.server_arg],
            env=env,
        )

    if command.name in {"docker", "docker.exe"}:
        return StdioServerParameters(
            command=str(command),
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e",
                "GITHUB_TOOLSETS",
                args.image,
                *args.server_arg,
            ],
            env=env,
        )

    return StdioServerParameters(
        command=str(command),
        args=args.server_arg,
        env=env,
    )


def _check_docker(command: str) -> None:
    # also have verified manually by runnning docker daemon and then `docker info`
    try:
        result = subprocess.run(
            [command, "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Docker is not usable via {command}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        first = next((line for line in detail if line.strip()), "no detail")
        raise SystemExit(f"Docker daemon unavailable via {command}: {first}")


def _tool_json(tool: Any) -> dict[str, Any]:
    # This converts a tool object to a dict for JSON output.
    if hasattr(tool, "model_dump"):
        return tool.model_dump(by_alias=True)
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "inputSchema": getattr(tool, "inputSchema", None),
    }


def _pick(tools: list[Any], exact: str, *terms: str) -> Any | None:
    """Pick a tool by exact name first, then by fuzzy name/description matching.

    Example:
        exact="pull_request_read"
        terms=("pull", "request")
    """
    for tool in tools:
        if getattr(tool, "name", "") == exact:
            return tool
    for tool in tools:
        haystack = f"{getattr(tool, 'name', '')} {getattr(tool, 'description', '')}".lower()
        if all(term in haystack for term in terms):
            return tool
    return None


def _text_of(result: Any) -> str:
    """Extract text from a tool result.

    Concatenate all text parts into one string. If there is no content or text,
    return an empty string.
    """
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _is_error(result: Any) -> bool:
    return bool(getattr(result, "isError", getattr(result, "is_error", False)))


def _preview(text: str, full: bool) -> str:
    # This trims long output so logs stay readable.
    if full:
        return text
    one_line = " ".join(text.split())
    return one_line[:700] + ("..." if len(one_line) > 700 else "")


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    *,
    timeout: float,
    full: bool,
) -> dict[str, Any]:
    # Invokes mcp tool calling

    started = time.perf_counter()
    result = await session.call_tool(name, arguments, read_timeout_seconds=timeout)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    text = _text_of(result)
    payload: dict[str, Any] = {
        "tool": name,
        "ok": not _is_error(result),
        "ms": elapsed_ms,
        "chars": len(text),
    }
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structured_keys"] = sorted(structured) if isinstance(structured, dict) else []
    print(
        f"  call {name}: ok={payload['ok']} ms={elapsed_ms} chars={len(text)}",
        flush=True,
    )
    print(f"  preview: {_preview(text, full)}", flush=True)
    return payload | {"text": text}


async def _run(args: argparse.Namespace) -> int:
    """Start the GitHub MCP server, discover supported tools, and probe a PR.

    Validates the command-line arguments, resolves the GitHub auth token,
    launches the MCP server, lists available tools, selects likely PR/diff/comment
    endpoints, and invokes them against the target repository and pull request.
    Returns 0 when all probe calls succeed and 1 when any check fails.
    """
    if not args.repo or "/" not in args.repo or args.pr <= 0:
        raise SystemExit("Pass --repo owner/name and --pr <number> for the probes.")
    owner, repo = args.repo.split("/", 1)
    token_name, token = _resolve_token()
    print(f"Starting GitHub MCP server via {args.server_command}")
    print(f"Token source: {token_name} (value not logged)")

    if Path(args.server_command).name in {"docker", "docker.exe"}:
        _check_docker(args.server_command)

    params = _server_params(args, token)
    started = time.perf_counter()
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            init_ms = round((time.perf_counter() - started) * 1000)
            print(f"Initialized in {init_ms} ms", flush=True)

            listed = await session.list_tools()
            tools = list(listed.tools)
            print(f"tools/list: {len(tools)} tools", flush=True)
            for tool in tools:
                print(f"  - {getattr(tool, 'name', '?')}", flush=True)

            if args.tools_json:
                inventory = [_tool_json(tool) for tool in tools]
                args.tools_json.parent.mkdir(parents=True, exist_ok=True)
                args.tools_json.write_text(json.dumps(inventory, indent=2) + "\n")
                print(f"Wrote {args.tools_json}", flush=True)

            pr_tool = _pick(tools, "pull_request_read", "pull", "request")
            diff_tool = pr_tool or _pick(tools, "__none__", "diff", "pull")
            comment_tool = _pick(tools, "add_issue_comment", "comment", "issue")
            print(
                "Selected:",
                f"pr={getattr(pr_tool, 'name', None)}",
                f"diff={getattr(diff_tool, 'name', None)}",
                f"comment={getattr(comment_tool, 'name', None)}",
                flush=True,
            )

            results: dict[str, Any] = {"tools": len(tools), "init_ms": init_ms}
            if pr_tool is not None:
                results["pr_read"] = await _call(
                    session,
                    pr_tool.name,
                    {
                        "owner": owner,
                        "repo": repo,
                        "pullNumber": args.pr,
                        "method": "get",
                    },
                    timeout=args.timeout,
                    full=args.full_output,
                )
            if diff_tool is not None:
                diff_args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": args.pr,
                }
                if diff_tool.name == getattr(pr_tool, "name", None):
                    diff_args["method"] = "get_diff"
                results["diff"] = await _call(
                    session,
                    diff_tool.name,
                    diff_args,
                    timeout=args.timeout,
                    full=args.full_output,
                )
            if args.post_comment:
                if comment_tool is None:
                    print("No comment tool discovered; fallback is required.", flush=True)
                    results["comment"] = {"ok": False, "reason": "no comment tool"}
                else:
                    results["comment"] = await _call(
                        session,
                        comment_tool.name,
                        {
                            "owner": owner,
                            "repo": repo,
                            "issue_number": args.pr,
                            "body": args.comment,
                        },
                        timeout=args.timeout,
                        full=args.full_output,
                    )

    failures = [
        name
        for name, value in results.items()
        if isinstance(value, dict) and not value.get("ok", True)
    ]
    summary = {
        key: value.get("ok") if isinstance(value, dict) else value for key, value in results.items()
    }
    print(f"Summary: {json.dumps(summary)}")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
