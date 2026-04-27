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
}

WEAR_SLOT_MAP = {
    1 << 1: "ring1",     # finger
    1 << 2: "neck1",     # neck
    1 << 3: "body",      # body
    1 << 4: "head",      # head
    1 << 5: "legs",      # legs
    1 << 6: "feet",      # feet
    1 << 7: "gloves",    # hands
    1 << 8: "body",      # arms -> body fallback
    1 << 9: "offhand",   # shield
    1 << 10: "neck1",    # about body -> closest
    1 << 11: "waist",    # waist
    1 << 12: "wrist1",   # wrist
    1 << 13: "weapon",   # wield
    1 << 14: "offhand",  # hold
}

# GoMUD equipment slot names that `infer_item_type()` can return with subtype
# "wearable" (armor and jewelry). Used to reconcile Circle zone `E` wear
# positions that do not match the object's real equipment semantics.
INFERRED_WEAR_EQUIP_SLOTS = frozenset(
    {
        "ring1",
        "ring2",
        "neck1",
        "neck2",
        "wrist1",
        "wrist2",
        "head",
        "body",
        "waist",
        "back",
        "light",
        "gloves",
        "legs",
        "feet",
    }
)

# Item types that should never occupy armor/jewelry slots in GoMUD mob YAML.
# Circle zones occasionally assign these to arbitrary wear locations.
NONWEAR_EQUIP_TYPES = frozenset(
    {
        "key",
        "potion",
        "drink",
        "food",
        "scroll",
        "readable",
        "lockpicks",
        "junk",
        "service",
        "gemstone",
        "object",
    }
)

MOB_FLAG_SENTINEL = 1 << 1
MOB_FLAG_SCAVENGER = 1 << 2
MOB_FLAG_AWARE = 1 << 4
MOB_FLAG_AGGRESSIVE = 1 << 5
MOB_FLAG_STAY_ZONE = 1 << 6
MOB_FLAG_WIMPY = 1 << 7
MOB_FLAG_AGGR_EVIL = 1 << 8
MOB_FLAG_AGGR_GOOD = 1 << 9
MOB_FLAG_AGGR_NEUTRAL = 1 << 10
MOB_FLAG_MEMORY = 1 << 11
MOB_FLAG_HELPER = 1 << 12
MOB_FLAG_HUNTER = 1 << 18
MOB_FLAG_AGGR24 = 1 << 19
MOB_FLAG_RANDZON = 1 << 20
MOB_FLAG_RARE = 1 << 22
MOB_FLAG_LOOTS = 1 << 23


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
    race_hint: Optional[int]
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
    extra_flags: int
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
    lifespan_minutes: int = 30
    reset_mode: int = 2
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


def has_boundary_phrase(text: str, phrase: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(phrase.strip())}(?![a-z0-9])",
            text,
        )
    )


