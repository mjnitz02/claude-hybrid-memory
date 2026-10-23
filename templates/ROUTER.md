# MEMORY ROUTER

machine: <work-mac | personal-mac>
last_retrospective: <YYYY-MM-DD>
territories: <n>

This file is a map, never a container. Its job is to answer one question: does anything I
am not currently looking at matter right now.

## chain
Product dependency chain. A change at a layer breaks the layer below it.

- chain/foundation : <members>. PULL WHEN: <trigger>
- chain/components : <members>. PULL WHEN: <trigger>
- chain/templates : <members>. PULL WHEN: <trigger>
- chain/apps : <members>. PULL WHEN: <trigger>

## utility
Cuts across every layer.

- utility/dep-policy : PULL WHEN: <trigger>
- utility/github-actions : PULL WHEN: <trigger>

## mine
Your own tooling. Not part of the product chain; these cannot break each other.

- mine/ops : <members>. PULL WHEN: <trigger>

## solo
One territory per repo. Grouped here for legibility only; nothing is shared.

- solo/<repo> : PULL WHEN: working in that repo

## Gates and cluster contracts
Irreversible-harm rules go in `GATES.md`, always loaded ahead of this file and never degraded,
capped at five. Everything else a territory exports is a **cluster contract** and is inlined into
the `MEMORY.md` of the territory that declares `consumes:` it — not copied here. Only a
`utility/*` export, which binds every layer, belongs in this file; see `format-spec.md`.
