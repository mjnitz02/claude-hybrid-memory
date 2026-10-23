---
territory: <chain/components>
layer: <1-5, or omit for non-chain>
consumes: <upstream territory, or none>
consumed_by: <downstream territory, or none>
members:
  <repo>: {owner: <self|colleague|employer|third-party>, mode: <active|occasional-pr|reference|dead-upstream|scratch>}
---
# <territory>

Auto-loaded by the harness for every repo pointed here. Limit is 200 lines / 25 KB, so
this is a router too, not a container.

## GATES - read before acting
<!-- Inline the full text of every role: gate memory in this territory. Not a link: a
     linked gate is a soft convention, and soft conventions are what failed. -->

## UPSTREAM CONTRACT - exports from <consumes>
<!-- Inlined from the upstream territory's EXPORTS.md. mem.py drift reports divergence. -->

## MEMORIES
<!-- Hook carries the CONCLUSION, not the subject. -->
- [<conclusion>](<slug>.md) — <status + date + what it settles>