def has_any_boundary_phrase(text: str, phrases: tuple[str, ...] | set[str]) -> bool:
    return any(has_boundary_phrase(text, phrase) for phrase in phrases)


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
            12: "desert",    # extended desert/sandstorm sector
            13: "water",     # steam vent / hot-water derivative sector
        }
        biome = sector_to_biome.get(sector_num, "city")
        tags: List[str] = []
        pvp: Optional[bool] = None
        # Circle room flags mapped to GoMUD-safe tags/fields.
        if room_flags & (1 << 0):   # ROOM_DARK
            tags.append("dark")
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
        if room_flags & (1 << 11):  # ROOM_HOUSE
            tags.append("house")
        if room_flags & (1 << 13):  # ROOM_ATRIUM
            tags.append("atrium")
        if room_flags & (1 << 16):  # ROOM_NEUTRAL
            pvp = False
            tags.append("neutral")
        if room_flags & (1 << 17):  # ROOM_BFR
            tags.append("badrecall")
        if room_flags & (1 << 18):  # ROOM_REGENROOM
            tags.append("regenroom")
        if room_flags & (1 << 19):  # ROOM_NO_WHO_ROOM
            tags.append("hidden-who")
        if room_flags & (1 << 20):  # ROOM_SECRET_MARK
            tags.append("secret-mark")
        if room_flags & (1 << 21):  # ROOM_FLOW_NORTH
            tags.append("flow-north")
        if room_flags & (1 << 22):  # ROOM_FLOW_SOUTH
            tags.append("flow-south")
        if room_flags & (1 << 23):  # ROOM_FLOW_EAST
            tags.append("flow-east")
        if room_flags & (1 << 24):  # ROOM_FLOW_WEST
            tags.append("flow-west")
        if room_flags & (1 << 25):  # ROOM_FLOW_UP
            tags.append("flow-up")
        if room_flags & (1 << 26):  # ROOM_FLOW_DOWN
            tags.append("flow-down")
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
                if not re.match(r"^D-?\d+$", cmd):
                    i += 1
                    continue
                dnum = int(cmd[1:])
                i += 1
                door_desc, i = read_tilde_text(lines, i)
                door_keywords, i = read_tilde_text(lines, i)
                door_keyword_list = [k.strip().lower() for k in door_keywords.split() if k.strip()]
                if door_desc and door_keyword_list:
                    primary = door_keyword_list[0]
                    if primary not in room.nouns:
                        room.nouns[primary] = door_desc
                    for alias in door_keyword_list[1:]:
                        if alias not in room.nouns:
                            room.nouns[alias] = f":{primary}"
                if i < len(lines):
                    vals = lines[i].strip().split()
                    i += 1
                    if len(vals) >= 3:
                        door_type = int(vals[0]) if re.match(r"^-?\d+$", vals[0]) else 0
                        key_vnum = int(vals[1]) if re.match(r"^-?\d+$", vals[1]) else -1
                        to_room = int(vals[2]) if re.match(r"^-?\d+$", vals[2]) else -1
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
        weight = 1
        if cost_line:
            try:
                weight = int(float(cost_line[0]))
            except ValueError:
                weight = 1
        cost = 0
        if len(cost_line) > 1:
            try:
                cost = int(float(cost_line[1]))
            except ValueError:
                cost = 0
        obj_type = header[0] if header else 13
        extra_flags = header[1] if len(header) > 1 else 0
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
            extra_flags=extra_flags,
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
        race_hint: Optional[int] = None
        while i < len(lines):
            extra = lines[i].strip()
            i += 1
            if extra == "E":
                break
            if extra.lower().startswith("noise:"):
                noise_text = extra.split(":", 1)[1].strip()
                if noise_text:
                    ambient_lines.append(noise_text)
            elif extra.lower().startswith("race:"):
                rv = extra.split(":", 1)[1].strip()
                if re.match(r"^-?\d+$", rv):
                    race_hint = int(rv)
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
            race_hint=race_hint,
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
    lifespan_minutes = 30
    reset_mode = 2
    if i < len(lines):
        parts = lines[i].split()
        i += 1
        if parts:
            top = int(parts[0])
        if len(parts) > 1 and re.match(r"^-?\d+$", parts[1]):
            lifespan_minutes = int(parts[1])
        if len(parts) > 2 and re.match(r"^-?\d+$", parts[2]):
            reset_mode = int(parts[2])
    commands: List[List[str]] = []
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line.startswith("*"):
            continue
        if "*" in line:
            line = line.split("*", 1)[0].strip()
            if not line:
                continue
        if line == "S" or line == "$":
            break
        commands.append(line.split())
    return Zone(
        number=zone_num,
        name=name or f"Zone {zone_num}",
        top=top,
        lifespan_minutes=max(1, lifespan_minutes),
        reset_mode=reset_mode,
        commands=commands,
    )


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
    circle_to_gomud_race = {
        0: 1,   # human
        1: 2,   # elf
        6: 4,   # troll
        9: 6,   # undead
        13: 21, # reptile
        14: 14, # arachnid -> giant spider
        17: 13, # vegetable -> tree
        21: 7,  # insect
        23: 21, # fish -> reptile fallback
        24: 11, # avian -> canine fallback
        26: 8,  # amphibian -> reptilian
        28: 15, # faery
        29: 8,  # ssaur
    }
    race_id = circle_to_gomud_race.get(mob.race_hint, 1)
    is_hostile = bool(
        mob.act_flags
        & (MOB_FLAG_AGGRESSIVE | MOB_FLAG_AGGR_EVIL | MOB_FLAG_AGGR_GOOD | MOB_FLAG_AGGR_NEUTRAL)
    )
    if mob.act_flags & MOB_FLAG_AGGR24:
        # Circle AGGR24 is still an explicit aggression hint.
        is_hostile = True
    max_wander = 0 if (mob.act_flags & MOB_FLAG_SENTINEL) else 20
    if mob.act_flags & MOB_FLAG_STAY_ZONE:
        max_wander = min(max_wander, 10) if max_wander > 0 else 0
    if mob.act_flags & MOB_FLAG_RANDZON:
        # Random-load/wanderers are usually intended to roam.
        max_wander = max(max_wander, 30)
    activity_level = 45 if (mob.act_flags & MOB_FLAG_SCAVENGER) else 20
    if mob.act_flags & MOB_FLAG_HELPER:
        activity_level = max(activity_level, 30)
    if mob.act_flags & MOB_FLAG_AWARE:
        activity_level = max(activity_level, 25)
    if mob.act_flags & MOB_FLAG_MEMORY:
        activity_level = max(activity_level, 35)
    if mob.act_flags & MOB_FLAG_LOOTS:
        activity_level = max(activity_level, 40)
    if mob.act_flags & MOB_FLAG_HUNTER:
        is_hostile = True
        activity_level = max(activity_level, 55)
    if mob.act_flags & MOB_FLAG_RARE:
        activity_level = min(activity_level, 15)
    if mob.act_flags & MOB_FLAG_WIMPY:
        activity_level = min(activity_level, 15)
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
        f"  raceid: {race_id}",
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
            for slot in [
                "weapon",
                "offhand",
                "head",
                "neck1",
                "neck2",
                "body",
                "waist",
                "back",
                "light",
                "gloves",
                "wrist1",
                "wrist2",
                "ring1",
                "ring2",
                "legs",
                "feet",
            ]:
                if slot in loadout.equipment:
                    out.extend([f"    {slot}:", f"      itemid: {loadout.equipment[slot]}"])
    out.append("")
    path.write_text("\n".join(out))


