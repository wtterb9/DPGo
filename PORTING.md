# DarkPawns -> DPGo Porting Notes

This repo uses `GoMud` as the engine baseline and ports `DarkPawns` gameplay/world content into it.

## World Import (current)

`cmd/import-darkpawns-world` converts CircleMUD `.wld` and `.zon` data into GoMUD room YAML files.

`cmd/import-darkpawns-content` converts CircleMUD mobs/objects and applies zone reset commands as GoMUD room spawn entries.

### What it imports now

- Room vnum -> `roomid`
- Room title/description
- Directional exits (`north`, `east`, `south`, `west`, `up`, `down`)
- Zone names (from `.zon`) and per-zone `zone-config.yaml`
- Mob templates from `.mob` files (basic fields)
- Item templates from `.obj` files (basic fields + coarse type mapping)
- Zone reset spawn commands (`M` + `O`) into room `spawninfo`

### ID offset strategy

To avoid collisions with existing GoMUD content IDs:

- Rooms use `+2000000`
- Mobs use `+2000000`
- Items use `+3000000`

### What it intentionally skips for now

- Room extra descriptions (`E` records)
- Exit keywords/descriptions/locks/keys/door flags
- Room affects and special Circle flags
- Mob/object/zone command scripts

### Run

From this repo root:

`go run ./cmd/import-darkpawns-world -darkpawns-world /Users/brett/Coding/DarkPawns/lib/world -output-rooms /Users/brett/Coding/DPGo/_datafiles/world/default/rooms -zone-prefix "DarkPawns" -room-id-offset 2000000`

This creates migrated zone folders under `_datafiles/world/default/rooms`.

`go run ./cmd/import-darkpawns-content -darkpawns-world /Users/brett/Coding/DarkPawns/lib/world -output-rooms /Users/brett/Coding/DPGo/_datafiles/world/default/rooms -output-mobs /Users/brett/Coding/DPGo/_datafiles/world/default/mobs -output-items /Users/brett/Coding/DPGo/_datafiles/world/default/items -zone-prefix "DarkPawns" -room-id-offset 2000000 -mob-id-offset 2000000 -item-id-offset 3000000`

## Next planned parity phases

1. Improve object type/equipment/stat conversion parity from `.obj`.
2. Convert advanced zone reset instructions (`G`, `E`, `P`) to preserve loadouts and containers.
3. Rebuild class + remort progression data in GoMUD config/modules.
4. Port combat math/rules from `DarkPawns/src/fight.c` and related tables into GoMUD combat systems.
