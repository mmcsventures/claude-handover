# claude-handover

A hook and a skill for [Claude Code](https://claude.com/claude-code) that stop you from paying for a stale session, and make it easy to continue the work in a fresh one.

## What it's for

Two things get expensive in long Claude Code sessions:

1. **Coming back after a break.** Claude Code caches your conversation for about an hour. If you send a message after the cache expires, the whole session is read again at full price. In a big session that one message can cost more than a lot of fresh work.
2. **Letting the context grow forever.** Every message re-sends the whole conversation. Past ~120k tokens each reply costs more and the model gets less sharp.

The fix in both cases is the same: start a new session and give it a short, precise summary of where you were. This repo automates that.

## How it works

### The hook: `hooks/handover-check.py`

One Python script, wired to two Claude Code hook events.

- **After every reply (`Stop`)** it saves the last 12 text messages of the conversation (yours and Claude's, no tool output, no thinking, each cut at 2000 characters) to `~/.claude/handover/<session_id>.md`. It does not call any model, so it costs nothing.
- **Before every message you send (`UserPromptSubmit`)** it checks two things:
  - **More than 60 minutes since Claude's last reply?** It blocks the message. The message never reaches the model, so you pay nothing. You see:
    `Open a new session and paste: Continue from ~/.claude/handover/<id>.md`.
    To send it in the old session anyway, start the message with `++`. Slash commands (`/...`) always go through.
  - **Context crossed 120k tokens** (and again at 160k, 200k, ...)? It tells Claude to offer you a handover with `/handover`. Claude asks first; it does not do it on its own.

If the script hits any error, it exits silently. It never blocks you because of a bug.

### The skill: `/handover`

The saved summary is only the tail of the chat. For work in progress (half-done code, open branches) you want a real handover. Type `/handover` and Claude writes a prompt for the next session, in a code block you copy with one click:

- the goal and what "done" looks like,
- what is already done, with commit SHAs and file paths it checks before writing,
- the steps left, in order,
- absolute paths of every file involved,
- traps found during the session,
- what NOT to touch, including files that other open sessions are editing (it searches their transcripts).

The skill runs on Opus with high effort, even if your session uses Sonnet or Haiku, because a vague handover wastes a whole session.

## Setup

**You need:** Claude Code and Python 3.8+ on your `PATH`. No other dependencies.

1. **Copy the files** into your Claude folder (`~/.claude`, on Windows `C:\Users\<you>\.claude`):

   ```
   ~/.claude/hooks/handover-check.py
   ~/.claude/skills/handover/SKILL.md
   ```

   From a clone of this repo:

   ```bash
   mkdir -p ~/.claude/hooks ~/.claude/skills/handover
   cp hooks/handover-check.py ~/.claude/hooks/
   cp skills/handover/SKILL.md ~/.claude/skills/handover/
   ```

2. **Check that the script runs:**

   ```bash
   python3 ~/.claude/hooks/handover-check.py --test
   ```

   It prints `ok`. On Windows the command is usually `python` instead of `python3`.

3. **Add the hooks** to `~/.claude/settings.json`. If the file already has a `"hooks"` key, merge these two entries into it instead of adding a second one:

   ```json
   {
     "hooks": {
       "UserPromptSubmit": [
         { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/handover-check.py", "timeout": 10 } ] }
       ],
       "Stop": [
         { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/handover-check.py --stop", "timeout": 10 } ] }
       ]
     }
   }
   ```

   On Windows, use `python` and the full path with forward slashes, for example
   `python C:/Users/<you>/.claude/hooks/handover-check.py`.

4. **Restart Claude Code.** Run `/hooks` to see both hooks listed. Send one message, then check that a file appeared in `~/.claude/handover/`.

## Settings

The numbers are constants at the top of `handover-check.py`:

| Constant | Default | What it does |
|---|---|---|
| `GAP_MINUTES` | `60` | Idle minutes before a message gets blocked |
| `CONTEXT_THRESHOLD` | `120_000` | Tokens at which Claude first offers a handover |
| `CONTEXT_STEP` | `40_000` | Offers again every this many tokens |
| `TAIL_MESSAGES` | `12` | Messages kept in the saved summary |
| `MAX_CHARS` | `2000` | Per-message cut in the summary |
| `BYPASS` | `("++", "/")` | Message prefixes that skip the block |

## Turning it off

Delete the `UserPromptSubmit` entry (or both entries) from `~/.claude/settings.json`. Files in `~/.claude/handover/` are plain Markdown; delete them whenever you like.

## Good to know

- If a message "didn't send", it was this hook blocking it. The reason shows in the Claude Code UI.
- The block only fires when you send a message, so leaving a session open costs nothing.
- The summary files contain your conversation text. They stay on your machine; nothing is uploaded.

## License

MIT