def map_circle_wear_to_slot(wear_pos: int, itemid: int, all_objs: Dict[int, Obj]) -> Optional[str]:
    pos_map = {
        0: "offhand",
        1: "ring1",
        2: "neck1",
        3: "body",
        4: "head",
        5: "legs",
        6: "feet",
        7: "gloves",
        8: "body",
        9: "offhand",
        10: "neck1",
        11: "waist",
        12: "wrist1",
        13: "weapon",
        14: "offhand",
        15: "offhand",
        16: "head",
        17: "weapon",
        18: "offhand",
        19: "ring2",
        20: "neck2",
        21: "head",
    }
    if wear_pos in pos_map:
        slot = pos_map[wear_pos]
        obj = all_objs.get(itemid)
        if obj:
            inferred_type, inferred_subtype = infer_item_type(obj)
            # If the reset wear position maps oddly but the item is definitely a weapon, prefer weapon.
            if inferred_type == "weapon":
                return "weapon"
            # Circle zones sometimes assign the wrong wear location (e.g. a ring
            # on the neck slot). Prefer the semantic wearable slot when it is
            # unambiguous and disagrees with the positional mapping.
            if (
                inferred_subtype == "wearable"
                and inferred_type in INFERRED_WEAR_EQUIP_SLOTS
                and inferred_type != slot
            ):
                return inferred_type
            if slot in INFERRED_WEAR_EQUIP_SLOTS and inferred_type in NONWEAR_EQUIP_TYPES:
                return "offhand"
            # Non-weapons are sometimes given WIELD in legacy data; hold them in
            # offhand instead of treating them as primary weapons.
            if slot == "weapon" and inferred_type != "weapon":
                return "offhand"
        return slot
    obj = all_objs.get(itemid)
    if obj:
        inferred_type, inferred_subtype = infer_item_type(obj)
        if inferred_type == "weapon":
            return "weapon"
        if inferred_subtype == "wearable" and inferred_type in INFERRED_WEAR_EQUIP_SLOTS:
            return inferred_type
        for bit, slot in WEAR_SLOT_MAP.items():
            if obj.wear_flags & bit:
                return slot
    return None


def infer_weapon_subtype(obj: Obj, primary_text: str, extended_text: str = "") -> str:
    # Prefer semantic weapon families over raw Circle type buckets when possible.
    # This keeps DarkPawns imports closer to intended weapon flavor.
    bludgeoning_markers = (
        "mace",
        "hammer",
        "warhammer",
        "war hammer",
        "morning star",
        "quarterstaff",
        "maul",
        "club",
        "staff",
        "sceptre",
        "scepter",
        "flail",
        "morningstar",
    )
    stabbing_markers = (
        "dagger",
        "dirk",
        "knife",
        "spear",
        "pike",
        "rapier",
        "lance",
        "trident",
        "stiletto",
        "needle",
        "spike",
        "bow",
        "crossbow",
        "arrow",
        "bolt",
    )
    slashing_markers = (
        "sword",
        "axe",
        "scimitar",
        "katana",
        "blade",
        "claw",
        "scythe",
        "halberd",
        "glaive",
    )
    marker_families = (
        ("bludgeoning", bludgeoning_markers),
        ("stabbing", stabbing_markers),
        ("slashing", slashing_markers),
    )
    for subtype, markers in marker_families:
        if any(has_boundary_phrase(primary_text, marker) for marker in markers):
            return subtype
    if extended_text:
        for subtype, markers in marker_families:
            if any(has_boundary_phrase(extended_text, marker) for marker in markers):
                return subtype
    return OBJ_TYPE_WEAPON_SUBTYPE.get(obj.obj_type, "slashing")


