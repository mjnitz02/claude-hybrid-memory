# Security Policy

## Supported versions

This is a personal open-source project. Only the latest commit on `main`
receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately via GitHub's
[private vulnerability reporting](https://github.com/mjnitz02/claude-hybrid-memory/security/advisories/new),
which notifies the maintainer directly and keeps the report confidential until
a fix ships.

Expect an initial response within roughly a week. As a single-maintainer
project there is no formal SLA, but reports are taken seriously and credited
in the advisory unless you'd rather stay anonymous.

## Scope

In scope: this repository's source, its GitHub Actions workflows, and the
hooks and skills it installs into Claude Code. The constraints `mem fresh --run`
puts on `verify:` recipes (allowlisted commands, no shell, no mutating
subcommands, timeouts) are a security boundary: a recipe that gets past them is
a vulnerability.

Out of scope: vulnerabilities in third-party dependencies (report those
upstream; Dependabot tracks them here), and issues that require an already
compromised local machine or a store someone else can already write to.
