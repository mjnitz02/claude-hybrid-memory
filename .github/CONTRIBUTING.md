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
`mem` enforces. Read the "Two rules worth knowing" section of the
[README](../README.md) before changing anything.

## Development

Everything runs through the `Makefile`; `make` alone lists the targets.

```sh
make sync    # dev environment from uv.lock
make hooks   # git hooks: lint + secret scan on commit, tests on push
make check   # what CI runs
```

Tests use synthetic fixture stores only. Never put real memory content in this
repo: memories are machine-local by design.

## License

By contributing, you agree your contributions are licensed under the
[MIT License](../LICENSE).