def infer_item_type(obj: Obj) -> Tuple[str, Optional[str]]:
    # Circle object type constants mapped into GoMUD known item types.
    gem_markers = {
        "gem",
        "gems",
        "gemstone",
        "jewel",
        "jewels",
        "ruby",
        "sapphire",
        "diamond",
        "emerald",
        "onyx",
        "opal",
        "pearl",
        "crystal",
        "stone",
        "hellstone",
        "serpentium",
        "blackrock",
    }
    text = f"{obj.aliases} {obj.short_desc}".lower()
    long_text = f"{obj.aliases} {obj.short_desc} {obj.long_desc} {obj.action_desc} {' '.join(obj.extra_descs)}".lower()
    def has_phrase(marker: str) -> bool:
        return has_boundary_phrase(text, marker)
    def has_long_phrase(marker: str) -> bool:
        return has_boundary_phrase(long_text, marker)
    light_markers = (" torch", "lantern", " lamp", "candle")
    portal_markers = (" portal", " gate", "gateway")
    container_junk_markers = ("corpse", "bones", "flesh", "dust", "carcass", "remains")
    container_service_markers = (
        "sack",
        "bag",
        "pack",
        "chest",
        "box",
        "safe",
        "bed",
        "desk",
        "table",
        "stool",
        "ground",
        "coffin",
    )
    # Furniture / large props that are often ITEM_OTHER in Circle.
    other_prop_markers = (
        "table",
        "desk",
        "bed",
        "stool",
        "sack",
        "bag",
        "pack",
        "chest",
        "box",
        "safe",
        "coffin",
    )
    other_service_markers = (
        "wall",
        "cloud",
        "circle",
        "flag",
        "candle",
        "brazier",
        "clock",
        "flute",
        "fountain",
        "altar",
        "totem",
        "obelisk",
        "sigil",
        "glyph",
        "orb",
        "idol",
        "statue",
        "board",
        "bulletin",
        "machine",
        "campfire",
        "wheel",
        "compass",
        "book",
        "paper",
        "jar",
        "platter",
        "throne",
        "tree",
        "nest",
        "beehive",
        "rope",
        "cylinder",
        "disk",
        "vial",
        "hammer",
        "kit",
        "halo",
        "torch",
        "mirror",
        "coin",
        "token",
    )
    other_junk_markers = (
        "corpse",
        "bones",
        "skull",
    )
    reagent_junk_markers = (
        "dust",
        "ash",
        "sand",
        "scale",
        "shard",
        "chunk",
        "pinch",
        "lens",
        "feather",
        "frog leg",
        "beholder",
        "powder",
        "reagent",
        "stone",
    )
    treasure_service_markers = (
        "talisman",
        "orb",
        "cross",
        "anvil",
        "coin",
        "bars",
        "throne",
        "portrait",
        "mirror",
        "idol",
        "relic",
        "sceptre",
        "scepter",
        "horn",
        "heart",
        "apple",
        "rose",
        "egg",
        "mirror",
        "halo",
        "ball",
    )
    semantic_wear_markers = [
        ("ring1", ("ring", "ring of", "band")),
        ("wrist1", ("bracelet",)),
        ("neck1", (" necklace", " amulet", " pendant", " medallion", " collar", " gorget")),
        ("head", (" helm", " helmet", " hood", " mask", " crown", " circlet", " tiara", " cap", " cowl", " headband", " headdress", " hat")),
        ("feet", (" boots", " boot", " sandals", " shoes", " slippers")),
        ("gloves", (" gloves", " gauntlets")),
        ("wrist1", (" bracers", " wristguards")),
        ("legs", (" leggings", " legguards", " pants", " trousers", " skirt", " greaves", " stockings", "breeches")),
        ("waist", (" belt", " girdle", " sash")),
        ("back", (" cloak", " cape", " mantle", " backpack", "satchel", " quiver", " backpack")),
        ("body", (" armor", " armour", " robe", " robes", " cloak", " vest", " tunic", " shirt", " suit", " mail")),
    ]
    wield_flag = 1 << 13
    if obj.obj_type in OBJ_TYPE_WEAPON_SUBTYPE:
        return "weapon", infer_weapon_subtype(obj, text, long_text)
    if obj.obj_type in {3, 4, 10, 24, 25}:
        consumable_jewelry_markers = (
            ("ring1", ("ring", "band", "nosering", "nose ring")),
            ("neck1", ("necklace", "amulet", "pendant", "medallion", "collar", "gorget")),
            ("wrist1", ("bracelet", "bracer", "wristguard", "armband")),
        )
        for slot, markers in consumable_jewelry_markers:
            if has_any_boundary_phrase(text, markers):
                return slot, "wearable"
    if obj.obj_type == 2:
        return "scroll", "usable"
    if obj.obj_type in {3, 4, 10, 24, 25}:
        return "potion", "usable"
    if obj.obj_type == 18:
        return "key", "usable"
    if obj.obj_type == 19:
        return "food", "edible"
    if obj.obj_type in {17, 23}:
        return "drink", "drinkable"
    if obj.obj_type == 13:
        if obj.wear_flags != 0:
            for bit, slot in WEAR_SLOT_MAP.items():
                if obj.wear_flags & bit and slot in {
                    "neck1",
                    "neck2",
                    "ring1",
                    "ring2",
                    "wrist1",
                    "wrist2",
                    "head",
                    "waist",
                    "back",
                    "gloves",
                    "legs",
                    "feet",
                    "body",
                }:
                    if has_any_boundary_phrase(
                        text,
                        (
                            "ring",
                            "necklace",
                            "amulet",
                            "pendant",
                            "medallion",
                            "collar",
                            "gorget",
                            "bracelet",
                            "bracer",
                            "wristguard",
                            "armband",
                        ),
                    ):
                        return slot, "wearable"
        if has_any_boundary_phrase(
            long_text,
            (
                "book",
                "paper",
                "parchment",
                "tome",
                "manuscript",
                "journal",
                "diary",
                "note",
                "letter",
            ),
        ):
            return "readable", None
        trash_jewelry_markers = (
            ("ring1", ("ring", "band")),
            ("neck1", ("necklace", "amulet", "pendant", "medallion", "collar", "gorget")),
            ("wrist1", ("bracelet", "bracer", "wristguard", "armband")),
        )
        for slot, markers in trash_jewelry_markers:
            if has_any_boundary_phrase(text, markers):
                return slot, "wearable"
        return "junk", None
    if obj.obj_type == 16:
        return "readable", None
    if obj.obj_type == 12 and has_any_boundary_phrase(
        long_text,
        (
            "book",
            "paper",
            "parchment",
            "tome",
            "manuscript",
            "journal",
            "diary",
            "necronomicon",
        ),
    ):
        return "readable", None
    if obj.obj_type == 12 and has_any_boundary_phrase(text, light_markers):
        return "light", "wearable"
    if obj.obj_type == 15:
        for bit, slot in WEAR_SLOT_MAP.items():
            if obj.wear_flags & bit and slot in {
                "head",
                "neck1",
                "neck2",
                "body",
                "waist",
                "back",
                "light",
                "gloves",
                "ring1",
                "ring2",
                "wrist1",
                "wrist2",
                "legs",
                "feet",
            }:
                return slot, "wearable"
        container_wear_markers = (
            ("head", ("helmet", "helm")),
            ("waist", ("beltpouch", "belt pouch", "waist pouch", "waist-pouch")),
            ("back", ("backpack", "rucksack", "quiver")),
            ("back", ("cloak", "satchel", "bandolier")),
            ("body", ("robe",)),
        )
        for slot, markers in container_wear_markers:
            if has_any_boundary_phrase(text, markers):
                return slot, "wearable"
        if has_any_boundary_phrase(text, container_junk_markers):
            return "junk", None
        if has_any_boundary_phrase(text, container_service_markers):
            return "service", None
        return "service", None
    if obj.obj_type == 12 and has_any_boundary_phrase(text, other_prop_markers):
        return "service", None
    if obj.obj_type == 12 and has_any_boundary_phrase(text, other_service_markers):
        return "service", None
    if obj.obj_type == 12 and has_phrase("key"):
        return "key", "usable"
    if obj.obj_type == 12 and has_any_boundary_phrase(text, other_junk_markers):
        return "junk", None
    if obj.obj_type == 12 and has_any_boundary_phrase(text, ("lockpick", "lockpicks")):
        return "lockpicks", None
    if obj.obj_type == 20:
        return "service", None
    if obj.obj_type in {21, 22}:
        return "service", None
    if obj.obj_type == 1 and has_any_boundary_phrase(text, light_markers):
        return "light", "wearable"
    if obj.obj_type == 1 and has_any_boundary_phrase(text, portal_markers):
        return "service", None
    if obj.obj_type == 1:
        accessory_slot_markers = (
            ("neck1", ("amulet", "pendant", "necklace", "medallion")),
            ("head", ("hair clasp", "clasp")),
            ("ring1", ("ring", "bracelet", "band")),
        )
        for slot, markers in accessory_slot_markers:
            if has_any_boundary_phrase(text, markers):
                return slot, "wearable"
    if obj.obj_type == 1 and has_phrase("staff"):
        return "weapon", infer_weapon_subtype(obj, text, long_text)
    if obj.obj_type == 1:
        return "service", None
    # Circle wear-flag bitmasks are not always trustworthy for a few legacy items.
    # Resolve obvious semantic categories before falling back to wear-bit equipment.
    if has_long_phrase("unfinished object"):
        return "junk", None
    if has_long_phrase("testing object") or has_long_phrase("testin"):
        return "junk", None
    if has_any_boundary_phrase(text, ("cloak-pin", "cloak pin")):
        return "neck1", "wearable"
    if has_phrase("talisman of the serpent"):
        return "neck1", "wearable"
    if obj.obj_type == 12 and has_phrase("sacred chao"):
        return "key", "usable"
    if obj.obj_type in {0, 8, 12} and has_phrase("khanda"):
        return "service", None
    if obj.obj_type in {0, 8, 12} and (has_phrase("sceptre") or has_phrase("scepter")):
        return "weapon", "bludgeoning"
    if obj.obj_type in {0, 8, 12} and (
        has_phrase("claw")
        or has_phrase("sickle-shaped claw")
        or (has_phrase("satan") and has_phrase("claw"))
    ):
        if has_phrase("sickle-shaped claw") or has_phrase("sickle shaped claw"):
            # Many legacy claw/trophy objects are equipped as armor/trophies in
            # Circle resets even when their wear bits are inconsistent; prefer a
            # wearable mapping over forcing everything into the weapon slot.
            return "body", "wearable"
        if obj.wear_flags & wield_flag or (has_phrase("satan") and has_phrase("claw")):
            return "weapon", "slashing"
    # Respect explicit wear bits for treasure/other artifacts before broad
    # service fallbacks. Many Circle treasures are wearable despite generic
    # object-type buckets.
    if obj.obj_type in {8, 12}:
        for bit, slot in WEAR_SLOT_MAP.items():
            if obj.wear_flags & bit and slot in {
                "offhand",
                "head",
                "neck1",
                "neck2",
                "body",
                "waist",
                "back",
                "light",
                "gloves",
                "ring1",
                "ring2",
                "wrist1",
                "wrist2",
                "legs",
                "feet",
            }:
                return slot, "wearable"
    if obj.obj_type in {8, 12} and has_any_boundary_phrase(text, treasure_service_markers):
        return "service", None
    if obj.obj_type in {0, 8, 11, 12} and obj.wear_flags == 0:
        for slot, markers in semantic_wear_markers:
            if any(has_phrase(marker) for marker in markers):
                return slot, "wearable"
    if obj.obj_type in {9, 11} and has_any_boundary_phrase(
        text,
        ("bracer", "bracers", "wristguard", "wristguards", "armband", "armbands"),
    ):
        return "wrist1", "wearable"
    if obj.obj_type == 11:
        return "body", "wearable"
    if obj.obj_type == 9 and obj.wear_flags == 0:
        armor_slot_markers = [
            ("ring1", (" ring", "ring of", "band ")),
            ("neck1", (" necklace", " amulet", " pendant", " medallion", " collar", " gorget")),
            ("head", (" helm", " helmet", " hood", " mask", " crown", " circlet", " tiara", " cap", " cowl")),
            ("feet", (" boots", " boot", " sandals", " shoes", " slippers")),
            ("gloves", (" gloves", " gauntlets")),
            ("wrist1", (" bracers", " wristguards")),
            ("legs", (" leggings", " legguards", " pants", " trousers", " skirt", " greaves", " stockings")),
            ("waist", (" belt", " girdle", " sash")),
            ("back", (" cloak", " cape", " mantle")),
        ]
        for slot, markers in armor_slot_markers:
            if any(has_phrase(marker) for marker in markers):
                return slot, "wearable"
    if obj.obj_type in {8, 12} and has_any_boundary_phrase(text, gem_markers):
        return "gemstone", None
    if obj.obj_type == 12 and has_any_boundary_phrase(text, reagent_junk_markers):
        return "junk", None
    if obj.obj_type == 0:
        if has_any_boundary_phrase(text, {"stool", "desk", "mirror", "egg"}):
            return "service", None
        if has_any_boundary_phrase(text, {"dead", "corpse", "bones"}):
            return "junk", None
    # If wearable bits are present, choose mapped equipment slot type.
    for bit, slot in WEAR_SLOT_MAP.items():
        if obj.wear_flags & bit:
            if slot in {
                "weapon",
                "offhand",
                "head",
                "neck1",
                "neck2",
                "body",
                "waist",
                "back",
                "light",
                "gloves",
                "ring1",
                "ring2",
                "wrist1",
                "wrist2",
                "legs",
                "feet",
            }:
                return slot, "wearable"
    if obj.obj_type == 9:
        return "body", "wearable"
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
        elif loc == 12:  # MANA
            statmods["mysticism"] = statmods.get("mysticism", 0) + mod
        elif loc == 13:  # HIT
            statmods["vitality"] = statmods.get("vitality", 0) + mod
        elif loc == 14:  # MOVE
            statmods["speed"] = statmods.get("speed", 0) + mod
        elif loc == 17:  # AC
            # Circle AC tends lower-is-better; negative apply improves armor.
            if mod < 0:
                damage_reduction += abs(mod)
        elif loc == 18:  # hitroll
            statmods["perception"] = statmods.get("perception", 0) + mod
        elif loc == 19:  # damroll
            statmods["damage"] = statmods.get("damage", 0) + mod
        elif loc in {20, 21, 22, 23, 24}:  # saving throws
            # Circle save modifiers are broad defensive stats; map conservatively
            # into mysticism/perception buckets rather than dropping them.
            # Circle saves are lower-is-better, while GoMUD statmods are
            # generally higher-is-better, so invert the sign here.
            save_bonus = -mod
            statmods["mysticism"] = statmods.get("mysticism", 0) + save_bonus
            statmods["perception"] = statmods.get("perception", 0) + save_bonus
        elif loc == 26:  # HIT_REGEN
            statmods["vitality"] = statmods.get("vitality", 0) + mod
        elif loc == 27:  # MANA_REGEN
            statmods["mysticism"] = statmods.get("mysticism", 0) + mod
        elif loc == 28:  # MOVE_REGEN
            statmods["speed"] = statmods.get("speed", 0) + mod
        elif loc == 29:  # SPELL
            # Circle spell-affect applies are not directly portable; keep some
            # of the item's magical weighting by projecting into mysticism.
            statmods["mysticism"] = statmods.get("mysticism", 0) + mod
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
    hands = 1
    # ITEM_TWO_HANDED in Circle extra flags.
    if item_type == "weapon" and (obj.extra_flags & (1 << 28)):
        hands = 2
    # GoMUD doesn't expose item weight directly in specs; use very heavy legacy
    # weapon weights as a conservative proxy for two-handed weapons.
    if item_type == "weapon" and obj.weight >= 15:
        hands = 2
    if item_type == "weapon":
        weapon_text = f"{obj.aliases} {obj.short_desc}".lower()
        weapon_extended_text = f"{obj.aliases} {obj.short_desc} {obj.long_desc} {obj.action_desc} {' '.join(obj.extra_descs)}".lower()
        def has_weapon_marker(marker: str) -> bool:
            return has_boundary_phrase(weapon_text, marker)
        def has_weapon_marker_extended(marker: str) -> bool:
            return has_boundary_phrase(weapon_extended_text, marker)
        two_handed_markers = (
            "bow",
            "crossbow",
            "longbow",
            "long bow",
            "spear",
            "pike",
            "halberd",
            "glaive",
            "polearm",
            "lance",
            "trident",
            "staff",
            "quarterstaff",
            "maul",
            "warhammer",
            "war hammer",
            "battleaxe",
            "battle axe",
            "greataxe",
            "great axe",
            "claymore",
            "greatsword",
            "zweihander",
            "huge sword",
            "massive sword",
        )
        two_handed_extended_markers = (
            "two-handed",
            "two handed",
            "huge sword",
            "massive sword",
            "great sword",
            "great axe",
            "battle axe",
            "long bow",
            "longbow",
        )
        if any(has_weapon_marker(marker) for marker in two_handed_markers):
            hands = 2
        elif any(has_weapon_marker_extended(marker) for marker in two_handed_extended_markers):
            hands = 2
    # ITEM_NODROP in Circle generally means cursed/equipped lock-in behavior.
    is_cursed = bool(obj.extra_flags & (1 << 7))
    out = [
        f"itemid: {obj.itemid}",
        f"name: {yquote(name)}",
        f"namesimple: {yquote(simple)}",
        f"description: {yquote(desc)}",
        f"type: {item_type}",
        f"value: {max(1, obj.values[0]) if obj.obj_type == 20 and obj.values else max(1, obj.cost)}",
        f"hands: {hands}",
    ]
    if subtype:
        out.append(f"subtype: {subtype}")
    if is_cursed:
        out.append("cursed: true")
    if item_type == "key":
        lock_id = key_lock_map.get(obj.itemid)
        if lock_id:
            out.append(f"keylockid: {lock_id}")
    statmods, dmg_red = map_affects(obj)
    if dmg_red > 0 and item_type in {
        "offhand",
        "head",
        "neck1",
        "neck2",
        "body",
        "waist",
        "back",
        "light",
        "gloves",
        "wrist1",
        "wrist2",
        "ring1",
        "ring2",
        "legs",
        "feet",
    }:
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
    def to_int(token: str, default: int = 0) -> int:
        try:
            return int(token)
        except (TypeError, ValueError):
            return default

    mob_loadouts: Dict[int, MobLoadout] = {}
    key_lock_map: Dict[int, str] = {}
    # First pass: static room exits can carry lock->key associations.
    for room in rooms.values():
        for direction, exit_info in room.exits.items():
            if "lock" in exit_info and "key_vnum" in exit_info:
                key_vnum = int(exit_info["key_vnum"])
                key_lock_map.setdefault(key_vnum, f"{room.roomid}-{direction}")
    for z in zones.values():
        # Approximate Circle zone lifespan with GoMUD respawn intervals.
        mob_respawn = max(1, min(60, z.lifespan_minutes // 2))
        item_respawn = max(1, min(60, z.lifespan_minutes))
        # Circle reset mode:
        # 0 = never reset, 1 = reset when empty, 2 = always reset.
        # GoMUD doesn't have direct mode equivalents, so approximate with pacing.
        if z.reset_mode == 0:
            mob_respawn = max(mob_respawn, 240)
            item_respawn = max(item_respawn, 240)
        elif z.reset_mode == 1:
            mob_respawn = max(mob_respawn, min(120, z.lifespan_minutes))
            item_respawn = max(item_respawn, min(120, z.lifespan_minutes + 15))
        last_mobid: Optional[int] = None
        # Tracks latest room container spawned by object vnum for this zone stream.
        latest_container_by_objid: Dict[int, Tuple[int, str]] = {}
        last_cmd_succeeded = True
        for cmd in z.commands:
            if not cmd:
                continue
            c = cmd[0]
            if_flag = int(cmd[1]) if len(cmd) > 1 and re.match(r"^-?\d+$", cmd[1]) else 0
            if if_flag > 0 and not last_cmd_succeeded:
                continue
            # Default to success for unsupported/no-op opcodes so they don't
            # accidentally break Circle if-flag reset chains.
            cmd_succeeded = True
            if c == "M" and len(cmd) >= 5:
                mobid = to_int(cmd[2], -1)
                max_existing = to_int(cmd[3], 1)
                roomid = to_int(cmd[4], -1)
                if mobid < 0 or roomid < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                last_mobid = mobid
                if roomid in rooms:
                    spawn_count = max(1, min(10, max_existing))
                    for _ in range(spawn_count):
                        rooms[roomid].spawninfo.append({"mobid": mobid, "respawn": mob_respawn})
                    cmd_succeeded = True
            elif c == "O" and len(cmd) >= 5:
                itemid = to_int(cmd[2], -1)
                max_existing = to_int(cmd[3], 1)
                roomid = to_int(cmd[4], -1)
                if itemid < 0 or roomid < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                if roomid in rooms:
                    spawn_count = max(1, min(10, max_existing))
                    for _ in range(spawn_count):
                        rooms[roomid].spawninfo.append({"itemid": itemid, "respawn": item_respawn})
                    obj = all_objs.get(itemid)
                    if obj and obj.obj_type == 15:
                        cbase = slugify((obj.aliases.split()[0] if obj.aliases else f"container_{itemid}"))[:28]
                        cname = f"{cbase}_{itemid}"
                        rooms[roomid].containers[cname] = {}
                        latest_container_by_objid[itemid] = (roomid, cname)
                        # Circle container values:
                        # value[0]=capacity, value[1]=flags, value[2]=key vnum.
                        # Flags commonly include: CLOSEABLE(1), PICKPROOF(2), CLOSED(4), LOCKED(8).
                        container_flags = obj.values[1] if len(obj.values) > 1 else 0
                        key_vnum = obj.values[2] if len(obj.values) > 2 else -1
                        has_lock_intent = bool(container_flags & 8) or key_vnum > 0
                        if has_lock_intent:
                            lock_difficulty = 1
                            if container_flags & 8:  # locked
                                lock_difficulty = max(lock_difficulty, 2)
                            if container_flags & 2:  # pickproof
                                lock_difficulty = max(lock_difficulty, 8)
                            if key_vnum > 0:
                                lock_difficulty = max(lock_difficulty, 2)
                            rooms[roomid].containers[cname]["lock"] = {"difficulty": lock_difficulty}
                        if key_vnum > 0:
                            key_lock_map.setdefault(int(key_vnum), f"{roomid}-{cname}")
                    cmd_succeeded = True
            elif c == "G" and len(cmd) >= 3 and last_mobid:
                itemid = to_int(cmd[2], -1)
                if itemid < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                ml = mob_loadouts.setdefault(last_mobid, MobLoadout())
                ml.items.append(itemid)
                cmd_succeeded = True
            elif c == "E" and len(cmd) >= 5 and last_mobid:
                itemid = to_int(cmd[2], -1)
                wear_pos = to_int(cmd[4], -1)
                if itemid < 0 or wear_pos < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                slot = map_circle_wear_to_slot(wear_pos, itemid, all_objs)
                if slot:
                    ml = mob_loadouts.setdefault(last_mobid, MobLoadout())
                    if slot in ml.equipment:
                        secondary_slot = {
                            "ring1": "ring2",
                            "neck1": "neck2",
                            "wrist1": "wrist2",
                        }.get(slot)
                        if secondary_slot and secondary_slot not in ml.equipment:
                            slot = secondary_slot
                    ml.equipment[slot] = itemid
                    cmd_succeeded = True
            elif c == "P" and len(cmd) >= 5:
                itemid = to_int(cmd[2], -1)
                max_existing = to_int(cmd[3], 1)
                container_objid = to_int(cmd[4], -1)
                if itemid < 0 or container_objid < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                if container_objid in latest_container_by_objid:
                    roomid, cname = latest_container_by_objid[container_objid]
                    if roomid in rooms:
                        spawn_count = max(1, min(10, max_existing))
                        for _ in range(spawn_count):
                            rooms[roomid].spawninfo.append(
                                {"itemid": itemid, "container": cname, "respawn": item_respawn}
                            )
                        cmd_succeeded = True
            elif c == "D" and len(cmd) >= 5:
                roomid = to_int(cmd[2], -1)
                dnum = to_int(cmd[3], -1)
                state = to_int(cmd[4], -1)
                if roomid < 0 or dnum < 0 or state < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                direction = DIR_MAP.get(dnum)
                room = rooms.get(roomid)
                if not room or not direction:
                    cmd_succeeded = False
                else:
                    exit_info = room.exits.get(direction)
                    if not exit_info:
                        cmd_succeeded = False
                    else:
                        # Circle reset states: 0=open, 1=closed, 2=closed+locked.
                        # GoMUD exposes lock semantics but no closed-state toggle in room YAML.
                        if state >= 2:
                            if "lock" not in exit_info:
                                exit_info["lock"] = {"difficulty": 1}
                        elif state == 0:
                            exit_info.pop("lock", None)
                        cmd_succeeded = True
            elif c == "R" and len(cmd) >= 4:
                roomid = to_int(cmd[2], -1)
                itemid = to_int(cmd[3], -1)
                if roomid < 0 or itemid < 0:
                    cmd_succeeded = False
                    last_cmd_succeeded = cmd_succeeded
                    continue
                room = rooms.get(roomid)
                if not room:
                    cmd_succeeded = False
                else:
                    room.spawninfo = [
                        s for s in room.spawninfo
                        if not ("itemid" in s and int(s["itemid"]) == itemid)
                    ]
                    cmd_succeeded = True
            last_cmd_succeeded = cmd_succeeded
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
