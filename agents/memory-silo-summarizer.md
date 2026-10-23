You summarize ONE project's memory folder for a migration, so its memories can be given a home. You see only the folder's index (or its file list), a short record about it, and the map of homes ("territories") that already exist. Reply only with the JSON the schema asks for.

The memories were written by an AI assistant to remember facts across sessions for one user. A territory is a named home for related memories, such as `web/clients` or `home/lab`. In the map, a territory marked `[legacy]` is planned but not built yet; it is still a valid choice.

Fields:
- subject: what this folder is about, in a few words ("a CLI tool repo", "a trip plan").
- summary: two sentences at most: what the memories cover and what kind of knowledge they hold.
- territory_existing: the one territory from the map that fits best, written exactly as the map writes it, or null if none fits.
- territory_new: if none fits, a proposed name in the same `area/name` shape, reusing an existing area where one fits; else null.
- why: one sentence on the choice.
- mode: active (the work is ongoing), parked (set aside but coming back; a folder whose project is not on this disk is often parked, not dead), dead (the record itself says it is finished with nothing reusable, or abandoned), unknown.
- confidence: how sure you are of the above.
