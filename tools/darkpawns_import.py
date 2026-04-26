#!/usr/bin/env python3
"""Import CircleMUD DarkPawns world data into GoMUD YAML content.

This script intentionally maps data into GoMUD-native content structures
without changing engine code. It focuses on:
- zones (zone-config.yaml)
- rooms (.wld -> room YAML)
- objects (.obj -> item YAML)
- mobs (.mob -> mob YAML)
- resets (.zon -> room spawninfo)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DIR_MAP = {
    0: "north",
    1: "east",
    2: "south",
    3: "west",
    4: "up",
    5: "down",
}

OBJ_TYPE_WEAPON_SUBTYPE = {
    5: "slashing",     # weapon
    6: "bludgeoning",  # firearm-ish in circle, closest GoMUD fallback
    7: "stabbing",     # missile
    8: "bludgeoning",  # treasure (kept generic)
}

WEAR_SLOT_MAP = {
    1 << 1: "ring",      # finger
    1 << 2: "neck",      # neck
    1 << 3: "body",      # body
    1 << 4: "head",      # head
    1 << 5: "legs",      # legs
    1 << 6: "feet",      # feet
    1 << 7: "gloves",    # hands
    1 << 8: "body",      # arms -> body fallback
    1 << 9: "offhand",   # shield
    1 << 10: "neck",     # about body -> closest
    1 << 11: "belt",     # waist
    1 << 12: "gloves",   # wrist -> closest
    1 << 13: "weapon",   # wield
    1 << 14: "offhand",  # hold
}

MOB_FLAG_SENTINEL = 1 << 1
MOB_FLAG_SCAVENGER = 1 << 2
MOB_FLAG_AGGRESSIVE = 1 << 5
MOB_FLAG_STAY_ZONE = 1 << 6
MOB_FLAG_AGGR_EVIL = 1 << 8
MOB_FLAG_AGGR_GOOD = 1 << 9
MOB_FLAG_AGGR_NEUTRAL = 1 << 10


@dataclass
class Room:
    roomid: int
    zone_num: int
    title: str
    description: str
    biome: str = "city"
    pvp: Optional[bool] = None
    tags: List[str] = field(default_factory=list)
    nouns: Dict[str, str] = field(default_factory=dict)
    exits: Dict[str, dict] = field(default_factory=dict)
    containers: Dict[str, dict] = field(default_factory=dict)
    spawninfo: List[dict] = field(default_factory=list)


@dataclass
class Mob:
    mobid: int
    zone_num: int
    aliases: str
    short_desc: str
    long_desc: str
    detailed_desc: str
    ambient_lines: List[str]
    level: int
    alignment: int
    gold: int
    act_flags: int


@dataclass
class Obj:
    itemid: int
    zone_num: int
    aliases: str
    short_desc: str
    long_desc: str
    action_desc: str
    extra_descs: List[str]
    obj_type: int
    wear_flags: int
    values: List[int]
    affects: List[Tuple[int, int]]
    weight: int
    cost: int


@dataclass
class Zone:
    number: int
    name: str
    top: int
    commands: List[List[str]] = field(default_factory=list)


@dataclass
class ShopDef:
    keeper_mobid: int
    producing_itemids: List[int] = field(default_factory=list)


@dataclass
class MobLoadout:
    items: List[int] = field(default_factory=list)
    equipment: Dict[str, int] = field(default_factory=dict)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "zone"


def write_legacy_help_doc(path: Path, title: str, raw_text: str) -> None:
    path.write_text(f"# {title}\n\n```text\n{raw_text}\n```\n")


def read_index(path: Path) -> List[str]:
    entries: List[str] = []
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        if line == "$":
            break
        entries.append(line)
    return entries


def read_tilde_text(lines: List[str], i: int) -> Tuple[str, int]:
    buf: List[str] = []
    while i < len(lines):
        line = lines[i]
        if line.endswith("~"):
            stripped = line[:-1]
            if stripped:
                buf.append(stripped)
            i += 1
            break
        buf.append(line)
        i += 1
    txt = "\n".join(buf).strip()
    return txt, i


def parse_wld_file(path: Path, zone_num: int) -> Dict[int, Room]:
    lines = path.read_text(errors="ignore").splitlines()
    i = 0
    rooms: Dict[int, Room] = {}
    while i < len(lines):
        line = lines[i].strip()
        if line == "$":
            break
        if not line.startswith("#"):
            i += 1
            continue
        roomid = int(line[1:])
        i += 1
        title, i = read_tilde_text(lines, i)
        desc, i = read_tilde_text(lines, i)
        if i >= len(lines):
            break
        sector_line = lines[i].strip()
        i += 1
        sector_num = 1
        room_flags = 0
        parts = sector_line.split()
        if len(parts) > 1 and re.match(r"^-?\d+$", parts[1]):
            room_flags = int(parts[1])
        if parts and re.match(r"^-?\d+$", parts[-1]):
            sector_num = int(parts[-1])
        sector_to_biome = {
            0: "house",      # inside
            1: "city",       # city
            2: "land",       # field
            3: "forest",     # forest
            4: "shore",      # hills
            5: "mountains",  # mountain
            6: "water",      # swim water
            7: "water",      # no-swim water
            8: "shore",      # underwater/flying equivalents
            9: "desert",     # flight/desert in derivatives
            10: "road",      # road
            11: "swamp",     # swamp
        }
        biome = sector_to_biome.get(sector_num, "city")
        tags: List[str] = []
        pvp: Optional[bool] = None
        # Circle room flags mapped to GoMUD-safe tags/fields.
        if room_flags & (1 << 1):   # ROOM_DEATH
            tags.append("deathtrap")
        if room_flags & (1 << 2):   # ROOM_NOMOB
            tags.append("nomob")
        if room_flags & (1 << 3):   # ROOM_INDOORS
            biome = "house" if biome in {"city", "land", "road"} else biome
            tags.append("indoors")
        if room_flags & (1 << 4):   # ROOM_PEACEFUL
            pvp = False
            tags.append("peaceful")
        if room_flags & (1 << 5):   # ROOM_SOUNDPROOF
            tags.append("soundproof")
        if room_flags & (1 << 6):   # ROOM_NOTRACK
            tags.append("notrack")
        if room_flags & (1 << 7):   # ROOM_NOMAGIC
            tags.append("nomagic")
        if room_flags & (1 << 8):   # ROOM_TUNNEL
            tags.append("tunnel")
        if room_flags & (1 << 9):   # ROOM_PRIVATE
            tags.append("private")
        if room_flags & (1 << 10):  # ROOM_GODROOM
            tags.append("godroom")
        if room_flags & (1 << 16):  # ROOM_NEUTRAL
            pvp = False
            tags.append("neutral")
        if room_flags & (1 << 27):  # ROOM_ARENA
            pvp = True
            tags.append("arena")
        room = Room(
            roomid=roomid,
            zone_num=zone_num,
            title=title or f"Room {roomid}",
            description=desc or "An unremarkable place.",
            biome=biome,
            pvp=pvp,
            tags=tags,
        )
        while i < len(lines):
            cmd = lines[i].strip()
            if cmd == "S":
                i += 1
                break
            if cmd.startswith("D"):
                dnum = int(cmd[1:])
                i += 1
                door_desc, i = read_tilde_text(lines, i)
                door_keywords, i = read_tilde_text(lines, i)
                if i < len(lines):
                    vals = lines[i].strip().split()
                    i += 1
                    if len(vals) >= 3:
                        door_type = int(vals[0]) if re.match(r"^-?\d+$", vals[0]) else 0
                        key_vnum = int(vals[1]) if re.match(r"^-?\d+$", vals[1]) else -1
                        to_room = int(vals[2])
                        if to_room >= 0 and dnum in DIR_MAP:
                            exit_info = {"roomid": to_room}
                            if door_type > 0:
                                lock_difficulty = 1
                                if door_type >= 2:
                                    lock_difficulty = 5
                                if key_vnum >= 0:
                                    lock_difficulty = max(lock_difficulty, 2)
                                exit_info["lock"] = {"difficulty": lock_difficulty}
                                if key_vnum >= 0:
                                    exit_info["key_vnum"] = key_vnum
                            # Only mark exits as secret when text explicitly suggests hidden/secret doors.
                            keyword_text = f"{door_keywords} {door_desc}".lower()
                            if door_type > 0 and ("secret" in keyword_text or "hidden" in keyword_text):
                                exit_info["secret"] = True
                            room.exits[DIR_MAP[dnum]] = exit_info
            elif cmd == "E":
                i += 1
                ex_keywords, i = read_tilde_text(lines, i)
                ex_desc, i = read_tilde_text(lines, i)
                keywords = [k.strip().lower() for k in ex_keywords.split() if k.strip()]
                if keywords and ex_desc:
                    primary = keywords[0]
                    room.nouns[primary] = ex_desc
                    for alias in keywords[1:]:
                        if alias not in room.nouns:
                            room.nouns[alias] = f":{primary}"
            else:
                i += 1
        rooms[roomid] = room
    return rooms


def parse_obj_file(path: Path, zone_num: int) -> Dict[int, Obj]:
    lines = path.read_text(errors="ignore").splitlines()
    i = 0
    objs: Dict[int, Obj] = {}
    while i < len(lines):
        line = lines[i].strip()
        if line == "$":
            break
        if not line.startswith("#"):
            i += 1
            continue
        itemid = int(line[1:])
        i += 1
        aliases, i = read_tilde_text(lines, i)
        short_desc, i = read_tilde_text(lines, i)
        long_desc, i = read_tilde_text(lines, i)
        action_desc, i = read_tilde_text(lines, i)
        if i + 2 >= len(lines):
            break
        header = [int(x) for x in lines[i].split() if re.match(r"^-?\d+$", x)]
        i += 1
        values = [int(x) for x in lines[i].split() if re.match(r"^-?\d+$", x)]
        i += 1
        cost_line = lines[i].split()
        i += 1
        weight = int(float(cost_line[0])) if cost_line else 1
        cost = int(float(cost_line[1])) if len(cost_line) > 1 else 0
        obj_type = header[0] if header else 13
        wear_flags = header[2] if len(header) > 2 else 0
        obj = Obj(
            itemid=itemid,
            zone_num=zone_num,
            aliases=aliases,
            short_desc=short_desc,
            long_desc=long_desc,
            action_desc=action_desc,
            extra_descs=[],
            obj_type=obj_type,
            wear_flags=wear_flags,
            values=values[:4] + [0] * (4 - len(values[:4])),
            affects=[],
            weight=max(1, weight),
            cost=max(0, cost),
        )
        while i < len(lines):
            cmd = lines[i].strip()
            if cmd.startswith("#") or cmd == "$":
                break
            if cmd == "E":
                i += 1
                _, i = read_tilde_text(lines, i)
                ex_desc, i = read_tilde_text(lines, i)
                if ex_desc:
                    obj.extra_descs.append(ex_desc)
            elif cmd == "A":
                i += 1
                if i < len(lines):
                    parts = lines[i].strip().split()
                    if len(parts) >= 2 and re.match(r"^-?\d+$", parts[0]) and re.match(r"^-?\d+$", parts[1]):
                        obj.affects.append((int(parts[0]), int(parts[1])))
                    i += 1
            else:
                i += 1
        objs[itemid] = obj
    return objs


def parse_mob_file(path: Path, zone_num: int) -> Dict[int, Mob]:
    lines = path.read_text(errors="ignore").splitlines()
    i = 0
    mobs: Dict[int, Mob] = {}
    while i < len(lines):
        line = lines[i].strip()
        if line == "$":
            break
        if not line.startswith("#"):
            i += 1
            continue
        mobid = int(line[1:])
        i += 1
        aliases, i = read_tilde_text(lines, i)
        short_desc, i = read_tilde_text(lines, i)
        long_desc, i = read_tilde_text(lines, i)
        detailed_desc, i = read_tilde_text(lines, i)
        if i + 2 >= len(lines):
            break
        stats = lines[i].split()
        i += 1
        combat = lines[i].split()
        i += 1
        cash = lines[i].split()
        i += 1
        i += 1  # position/sex
        ambient_lines: List[str] = []
        while i < len(lines):
            extra = lines[i].strip()
            i += 1
            if extra == "E":
                break
            if extra.lower().startswith("noise:"):
                noise_text = extra.split(":", 1)[1].strip()
                if noise_text:
                    ambient_lines.append(noise_text)
        level = int(combat[0]) if combat and re.match(r"^-?\d+$", combat[0]) else 1
        act_flags = int(stats[0]) if stats and re.match(r"^-?\d+$", stats[0]) else 0
        alignment = int(stats[8]) if len(stats) > 8 and re.match(r"^-?\d+$", stats[8]) else 0
        gold = int(cash[0]) if cash and re.match(r"^-?\d+$", cash[0]) else 0
        mobs[mobid] = Mob(
            mobid=mobid,
            zone_num=zone_num,
            aliases=aliases,
            short_desc=short_desc,
            long_desc=long_desc,
            detailed_desc=detailed_desc,
            ambient_lines=ambient_lines,
            level=max(1, level),
            alignment=alignment,
            gold=max(0, gold),
            act_flags=act_flags,
        )
    return mobs


def parse_zone_file(path: Path) -> Zone:
    lines = path.read_text(errors="ignore").splitlines()
    if not lines or not lines[0].startswith("#"):
        raise ValueError(f"Bad zone file: {path}")
    zone_num = int(lines[0][1:])
    i = 1
    name, i = read_tilde_text(lines, i)
    top = 0
    if i < len(lines):
        parts = lines[i].split()
        i += 1
        if parts:
            top = int(parts[0])
    commands: List[List[str]] = []
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line == "S" or line == "$":
            break
        commands.append(line.split())
    return Zone(number=zone_num, name=name or f"Zone {zone_num}", top=top, commands=commands)


def parse_shop_file(path: Path) -> List[ShopDef]:
    lines = path.read_text(errors="ignore").splitlines()
    i = 0
    shops: List[ShopDef] = []
    if not lines:
        return shops
    if lines[0].startswith("CircleMUD v3.0 Shop File"):
        i = 1
    while i < len(lines):
        line = lines[i].strip()
        if line == "$":
            break
        if not line.startswith("#"):
            i += 1
            continue
        i += 1
        producing: List[int] = []
        while i < len(lines):
            v = lines[i].strip()
            i += 1
            if v == "-1":
                break
            if re.match(r"^-?\d+$", v):
                producing.append(int(v))
        i += 2  # buy/sell profit
        while i < len(lines):
            v = lines[i].strip()
            i += 1
            if v == "-1":
                break
        for _ in range(7):  # message strings
            if i < len(lines):
                _, i = read_tilde_text(lines, i)
        i += 2  # temperament + bitvector
        keeper = -1
        if i < len(lines) and re.match(r"^-?\d+$", lines[i].strip()):
            keeper = int(lines[i].strip())
            i += 1
        i += 5  # with_who + open/close times
        if keeper > 0:
            shops.append(ShopDef(keeper_mobid=keeper, producing_itemids=producing))
    return shops


def yquote(text: str) -> str:
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_zone_config(path: Path, zone_name: str, entry_room: int, default_biome: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"name: {zone_name}",
                f"roomid: {entry_room}",
                "autoscale:",
                "  minimum: 1",
                "  maximum: 50",
                f"defaultbiome: {default_biome}",
                "",
            ]
        )
    )


def write_room(path: Path, room: Room, zone_name: str) -> None:
    biome_symbols = {
        "city": ".",
        "road": ".",
        "house": "#",
        "land": ",",
        "farmland": ",",
        "forest": "T",
        "swamp": "~",
        "water": "~",
        "shore": ":",
        "desert": "*",
        "mountains": "^",
        "cave": "%",
        "dungeon": "%",
        "fort": "H",
        "cliffs": "^",
        "snow": "S",
    }
    mapsymbol = biome_symbols.get(room.biome, ".")
    if "arena" in room.tags:
        mapsymbol = "!"
    if "deathtrap" in room.tags:
        mapsymbol = "X"
    out: List[str] = [
        f"roomid: {room.roomid}",
        f"zone: {zone_name}",
        f"title: {yquote(room.title)}",
        "description: |-",
    ]
    for dl in (room.description or "An empty room.").splitlines():
        out.append(f"  {dl}")
    out.extend([f"mapsymbol: {mapsymbol}", f"biome: {room.biome}"])
    if room.pvp is not None:
        out.append(f"pvp: {'true' if room.pvp else 'false'}")
    if room.tags:
        out.append(f"tags: [{', '.join(room.tags)}]")
    if room.exits:
        out.append("exits:")
        for d, exit_info in room.exits.items():
            out.extend([f"  {d}:", f"    roomid: {exit_info['roomid']}"])
            if "secret" in exit_info and exit_info["secret"]:
                out.append("    secret: true")
            if "lock" in exit_info:
                out.append("    lock:")
                out.append(f"      difficulty: {exit_info['lock']['difficulty']}")
    else:
        out.append("exits: {}")
    if room.nouns:
        out.append("nouns:")
        for noun in sorted(room.nouns.keys()):
            out.append(f"  {noun}: {yquote(room.nouns[noun])}")
    if room.containers:
        out.append("containers:")
        for cname in sorted(room.containers.keys()):
            cdata = room.containers[cname]
            if isinstance(cdata, dict) and cdata.get("lock"):
                out.append(f"  {cname}:")
                out.append("    lock:")
                out.append(f"      difficulty: {cdata['lock'].get('difficulty', 1)}")
            else:
                out.append(f"  {cname}: {{}}")
    if room.spawninfo:
        out.append("spawninfo:")
        for s in room.spawninfo:
            if "mobid" in s:
                out.extend([f"- mobid: {s['mobid']}", f"  respawnrate: {s['respawn']} real minutes"])
            elif "itemid" in s:
                out.append(f"- itemid: {s['itemid']}")
                if s.get("container"):
                    out.append(f"  container: {s['container']}")
                out.append(f"  respawnrate: {s['respawn']} real minutes")
    out.append("")
    path.write_text("\n".join(out))


def write_mob(
    path: Path,
    mob: Mob,
    zone_name: str,
    shop_items: Optional[List[int]] = None,
    loadout: Optional[MobLoadout] = None,
) -> None:
    name = mob.short_desc.strip() or f"mob {mob.mobid}"
    desc_parts: List[str] = [(mob.detailed_desc or mob.long_desc or "A creature lurks here.").strip()]
    for ambient in mob.ambient_lines:
        if ambient and ambient not in desc_parts:
            desc_parts.append(ambient)
    desc = "\n\n".join(desc_parts)
    is_hostile = bool(
        mob.act_flags
        & (MOB_FLAG_AGGRESSIVE | MOB_FLAG_AGGR_EVIL | MOB_FLAG_AGGR_GOOD | MOB_FLAG_AGGR_NEUTRAL)
    )
    max_wander = 0 if (mob.act_flags & MOB_FLAG_SENTINEL) else 20
    if mob.act_flags & MOB_FLAG_STAY_ZONE:
        max_wander = min(max_wander, 10) if max_wander > 0 else 0
    activity_level = 45 if (mob.act_flags & MOB_FLAG_SCAVENGER) else 20
    out = [
        f"mobid: {mob.mobid}",
        f"zone: {zone_name}",
        "itemdropchance: 1",
        f"hostile: {'true' if is_hostile else 'false'}",
        f"maxwander: {max_wander}",
        f"activitylevel: {activity_level}",
        "character:",
        f"  name: {yquote(name)}",
        f"  description: {yquote(desc)}",
        "  raceid: 1",
        f"  level: {mob.level}",
        f"  alignment: {mob.alignment}",
        f"  gold: {mob.gold}",
    ]
    if shop_items:
        out.append("  shop:")
        for itemid in shop_items:
            out.extend(
                [
                    f"    - itemid: {itemid}",
                    "      quantitymax: 0",
                    "      quantity: 0",
                ]
            )
    if loadout:
        if loadout.items:
            out.append("  items:")
            for itemid in loadout.items:
                out.append(f"    - itemid: {itemid}")
        if loadout.equipment:
            out.append("  equipment:")
            for slot in ["weapon", "offhand", "head", "neck", "body", "belt", "gloves", "ring", "legs", "feet"]:
                if slot in loadout.equipment:
                    out.extend([f"    {slot}:", f"      itemid: {loadout.equipment[slot]}"])
    out.append("")
    path.write_text("\n".join(out))


def map_circle_wear_to_slot(wear_pos: int, itemid: int, all_objs: Dict[int, Obj]) -> Optional[str]:
    pos_map = {
        1: "ring",
        2: "neck",
        3: "body",
        4: "head",
        5: "legs",
        6: "feet",
        7: "gloves",
        8: "body",
        9: "offhand",
        10: "neck",
        11: "belt",
        12: "gloves",
        13: "weapon",
        14: "offhand",
        15: "offhand",
        16: "head",
    }
    if wear_pos in pos_map:
        slot = pos_map[wear_pos]
        obj = all_objs.get(itemid)
        if obj:
            inferred_type, _ = infer_item_type(obj)
            # If the reset wear position maps oddly but the item is definitely a weapon, prefer weapon.
            if inferred_type == "weapon":
                return "weapon"
        return slot
    obj = all_objs.get(itemid)
    if obj:
        for bit, slot in WEAR_SLOT_MAP.items():
            if obj.wear_flags & bit:
                return slot
    return None


def infer_item_type(obj: Obj) -> Tuple[str, Optional[str]]:
    # Circle object type constants mapped into GoMUD known item types.
    if obj.obj_type in OBJ_TYPE_WEAPON_SUBTYPE:
        return "weapon", OBJ_TYPE_WEAPON_SUBTYPE[obj.obj_type]
    if obj.obj_type == 2:
        return "scroll", "usable"
    if obj.obj_type in {10, 18}:
        return "key", "usable"
    if obj.obj_type == 19:
        return "food", "edible"
    if obj.obj_type == 23:
        return "drink", "drinkable"
    if obj.obj_type in {24, 25}:
        return "potion", "usable"
    # If wearable bits are present, choose mapped equipment slot type.
    for bit, slot in WEAR_SLOT_MAP.items():
        if obj.wear_flags & bit:
            if slot in {"weapon", "offhand", "head", "neck", "body", "belt", "gloves", "ring", "legs", "feet"}:
                return slot, "wearable"
    return "object", None


def map_affects(obj: Obj) -> Tuple[Dict[str, int], int]:
    statmods: Dict[str, int] = {}
    damage_reduction = 0
    for loc, mod in obj.affects:
        if mod == 0:
            continue
        # Circle apply types -> closest GoMUD statmods.
        if loc == 1:  # STR
            statmods["strength"] = statmods.get("strength", 0) + mod
        elif loc == 2:  # DEX
            statmods["speed"] = statmods.get("speed", 0) + mod
        elif loc == 3:  # INT
            statmods["smarts"] = statmods.get("smarts", 0) + mod
        elif loc == 4:  # WIS
            statmods["mysticism"] = statmods.get("mysticism", 0) + mod
        elif loc == 5:  # CON
            statmods["vitality"] = statmods.get("vitality", 0) + mod
        elif loc == 6:  # CHA
            statmods["perception"] = statmods.get("perception", 0) + mod
        elif loc == 17:  # AC
            # Circle AC tends lower-is-better; negative apply improves armor.
            if mod < 0:
                damage_reduction += abs(mod)
        elif loc == 18:  # hitroll
            statmods["perception"] = statmods.get("perception", 0) + mod
        elif loc == 19:  # damroll
            statmods["damage"] = statmods.get("damage", 0) + mod
    if damage_reduction > 100:
        damage_reduction = 100
    return statmods, damage_reduction


def write_item(path: Path, obj: Obj, key_lock_map: Dict[int, str]) -> None:
    aliases = obj.aliases.split()
    name = obj.short_desc.strip() or f"item {obj.itemid}"
    simple = aliases[0] if aliases else f"item{obj.itemid}"
    desc_parts: List[str] = []
    base_desc = obj.long_desc.strip() or "An item lies here."
    desc_parts.append(base_desc)
    action_desc = obj.action_desc.strip()
    if action_desc and action_desc not in desc_parts:
        desc_parts.append(action_desc)
    for ex_desc in obj.extra_descs:
        ex = ex_desc.strip()
        if ex and ex not in desc_parts:
            desc_parts.append(ex)
    desc = "\n\n".join(desc_parts)
    item_type, subtype = infer_item_type(obj)
    out = [
        f"itemid: {obj.itemid}",
        f"name: {yquote(name)}",
        f"namesimple: {yquote(simple)}",
        f"description: {yquote(desc)}",
        f"type: {item_type}",
        "hands: 1",
    ]
    if subtype:
        out.append(f"subtype: {subtype}")
    if item_type == "key":
        lock_id = key_lock_map.get(obj.itemid)
        if lock_id:
            out.append(f"keylockid: {lock_id}")
    statmods, dmg_red = map_affects(obj)
    if dmg_red > 0 and item_type in {"offhand", "head", "neck", "body", "belt", "gloves", "ring", "legs", "feet"}:
        out.append(f"damagereduction: {dmg_red}")
    if statmods:
        out.append("statmods:")
        for k in sorted(statmods.keys()):
            out.append(f"  {k}: {statmods[k]}")
    if item_type == "weapon":
        dice_sides = max(2, obj.values[2] if obj.values[2] > 0 else 4)
        dice_num = max(1, obj.values[1] if obj.values[1] > 0 else 1)
        out.extend(
            [
                "damage:",
                f"  diceroll: {dice_num}d{dice_sides}",
            ]
        )
    elif item_type in {"food", "drink", "potion", "scroll"}:
        out.append(f"uses: {max(1, obj.values[0] if obj.values else 1)}")
    else:
        out.append("uses: 0")
    out.append("")
    path.write_text("\n".join(out))


def apply_zone_resets(
    zones: Dict[int, Zone],
    rooms: Dict[int, Room],
    all_objs: Dict[int, Obj],
) -> Tuple[Dict[int, MobLoadout], Dict[int, str]]:
    mob_loadouts: Dict[int, MobLoadout] = {}
    key_lock_map: Dict[int, str] = {}
    # First pass: static room exits can carry lock->key associations.
    for room in rooms.values():
        for direction, exit_info in room.exits.items():
            if "lock" in exit_info and "key_vnum" in exit_info:
                key_vnum = int(exit_info["key_vnum"])
                key_lock_map.setdefault(key_vnum, f"{room.roomid}-{direction}")
    for z in zones.values():
        last_mobid: Optional[int] = None
        # Tracks latest room container spawned by object vnum for this zone stream.
        latest_container_by_objid: Dict[int, Tuple[int, str]] = {}
        for cmd in z.commands:
            if not cmd:
                continue
            c = cmd[0]
            if c == "M" and len(cmd) >= 5:
                mobid = int(cmd[2])
                roomid = int(cmd[4])
                last_mobid = mobid
                if roomid in rooms:
                    rooms[roomid].spawninfo.append({"mobid": mobid, "respawn": 5})
            elif c == "O" and len(cmd) >= 5:
                itemid = int(cmd[2])
                roomid = int(cmd[4])
                if roomid in rooms:
                    rooms[roomid].spawninfo.append({"itemid": itemid, "respawn": 10})
                    obj = all_objs.get(itemid)
                    if obj and obj.obj_type == 15:
                        cbase = slugify((obj.aliases.split()[0] if obj.aliases else f"container_{itemid}"))[:28]
                        cname = f"{cbase}_{itemid}"
                        rooms[roomid].containers[cname] = {}
                        latest_container_by_objid[itemid] = (roomid, cname)
                        # Circle container value[2] is key vnum for the lock (or -1/0 for none).
                        if len(obj.values) > 2 and obj.values[2] > 0:
                            rooms[roomid].containers[cname]["lock"] = {"difficulty": 1}
                            key_lock_map.setdefault(int(obj.values[2]), f"{roomid}-{cname}")
            elif c == "G" and len(cmd) >= 3 and last_mobid:
                itemid = int(cmd[2])
                ml = mob_loadouts.setdefault(last_mobid, MobLoadout())
                if itemid not in ml.items:
                    ml.items.append(itemid)
            elif c == "E" and len(cmd) >= 5 and last_mobid:
                itemid = int(cmd[2])
                wear_pos = int(cmd[4])
                slot = map_circle_wear_to_slot(wear_pos, itemid, all_objs)
                if slot:
                    ml = mob_loadouts.setdefault(last_mobid, MobLoadout())
                    ml.equipment[slot] = itemid
            elif c == "P" and len(cmd) >= 5:
                itemid = int(cmd[2])
                container_objid = int(cmd[4])
                if container_objid in latest_container_by_objid:
                    roomid, cname = latest_container_by_objid[container_objid]
                    if roomid in rooms:
                        rooms[roomid].spawninfo.append(
                            {"itemid": itemid, "container": cname, "respawn": 10}
                        )
            elif c == "D" and len(cmd) >= 5:
                roomid = int(cmd[2])
                dnum = int(cmd[3])
                state = int(cmd[4])
                direction = DIR_MAP.get(dnum)
                room = rooms.get(roomid)
                if not room or not direction:
                    continue
                exit_info = room.exits.get(direction)
                if not exit_info:
                    continue
                # Circle reset states: 0=open, 1=closed, 2=closed+locked.
                # GoMUD exposes lock semantics but no closed-state toggle in room YAML.
                if state >= 2:
                    if "lock" not in exit_info:
                        exit_info["lock"] = {"difficulty": 1}
                elif state == 0:
                    exit_info.pop("lock", None)
    return mob_loadouts, key_lock_map


def infer_zone_number_from_filename(name: str) -> Optional[int]:
    m = re.match(r"(\d+)\.", name)
    return int(m.group(1)) if m else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--darkpawns", required=True, help="Path to DarkPawns root")
    parser.add_argument("--dpgo", required=True, help="Path to DPGo root")
    args = parser.parse_args()

    darkpawns = Path(args.darkpawns)
    dpgo = Path(args.dpgo)
    world = darkpawns / "lib" / "world"
    out_world = dpgo / "_datafiles" / "world" / "default"
    out_rooms = out_world / "rooms"
    out_mobs = out_world / "mobs"
    out_items = out_world / "items"

    # Replace existing GoMud world content with migrated DarkPawns content.
    for p in [out_rooms, out_mobs, out_items]:
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)

    zones: Dict[int, Zone] = {}
    zone_index = read_index(world / "zon" / "index")
    for entry in zone_index:
        z = parse_zone_file(world / "zon" / entry)
        zones[z.number] = z

    all_rooms: Dict[int, Room] = {}
    for entry in read_index(world / "wld" / "index"):
        znum = infer_zone_number_from_filename(entry) or 0
        all_rooms.update(parse_wld_file(world / "wld" / entry, znum))

    all_mobs: Dict[int, Mob] = {}
    for entry in read_index(world / "mob" / "index"):
        znum = infer_zone_number_from_filename(entry) or 0
        all_mobs.update(parse_mob_file(world / "mob" / entry, znum))

    all_objs: Dict[int, Obj] = {}
    for entry in read_index(world / "obj" / "index"):
        znum = infer_zone_number_from_filename(entry) or 0
        all_objs.update(parse_obj_file(world / "obj" / entry, znum))

    mob_loadouts, key_lock_map = apply_zone_resets(zones, all_rooms, all_objs)
    all_shops: List[ShopDef] = []
    shp_index = world / "shp" / "index"
    if shp_index.exists():
        for entry in read_index(shp_index):
            shp_file = world / "shp" / entry
            if shp_file.exists():
                all_shops.extend(parse_shop_file(shp_file))
    valid_item_ids = set(all_objs.keys())
    shop_map: Dict[int, List[int]] = {}
    for s in all_shops:
        items = [itemid for itemid in s.producing_itemids if itemid in valid_item_ids]
        if not items:
            continue
        if s.keeper_mobid not in shop_map:
            shop_map[s.keeper_mobid] = []
        for itemid in items:
            if itemid not in shop_map[s.keeper_mobid]:
                shop_map[s.keeper_mobid].append(itemid)

    zone_folder_map: Dict[int, str] = {}
    for znum, z in sorted(zones.items()):
        folder = f"darkpawns_{znum}_{slugify(z.name)[:40]}"
        zone_folder_map[znum] = folder
        zdir = out_rooms / folder
        zdir.mkdir(parents=True, exist_ok=True)
        zone_rooms = [r for r in all_rooms.values() if r.zone_num == znum]
        room_candidates = [r.roomid for r in zone_rooms]
        entry_room = min(room_candidates) if room_candidates else max(1, z.top)
        biome_counts: Dict[str, int] = {}
        for r in zone_rooms:
            biome_counts[r.biome] = biome_counts.get(r.biome, 0) + 1
        default_biome = "city"
        if biome_counts:
            default_biome = max(biome_counts.items(), key=lambda kv: kv[1])[0]
        write_zone_config(zdir / "zone-config.yaml", z.name, entry_room, default_biome)

    fallback_folder = "darkpawns_misc"
    (out_rooms / fallback_folder).mkdir(exist_ok=True)

    for roomid, room in sorted(all_rooms.items()):
        folder = zone_folder_map.get(room.zone_num, fallback_folder)
        write_room(out_rooms / folder / f"{roomid}.yaml", room, zones.get(room.zone_num, Zone(room.zone_num, f"Zone {room.zone_num}", room.roomid)).name)

    for mobid, mob in sorted(all_mobs.items()):
        folder = zone_folder_map.get(mob.zone_num, fallback_folder)
        mdir = out_mobs / folder
        mdir.mkdir(parents=True, exist_ok=True)
        mob_name = slugify(mob.short_desc or f"mob_{mobid}")[:48]
        write_mob(
            mdir / f"{mobid}-{mob_name}.yaml",
            mob,
            zones.get(mob.zone_num, Zone(mob.zone_num, f"Zone {mob.zone_num}", 0)).name,
            shop_map.get(mobid),
            mob_loadouts.get(mobid),
        )

    item_folder = out_items / "darkpawns-0"
    item_folder.mkdir(parents=True, exist_ok=True)
    for itemid, obj in sorted(all_objs.items()):
        item_name = slugify(obj.short_desc or f"item_{itemid}")[:48]
        write_item(item_folder / f"{itemid}-{item_name}.yaml", obj, key_lock_map)

    # Port a few high-value text assets.
    templates = out_world / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    text_dir = darkpawns / "lib" / "text"
    for src_name, dst_name in [
        ("motd", "darkpawns_motd.template"),
        ("news", "darkpawns_news.template"),
        ("credits", "darkpawns_credits.template"),
        ("info", "darkpawns_info.template"),
    ]:
        src = text_dir / src_name
        if src.exists():
            shutil.copyfile(src, templates / dst_name)
    help_src = text_dir / "help"
    help_dst = templates / "help"
    help_dst.mkdir(parents=True, exist_ok=True)
    for fname in ["commands.hlp", "info.hlp", "socials.hlp", "spells.hlp", "wizhelp.hlp"]:
        src = help_src / fname
        if src.exists():
            raw = src.read_text(errors="ignore")
            write_legacy_help_doc(
                help_dst / f"darkpawns-{fname.replace('.hlp', '')}.md",
                "DarkPawns Legacy Help",
                raw,
            )
    for src_name, topic_name, title in [
        ("imotd", "darkpawns-imotd", "DarkPawns Immortal MOTD"),
        ("immlist", "darkpawns-immlist", "DarkPawns Immortal List"),
        ("wizlist", "darkpawns-wizlist", "DarkPawns Wizard List"),
        ("policies", "darkpawns-policies", "DarkPawns Policies"),
        ("handbook", "darkpawns-handbook", "DarkPawns Handbook"),
        ("background", "darkpawns-background", "DarkPawns Background"),
        ("future", "darkpawns-future", "DarkPawns Future Notes"),
    ]:
        src = text_dir / src_name
        if src.exists():
            write_legacy_help_doc(
                help_dst / f"{topic_name}.md",
                title,
                src.read_text(errors="ignore"),
            )
    socials_src = darkpawns / "lib" / "misc" / "socials"
    if socials_src.exists():
        raw_socials = socials_src.read_text(errors="ignore")
        (templates / "darkpawns_socials.template").write_text(raw_socials)

    print(
        f"Imported {len(zones)} zones, {len(all_rooms)} rooms, {len(all_mobs)} mobs, "
        f"{len(all_objs)} objects, {len(shop_map)} shopkeepers."
    )


if __name__ == "__main__":
    main()
