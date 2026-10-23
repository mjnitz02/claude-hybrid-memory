"""Tooling for the Claude memory store. See docs/direction.md.

Import-light by design: `mem hook ...` runs on every session start, so nothing here may
import the audit modules, argparse, or any third-party package at module level.
"""
