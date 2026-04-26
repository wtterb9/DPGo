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

OBJ_TYPE_MAP = {
    5: ("weapon", "slashing"),
    6: ("armor", "body"),
    7: ("weapon", "piercing"),
    8: ("weapon", "bludgeoning"),
    9: ("armor", "body"),
    10: ("other", ""),
    11: ("other", ""),
    12: ("other", ""),
    13: ("other", ""),
    14: ("other", ""),
    15: ("container", ""),
    17: ("other", ""),
    19: ("food", ""),
    20: ("other", ""),
    21: ("other", ""),
    22: ("other", ""),
    23: ("drink", ""),
    24: ("other", ""),
    25: ("other", ""),
}


@dataclass
class Room:
    roomid: int
    zone_num: int
    title: str
    description: str
    exits: Dict[str, int] = field(default_factory=dict)
    spawninfo: List[dict] = field(default_factory=list)


@dataclass
class Mob:
    mobid: int
    zone_num: int
    aliases: str
    short_desc: str
    long_desc: str
    detailed_desc: str
    level: int
    alignment: int
    gold: int


@dataclass
class Obj:
    itemid: int
    zone_num: int
    aliases: str
    short_desc: str
    long_desc: str
    obj_type: int
    values: List[int]
    weight: int
    cost: int


