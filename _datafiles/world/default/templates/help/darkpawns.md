# DarkPawns Go

DarkPawns Go is a content-focused migration of the legacy DarkPawns CircleMUD world
onto the GoMud engine.

## Design Goals

- Preserve DarkPawns setting, areas, mobs, objects, and tone.
- Keep native GoMud gameplay systems and engine behavior.
- Prefer data/config conversion over custom engine rewrites.

## Legacy Content

- World zones, rooms, objects, and mobiles are imported from DarkPawns data files.
- Shop data, room reset chains, and container nesting are mapped into GoMud-native files.
- Legacy help/social files are available under:
  - `help darkpawns-classes`
  - `help darkpawns-races`
  - `help darkpawns-commands`
  - `help darkpawns-info`
  - `help darkpawns-socials`
  - `help darkpawns-spells`
  - `help darkpawns-wizhelp`

## Notes

Some CircleMUD-specific mechanics are approximated to the closest GoMud-native behavior.
When there is a mismatch, stability and native GoMud operation are prioritized.
