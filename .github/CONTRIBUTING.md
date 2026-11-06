# Contributing

claude-hybrid-memory is a personal, single-maintainer project built for one
person's Claude Code setup. It's open source in case the approach helps someone,
but it isn't trying to become a general-purpose product. So:

- **Bug reports and ideas are welcome** via [issues](https://github.com/mjnitz02/claude-hybrid-memory/issues).
- **PRs may be declined** if they don't fit the design, even when they're well
  made. Open an issue first for anything non-trivial.

## Design

[`docs/design.md`](../docs/design.md) explains the model and the alternatives
already rejected; [`docs/format-spec.md`](../docs/format-spec.md) is the format
`mem` enforces. Read the "Two rules worth knowing" section of
[`docs/overview.md`](../docs/overview.md) before changing anything.

## Development

Everything runs through [Task](https://taskfile.dev) (`Taskfile.yml`); `task` alone
lists the targets. Task is pinned in the dev dependencies, so `uv run task <name>` always
works; `uv tool install go-task-bin` puts a bare `task` on your PATH.

```sh
task sync    # dev environment from uv.lock
task hooks   # git hooks (prek): lint + secret scan on commit, tests on push
task check   # what CI runs
```

Tests use synthetic fixture stores only. Never put real memory content in this
repo: memories are machine-local by design.

## License

By contributing, you agree your contributions are licensed under the
[MIT License](../LICENSE).
