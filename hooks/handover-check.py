"""Claude Code handover hooks. Two modes:

- UserPromptSubmit (no arguments): tells Claude when the context crosses a threshold, and BLOCKS the
  message if more than 60 min passed since the last reply (the prompt cache expired: sending it re-reads
  the whole session at full price). The block message points to the session summary file.
  Start the message with ++ or / to send it anyway.
- Stop (--stop): after every reply, writes the end of the conversation (text only, no tool output) to
  ~/.claude/handover/<session_id>.md. No model call: it costs nothing.

No state besides that file. On any error it exits 0 and prints nothing: a failure never blocks you.
Self-test: python handover-check.py --test"""
import json
import os
import sys
from datetime import datetime, timezone

CONTEXT_THRESHOLD = 120_000  # context tokens at which the first warning fires
CONTEXT_STEP = 40_000        # warn again every this many tokens (160k, 200k, ...)
GAP_MINUTES = 60             # idle time since the last reply; past one hour the prompt cache expired
TAIL_MESSAGES = 12           # text messages (yours and Claude's) kept in the summary
MAX_CHARS = 2000             # per-message cut in the summary
BYPASS = ("++", "/")         # prefixes that go through even with an expired cache
HANDOVER_DIR = os.path.join(os.path.expanduser("~"), ".claude", "handover")


def level(tokens):
    """Threshold reached: -1 below it, 0 at 120k, 1 at 160k, ..."""
    return -1 if tokens < CONTEXT_THRESHOLD else (tokens - CONTEXT_THRESHOLD) // CONTEXT_STEP


def context_crossed(prev, last):
    """True if last crossed a threshold that prev (or nothing) had not crossed."""
    return level(last) > level(prev if prev is not None else 0)


def gap_exceeded(last_ts, now):
    return (now - last_ts).total_seconds() > GAP_MINUTES * 60


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def entries(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def usage_tokens(o):
    u = (o.get("message") or {}).get("usage") or {}
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def responses(path):
    """[(context, timestamp)] of main-thread replies, one per message.id."""
    by_id = {}
    for o in entries(path):
        if o.get("type") != "assistant" or o.get("isSidechain") is not False:
            continue
        ctx = usage_tokens(o)
        if ctx and o.get("timestamp"):
            key = (o.get("message") or {}).get("id", o.get("uuid"))
            by_id.pop(key, None)  # re-insert at the end: keeps order of appearance
            by_id[key] = (ctx, parse_ts(o["timestamp"]))
    return list(by_id.values())


def is_prompt(o):
    """A message the user typed (not a tool result, not a meta or system block)."""
    if o.get("type") != "user" or o.get("isSidechain") is not False or o.get("isMeta"):
        return False
    content = (o.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
    return any(isinstance(b, dict) and b.get("type") == "text" and not b.get("text", "").lstrip().startswith("<")
               for b in blocks)


def context_before_last_prompt(path):
    """Context of the last reply before the user's previous message. Compared with the latest reply it catches
    a threshold crossed anywhere inside the last turn, tool calls included, not only between its last two calls."""
    last = before = None
    for o in entries(path):
        if is_prompt(o):
            before = last
        elif o.get("type") == "assistant" and o.get("isSidechain") is False:
            last = usage_tokens(o) or last
    return before


def texts(path):
    """[(role, text)] of the visible conversation: what the user typed and Claude's text, without tools,
    without thinking and without blocks the system adds (<system-reminder>, <ide_selection>...)."""
    out = []
    for o in entries(path):
        role = o.get("type")
        if role not in ("user", "assistant") or o.get("isSidechain") is not False or o.get("isMeta"):
            continue
        content = (o.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        t = "\n".join(b.get("text", "").strip() for b in blocks
                      if isinstance(b, dict) and b.get("type") == "text"
                      and not b.get("text", "").lstrip().startswith("<")).strip()
        if t:
            out.append(("User" if role == "user" else "Claude", t))
    return out


def tail_markdown(msgs, transcript, cwd, now):
    lines = [f"# End of a previous session ({now:%Y-%m-%d %H:%M} UTC)", "",
             f"Working folder: `{cwd}`", f"Full transcript: `{transcript}`", "",
             "This is the end of the conversation, text only. Read it and continue from there. If a detail is "
             "missing (a commit SHA, a path, a tool output), look it up in the transcript before assuming it.", ""]
    for role, t in msgs[-TAIL_MESSAGES:]:
        if len(t) > MAX_CHARS:
            t = t[:MAX_CHARS] + " [...]"
        lines += [f"## {role}", "", t, ""]
    return "\n".join(lines)


def handover_path(session_id):
    return os.path.join(HANDOVER_DIR, f"{session_id}.md")


def on_stop(data):
    msgs = texts(data["transcript_path"])
    if not msgs:
        return
    os.makedirs(HANDOVER_DIR, exist_ok=True)
    with open(handover_path(data["session_id"]), "w", encoding="utf-8") as f:
        f.write(tail_markdown(msgs, data["transcript_path"], data.get("cwd", ""), datetime.now(timezone.utc)))


def on_prompt(data):
    r = responses(data["transcript_path"])
    if not r:
        return
    last_ctx, last_ts = r[-1]
    now = datetime.now(timezone.utc)
    if gap_exceeded(last_ts, now) and not data.get("prompt", "").lstrip().startswith(BYPASS):
        mins = int((now - last_ts).total_seconds() // 60)
        path = handover_path(data["session_id"])
        print(json.dumps({"decision": "block", "reason":
            f"{mins} min passed: the prompt cache expired and this message would re-read the whole session "
            f"at full price. It was NOT sent. Open a new session and paste: Continue from {path}   "
            f"(To send it here anyway, start it with ++)"}))
        return
    if context_crossed(context_before_last_prompt(data["transcript_path"]), last_ctx):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
            f"Context is at ~{last_ctx // 1000}k tokens. Offer the user a handover with /handover "
            "(mid-task mode); do not do it without their OK."}}))


