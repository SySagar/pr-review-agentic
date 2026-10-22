# Day 1 findings: GitHub MCP, auth, and LLM provider

Date: 2026-10-22  
Environment: WSL2 Ubuntu, Python 3.14.4, official `github-mcp-server` v2.0.3  
Sandbox PR: [SySagar/pr-review-agentic#1](https://github.com/SySagar/pr-review-agentic/pull/1)

No token value is recorded in this document.

## Summary

| Question | Result |
|---|---|
| Does the official MCP server expose the tools we need? | **Yes.** `tools/list` returned 46 tools with the default toolset. |
| Can it read PR details? | **Yes.** `pull_request_read` with `method=get`. |
| Can it read the diff? | **Yes.** `pull_request_read` with `method=get_diff`. |
| Can it post a PR-level comment? | **Yes.** `add_issue_comment` posted on PR #1. |
| Is the custom `post_comment` fallback required today? | **No, not for the current server.** Keep it as a resilience fallback. |
| Does it accept a PAT? | **Yes.** A PAT authenticated all probes. |
| Does it accept the workflow token? | **Expected, but not locally verified.** The server reads `GITHUB_PERSONAL_ACCESS_TOKEN`, so CI must pass `${{ github.token }}` through that variable. |
| Can we use GitHub Models? | **No. GitHub Models was fully retired on 2026-07-30.** |
| Replacement free provider | **Google Gemini API free tier**, using an AI Studio key. Default model: `gemini-3.5-flash-lite`. |

## What the MCP server returned

### Tool discovery

`tools/list` returned 46 tools. The relevant ones were:

| Capability | Tool | Notes |
|---|---|---|
| PR details | `pull_request_read` | Required `method=get`; arguments are `owner`, `repo`, `pullNumber`. |
| PR diff | `pull_request_read` | Required `method=get_diff`; no separate diff tool was needed. |
| PR files | `pull_request_read` | Also supports `method=get_files`. |
| PR comment | `add_issue_comment` | Uses `issue_number` for the PR number and `body` for the text. |
| Issue/PR comments | `issue_read` | `method=get_comments` reads existing comments. |

The full tool catalog must still be discovered at runtime. These names are
evidence from this release, not constants to hard-code.

### Probe results

| Probe | Result | Observed |
|---|---|---|
| `pull_request_read` (`get`) | Success | Returned PR title, body, state, branches, merge state, and URL. |
| `pull_request_read` (`get_diff`) | Success | Returned a unified diff for the one-file probe PR. |
| `add_issue_comment` | Success | Posted [comment 6346688227](https://github.com/SySagar/pr-review-agentic/pull/1#issuecomment-6346688227). |

Approximate local timings:

| Step | Time |
|---|---|
| Server initialize | 0.35–0.42 s |
| PR details | ~10.7 s |
| Diff read | ~0.5 s |
| Comment post | ~0.8 s |

The PR read was the slowest probe. The review pipeline should keep an overall
timeout and should not assume the first PR read is fast.

## Auth decision

The spike used a PAT from the local Git credential helper. The token was passed
to the server as `GITHUB_PERSONAL_ACCESS_TOKEN`; its value was never printed.

Decision:

1. Use the workflow `GITHUB_TOKEN` in GitHub Actions, mapped into
   `GITHUB_PERSONAL_ACCESS_TOKEN` for the MCP server.
2. Keep a PAT repository secret as the fallback if the Actions token is
   rejected.
3. Do not require a separate bot account.

The workflow token path must be rechecked in Phase 14, inside Actions, because a
local WSL session cannot reproduce the Actions token. The official server's
authentication variable is the important integration detail.

Rate-limit note: the PAT reported a core limit of 5,000 requests/hour. A
workflow `GITHUB_TOKEN` has a lower per-repository limit, so the reviewer must
stay well below it; one PR should consume only a handful of GitHub calls.

## Docker status

The production path is Docker stdio:

```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN \
  ghcr.io/github/github-mcp-server
```

Local WSL could not reach a Docker daemon: Docker Desktop was installed, but the
engine pipe was unavailable, so the image was not pulled.

To avoid faking the result, the spike was run with the same official server
release, built natively at v2.0.3, using the script's
`--server-command /path/to/github-mcp-server` option. The default script path
remains Docker. CI must verify the Docker path before relying on it.

Docker pull time: **not measured locally**.

## LLM provider finding

### GitHub Models is retired

GitHub retired GitHub Models on 2026-07-30. The playground, model catalog,
inference API, and BYOK endpoints are unavailable.

Evidence from this environment:

- `https://models.github.ai/inference/chat/completions` returned HTTP 200 with
  `content-type: text/plain` and the body `OK` for every tested model ID.
- Tested IDs included `openai/gpt-4o-mini`, `openai/gpt-4.1-mini`,
  `openai/gpt-5-mini`, and `meta/Llama-3.3-70B-Instruct`.
- The OpenAI SDK received a string instead of a chat-completion object:

```text
HTTP call: unexpected response after 849 ms
Response type: str
Content: OK
```

This is not a usable inference endpoint. A model name and rate-limit table
cannot be recorded because the service no longer answers inference requests.

### Replacement: Google Gemini API free tier

The project now targets Google Gemini through its OpenAI-compatible API:

```text
Base URL: https://generativelanguage.googleapis.com/v1beta/openai/
Model:    gemini-3.5-flash-lite
Key:      Google AI Studio API key (free tier)
```

Why this model:

- It is available on the free tier.
- It is JSON-capable through the OpenAI-compatible chat endpoint.
- The free-tier limit is currently in the range of 15 requests/minute and
  500 requests/day for Flash-Lite. The project expects only 2–3 LLM calls per
  review, so this fits the PR-time budget.
- Google changes free-tier limits; confirm the live values in
  [Google AI Studio](https://aistudio.google.com/rate-limit) before relying on
  them.

Status: **configuration is ready, live verification is pending a Google API
key.** No Google key was available during this spike, so no latency or token
usage is claimed here.

To use a different Gemini model, change only `LLM_MODEL`. For example,
`gemini-3.8-flash` may give better reviews but has a much smaller daily free
quota.

## Reproduce

MCP probe with the native server:

```bash
GITHUB_PERSONAL_ACCESS_TOKEN=<pat> \
uv run python scripts/spike_github_mcp.py \
  --server-command /path/to/github-mcp-server \
  --repo SySagar/pr-review-agentic --pr 1
```

MCP probe with Docker, the default production path:

```bash
GITHUB_PERSONAL_ACCESS_TOKEN=<pat> \
uv run python scripts/spike_github_mcp.py \
  --repo SySagar/pr-review-agentic --pr 1
```

Post a probe comment:

```bash
GITHUB_PERSONAL_ACCESS_TOKEN=<pat> \
uv run python scripts/spike_github_mcp.py \
  --repo SySagar/pr-review-agentic --pr 1 --post-comment
```

LLM probe:

```bash
LLM_API_KEY=<google-ai-studio-key> \
uv run python scripts/spike_llm.py
```

The script defaults to the Gemini endpoint and `gemini-3.5-flash-lite`. Override
`LLM_BASE_URL` or `LLM_MODEL` only if needed.

## Remaining check

The Gemini configuration is in place, but it has not been called with a real
Google key yet. Run the LLM probe once with your key and record the observed
latency and token usage in this document.
