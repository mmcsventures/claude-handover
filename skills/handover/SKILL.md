---
name: handover
description: Invoke BEFORE writing a prompt the user will paste into a new Claude Code session - the closing prompt at the end of a session, or a mid-task handover when the context is large or the prompt cache expired. Runs that writing on Opus even when the session runs on Sonnet or Haiku.
model: opus
effort: high
---

You are writing text the user will paste into a fresh session without editing it. The new session knows nothing except what you write. Any ambiguity costs a whole session. That is why this skill runs on Opus.

Before writing:
- Check every fact about the repo you are about to state (file contents, branch, commit, what a script does). Read it now if you did not read it in this session. If you cannot check it, mark it as a guess.

Rules for the text:
- Head the prompt with the model and effort level the next session should use. Pick the cheapest model that can do the work.
- Give the absolute path of the repo or worktree to work in, and the absolute path where each output is saved.
- Put the prompt inside one fenced code block, so the user sees where it starts and ends and copies it with one click. If the prompt contains triple backticks, fence it with four.
- The message opens with the model/effort line and the fenced prompt. Everything else (what the user must do, caveats, open decisions) goes AFTER the block.
- The user pastes the block without reading it. Anything they must do themselves (answer a question, open a page, run a command, pick an option) goes in the chat, after the block, as a short numbered list. The prompt may tell the next session to check it was done, but the prompt is never the only place that instruction lives.
- One instruction per sentence. Concrete nouns. No "the usual", no "as before" without saying what that was.

## Mid-task handover

Use this mode when you cut a session in the middle of a task (the `handover-check.py` hook suggests it when the context is large). The text you write is the whole memory of the new session.

Before writing, check the other sessions' transcripts so the new session does not overwrite work another session is doing:
- List the `.jsonl` files in this project's folder under `~/.claude/projects/`. Skip the current session's own file.
- Search each one for the absolute path of this task's repo or worktree. Check the most recent ones first.
- If another session touched that path recently, say so in the prompt: which session, what it changed, and that the new session must check it before editing.

Write the prompt with these parts, in this order:
1. Goal of the task: one or two sentences, what "done" looks like.
2. What is done: each item with the commit SHA or the file path where it lives. Read `git log` or the file now; do not write from memory.
3. What is left: numbered steps, one action per step, in the order to run them.
4. Absolute paths of every file involved (to read, to edit, to create), plus the repo or worktree path.
5. Traps found during the session: errors hit, wrong assumptions, commands that fail and why.
6. What NOT to touch: files, branches, and work owned by other sessions.

After writing, reread it as someone who did not see this session. Every noun that only makes sense with this session's context gets explained or replaced.
