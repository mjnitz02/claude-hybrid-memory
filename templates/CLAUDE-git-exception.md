- **One exception: the memory store.** `mem` commits `~/.claude/memory/` on its own after
  memory writes, with generated messages. It has no remote and is never pushed. This covers
  that directory only — every repo, including claude-hybrid-memory itself, stays under the rule above.