def test():
    import tempfile
    assert level(119_999) == -1 and level(120_000) == 0 and level(159_999) == 0 and level(160_000) == 1
    assert context_crossed(100_000, 125_000)        # crosses 120k
    assert not context_crossed(125_000, 150_000)    # same step
    assert context_crossed(150_000, 165_000)        # crosses 160k
    assert context_crossed(100_000, 210_000)        # jumps two steps: warns once
    assert context_crossed(None, 130_000)           # first reply already above threshold
    assert not context_crossed(None, 50_000)
    assert not context_crossed(200_000, 190_000)    # goes down (compaction)
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert gap_exceeded(t, datetime(2026, 1, 1, 13, 1, tzinfo=timezone.utc))
    assert not gap_exceeded(t, datetime(2026, 1, 1, 12, 59, tzinfo=timezone.utc))
    assert parse_ts("2026-10-19T05:05:13.604Z").tzinfo is not None
    rows = [
        {"type": "user", "isSidechain": False, "message": {"content": [
            {"type": "text", "text": "<system-reminder>noise</system-reminder>"},
            {"type": "text", "text": "hi"}]}},
        {"type": "user", "isSidechain": False, "isMeta": True, "message": {"content": [{"type": "text", "text": "meta"}]}},
        {"type": "assistant", "isSidechain": False, "message": {"content": [{"type": "thinking", "thinking": "x"}]}},
        {"type": "assistant", "isSidechain": False, "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"type": "user", "isSidechain": False, "message": {"content": [{"type": "tool_result", "content": "output"}]}},
        {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "subagent"}]}},
        {"type": "assistant", "isSidechain": False, "message": {"content": [{"type": "text", "text": "bye"}]}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n{broken\n")
    assert texts(f.name) == [("User", "hi"), ("Claude", "bye")], texts(f.name)
    # 120k crossed between two tool calls of the same turn: comparing only the last two replies missed it
    use = lambda n: {"type": "assistant", "isSidechain": False, "message": {"usage": {"input_tokens": n}}}
    turn = [{"type": "user", "isSidechain": False, "message": {"content": "hi"}}, use(100_000),
            {"type": "user", "isSidechain": False, "message": {"content": "go on"}}, use(110_000),
            {"type": "user", "isSidechain": False, "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            use(125_000),
            {"type": "user", "isSidechain": False, "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            use(130_000)]
    with open(f.name, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in turn))
    assert context_before_last_prompt(f.name) == 100_000
    assert context_crossed(context_before_last_prompt(f.name), 130_000)
    md = tail_markdown([("User", "x" * (MAX_CHARS + 10))], f.name, "/home/me/project", t)
    assert md.count("## User") == 1 and md.endswith(" [...]\n")
    os.unlink(f.name)
    assert "++ hi".startswith(BYPASS) and "/handover".startswith(BYPASS) and not "hi".startswith(BYPASS)
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    else:
        try:
            data = json.load(sys.stdin)
            on_stop(data) if "--stop" in sys.argv else on_prompt(data)
        except Exception:
            pass
        sys.exit(0)
