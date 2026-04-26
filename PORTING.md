# DarkPawns -> DPGo Porting Notes

This repo uses `GoMud` as the engine baseline and ports `DarkPawns` gameplay/world content into it.

## World Import (first pass)

`cmd/import-darkpawns-world` converts CircleMUD `.wld` and `.zon` data into GoMUD room YAML files.

### What it imports now

- Room vnum -> `roomid`
- Room title/description
- Directional exits (`north`, `east`, `south`, `west`, `up`, `down`)
- Zone names (from `.zon`) and per-zone `zone-config.yaml`

### What it intentionally skips for now

- Room extra descriptions (`E` records)
- Exit keywords/descriptions/locks/keys/door flags
- Room affects and special Circle flags
- Mob/object/zone command scripts

### Run

From this repo root:

`go run ./cmd/import-darkpawns-world -darkpawns-world /Users/brett/Coding/DarkPawns/lib/world -output-rooms /Users/brett/Coding/DPGo/_datafiles/world/default/rooms -zone-prefix "DarkPawns"`

This creates migrated zone folders under `_datafiles/world/default/rooms`.

## Next planned parity phases

1. Import mobiles (`mob`) and objects (`obj`) into GoMUD mob/item templates.
2. Convert zone resets (`zon`) into spawn definitions.
3. Rebuild class + remort progression data in GoMUD config/modules.
4. Port combat math/rules from `DarkPawns/src/fight.c` and related tables into GoMUD combat systems.