@dataclass
class Zone:
    number: int
    name: str
    top: int
    commands: List[List[str]] = field(default_factory=list)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "zone"


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
        i += 1  # skip flags/sector line
        room = Room(roomid=roomid, zone_num=zone_num, title=title or f"Room {roomid}", description=desc or "An unremarkable place.")
        while i < len(lines):
            cmd = lines[i].strip()
            if cmd == "S":
                i += 1
                break
            if cmd.startswith("D"):
                dnum = int(cmd[1:])
                i += 1
                _, i = read_tilde_text(lines, i)  # door desc
                _, i = read_tilde_text(lines, i)  # keywords
                if i < len(lines):
                    vals = lines[i].strip().split()
                    i += 1
                    if len(vals) >= 3:
                        to_room = int(vals[2])
                        if to_room >= 0 and dnum in DIR_MAP:
                            room.exits[DIR_MAP[dnum]] = to_room
            elif cmd == "E":
                i += 1
                _, i = read_tilde_text(lines, i)  # keyword
                _, i = read_tilde_text(lines, i)  # extra desc
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
        _, i = read_tilde_text(lines, i)  # action desc
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
        obj = Obj(
            itemid=itemid,
            zone_num=zone_num,
            aliases=aliases,
            short_desc=short_desc,
            long_desc=long_desc,
            obj_type=obj_type,
            values=values[:4] + [0] * (4 - len(values[:4])),
            weight=max(1, weight),
            cost=max(0, cost),
        )
        while i < len(lines):
            cmd = lines[i].strip()
            if cmd.startswith("#") or cmd == "$":
                break
            if cmd in {"E", "A"}:
                i += 1
                _, i = read_tilde_text(lines, i)
                if cmd == "E":
                    _, i = read_tilde_text(lines, i)
                else:
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
        while i < len(lines):
            extra = lines[i].strip()
            i += 1
            if extra == "E":
                break
        level = int(combat[0]) if combat and re.match(r"^-?\d+$", combat[0]) else 1
        alignment = int(stats[8]) if len(stats) > 8 and re.match(r"^-?\d+$", stats[8]) else 0
        gold = int(cash[0]) if cash and re.match(r"^-?\d+$", cash[0]) else 0
        mobs[mobid] = Mob(
            mobid=mobid,
            zone_num=zone_num,
            aliases=aliases,
            short_desc=short_desc,
            long_desc=long_desc,
            detailed_desc=detailed_desc,
            level=max(1, level),
            alignment=alignment,
            gold=max(0, gold),
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


def yquote(text: str) -> str:
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_zone_config(path: Path, zone_name: str, entry_room: int) -> None:
    path.write_text(
        "\n".join(
            [
                f"name: {zone_name}",
                f"roomid: {entry_room}",
                "autoscale:",
                "  minimum: 1",
                "  maximum: 50",
                "defaultbiome: city",
                "",
            ]
        )
    )


def write_room(path: Path, room: Room, zone_name: str) -> None:
    out: List[str] = [
        f"roomid: {room.roomid}",
        f"zone: {zone_name}",
        f"title: {yquote(room.title)}",
        "description: |-",
    ]
    for dl in (room.description or "An empty room.").splitlines():
        out.append(f"  {dl}")
    out.extend(["mapsymbol: .", "biome: city"])
    if room.exits:
        out.append("exits:")
        for d, rid in room.exits.items():
            out.extend([f"  {d}:", f"    roomid: {rid}"])
    else:
        out.append("exits: {}")
    if room.spawninfo:
        out.append("spawninfo:")
        for s in room.spawninfo:
            if "mobid" in s:
                out.extend([f"- mobid: {s['mobid']}", f"  respawnrate: {s['respawn']} real minutes"])
            elif "itemid" in s:
                out.extend([f"- itemid: {s['itemid']}", f"  respawnrate: {s['respawn']} real minutes"])
    out.append("")
    path.write_text("\n".join(out))


def write_mob(path: Path, mob: Mob, zone_name: str) -> None:
    name = mob.short_desc.strip() or f"mob {mob.mobid}"
    desc = (mob.detailed_desc or mob.long_desc or "A creature lurks here.").strip()
    out = [
        f"mobid: {mob.mobid}",
        f"zone: {zone_name}",
        "itemdropchance: 1",
        "hostile: false",
        "activitylevel: 20",
        "character:",
        f"  name: {yquote(name)}",
        f"  description: {yquote(desc)}",
        "  raceid: 1",
        f"  level: {mob.level}",
        f"  alignment: {mob.alignment}",
        f"  gold: {mob.gold}",
        "",
    ]
    path.write_text("\n".join(out))


def write_item(path: Path, obj: Obj) -> None:
    aliases = obj.aliases.split()
    name = obj.short_desc.strip() or f"item {obj.itemid}"
    simple = aliases[0] if aliases else f"item{obj.itemid}"
    desc = obj.long_desc.strip() or "An item lies here."
    item_type, subtype = OBJ_TYPE_MAP.get(obj.obj_type, ("other", ""))
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
    if item_type == "weapon":
        dice_sides = max(2, obj.values[2] if obj.values[2] > 0 else 4)
        dice_num = max(1, obj.values[1] if obj.values[1] > 0 else 1)
        out.extend(
            [
                "damage:",
                f"  diceroll: {dice_num}d{dice_sides}",
            ]
        )
    elif item_type == "food":
        out.append(f"uses: {max(1, obj.values[0] if obj.values else 1)}")
    else:
        out.append("uses: 0")
    out.append("")
    path.write_text("\n".join(out))


def apply_zone_resets(zones: Dict[int, Zone], rooms: Dict[int, Room]) -> None:
    for z in zones.values():
        for cmd in z.commands:
            if not cmd:
                continue
            c = cmd[0]
            if c == "M" and len(cmd) >= 5:
                mobid = int(cmd[2])
                roomid = int(cmd[4])
                if roomid in rooms:
                    rooms[roomid].spawninfo.append({"mobid": mobid, "respawn": 5})
            elif c == "O" and len(cmd) >= 5:
                itemid = int(cmd[2])
                roomid = int(cmd[4])
                if roomid in rooms:
                    rooms[roomid].spawninfo.append({"itemid": itemid, "respawn": 10})


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

    apply_zone_resets(zones, all_rooms)

    zone_folder_map: Dict[int, str] = {}
    for znum, z in sorted(zones.items()):
        folder = f"darkpawns_{znum}_{slugify(z.name)[:40]}"
        zone_folder_map[znum] = folder
        zdir = out_rooms / folder
        zdir.mkdir(parents=True, exist_ok=True)
        room_candidates = [r.roomid for r in all_rooms.values() if r.zone_num == znum]
        entry_room = min(room_candidates) if room_candidates else max(1, z.top)
        write_zone_config(zdir / "zone-config.yaml", z.name, entry_room)

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
        write_mob(mdir / f"{mobid}-{mob_name}.yaml", mob, zones.get(mob.zone_num, Zone(mob.zone_num, f"Zone {mob.zone_num}", 0)).name)

    item_folder = out_items / "darkpawns-0"
    item_folder.mkdir(parents=True, exist_ok=True)
    for itemid, obj in sorted(all_objs.items()):
        item_name = slugify(obj.short_desc or f"item_{itemid}")[:48]
        write_item(item_folder / f"{itemid}-{item_name}.yaml", obj)

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

    print(f"Imported {len(zones)} zones, {len(all_rooms)} rooms, {len(all_mobs)} mobs, {len(all_objs)} objects.")


if __name__ == "__main__":
    main()
