package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v2"
)

type roomSpawnEntry struct {
	MobID       int    `yaml:"mobid,omitempty"`
	ItemID      int    `yaml:"itemid,omitempty"`
	Container   string `yaml:"container,omitempty"`
	RespawnRate string `yaml:"respawnrate,omitempty"`
}

type roomContainer struct {
	Items []map[string]int `yaml:"items,omitempty"`
}

type roomData struct {
	RoomID      int                       `yaml:"roomid"`
	Zone        string                    `yaml:"zone"`
	Title       string                    `yaml:"title"`
	Description string                    `yaml:"description"`
	Biome       string                    `yaml:"biome,omitempty"`
	Exits       map[string]map[string]int `yaml:"exits,omitempty"`
	Containers  map[string]roomContainer  `yaml:"containers,omitempty"`
	Tags        []string                  `yaml:"tags,omitempty"`
	SpawnInfo   []roomSpawnEntry          `yaml:"spawninfo,omitempty"`
}

type mobData struct {
	MobID          int       `yaml:"mobid"`
	Zone           string    `yaml:"zone"`
	ItemDropChance int       `yaml:"itemdropchance"`
	Hostile        bool      `yaml:"hostile"`
	MaxWander      int       `yaml:"maxwander,omitempty"`
	ActivityLevel  int       `yaml:"activitylevel,omitempty"`
	Character      character `yaml:"character"`
}

type character struct {
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
	Level       int    `yaml:"level"`
	RaceID      int    `yaml:"raceid"`
}

type itemData struct {
	ItemID      int    `yaml:"itemid"`
	Name        string `yaml:"name"`
	NameSimple  string `yaml:"namesimple"`
	Description string `yaml:"description"`
	Type        string `yaml:"type"`
	Subtype     string `yaml:"subtype"`
	Value       int    `yaml:"value,omitempty"`
}

type parsedMob struct {
	Vnum        int
	ZoneVnum    int
	Name        string
	Description string
	Level       int
	RaceID      int
}

type parsedItem struct {
	Vnum        int
	ZoneVnum    int
	Name        string
	NameSimple  string
	Description string
	ObjType     int
	Value       int
}

type zoneSpawn struct {
	RoomVnum            int
	MobVnum             int
	ItemVnum            int
	ContainerObjectVnum int
	Command             string
}

func main() {
	darkPawnsWorld := flag.String("darkpawns-world", "", "Path to DarkPawns lib/world directory")
	outputRooms := flag.String("output-rooms", "", "Path to GoMUD world/default/rooms directory")
	outputMobs := flag.String("output-mobs", "", "Path to GoMUD world/default/mobs directory")
	outputItems := flag.String("output-items", "", "Path to GoMUD world/default/items directory")
	zonePrefix := flag.String("zone-prefix", "DarkPawns", "Prefix used for migrated zone names")
	roomIDOffset := flag.Int("room-id-offset", 2000000, "Numeric offset for room IDs")
	mobIDOffset := flag.Int("mob-id-offset", 2000000, "Numeric offset for mob IDs")
	itemIDOffset := flag.Int("item-id-offset", 3000000, "Numeric offset for item IDs")
	flag.Parse()

	if *darkPawnsWorld == "" || *outputRooms == "" || *outputMobs == "" || *outputItems == "" {
		fmt.Fprintln(os.Stderr, "usage: go run ./cmd/import-darkpawns-content -darkpawns-world <path>/lib/world -output-rooms <rooms> -output-mobs <mobs> -output-items <items>")
		os.Exit(2)
	}

	zoneNames, err := parseZoneNames(filepath.Join(*darkPawnsWorld, "zon"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse zone names: %v\n", err)
		os.Exit(1)
	}

	rooms, err := parseRooms(filepath.Join(*darkPawnsWorld, "wld"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse rooms: %v\n", err)
		os.Exit(1)
	}

	zoneByRoom := make(map[int]string, len(rooms))
	for _, room := range rooms {
		zName := zoneNames[room.ZoneVnum]
		if zName == "" {
			zName = fmt.Sprintf("Zone %d", room.ZoneVnum)
		}
		zoneByRoom[room.Vnum] = fmt.Sprintf("%s %s", *zonePrefix, zName)
	}

	mobs, err := parseMobs(filepath.Join(*darkPawnsWorld, "mob"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse mobs: %v\n", err)
		os.Exit(1)
	}

	items, err := parseItems(filepath.Join(*darkPawnsWorld, "obj"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse items: %v\n", err)
		os.Exit(1)
	}

	spawns, err := parseZoneSpawns(filepath.Join(*darkPawnsWorld, "zon"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse zone resets: %v\n", err)
		os.Exit(1)
	}

	if err := writeMobs(*outputMobs, *zonePrefix, mobs, *mobIDOffset); err != nil {
		fmt.Fprintf(os.Stderr, "failed writing mobs: %v\n", err)
		os.Exit(1)
	}
	if err := writeItems(*outputItems, items, *itemIDOffset); err != nil {
		fmt.Fprintf(os.Stderr, "failed writing items: %v\n", err)
		os.Exit(1)
	}
	if err := applySpawns(*outputRooms, zoneByRoom, spawns, *roomIDOffset, *mobIDOffset, *itemIDOffset); err != nil {
		fmt.Fprintf(os.Stderr, "failed applying spawns: %v\n", err)
		os.Exit(1)
	}
	if err := tagRemortRooms(*outputRooms, zoneByRoom, spawns, *roomIDOffset); err != nil {
		fmt.Fprintf(os.Stderr, "failed tagging remort rooms: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Imported %d mobs, %d items, %d zone spawns\n", len(mobs), len(items), len(spawns))
}

func writeMobs(outputRoot string, zonePrefix string, mobs []parsedMob, mobIDOffset int) error {
	zoneName := fmt.Sprintf("%s Mob Templates", zonePrefix)
	folder := filepath.Join(outputRoot, zoneFolderName(zoneName))
	if err := os.MkdirAll(folder, 0o755); err != nil {
		return err
	}

	for _, m := range mobs {
		md := mobData{
			MobID:          m.Vnum + mobIDOffset,
			Zone:           zoneName,
			ItemDropChance: 0,
			Hostile:        false,
			MaxWander:      4,
			ActivityLevel:  10,
			Character: character{
				Name:        m.Name,
				Description: m.Description,
				Level:       clamp(m.Level, 1, 100),
				RaceID:      clamp(m.RaceID, 1, 9999),
			},
		}

		data, err := yaml.Marshal(&md)
		if err != nil {
			return err
		}
		filename := fmt.Sprintf("%d-%s.yaml", md.MobID, safeName(m.Name))
		if err := os.WriteFile(filepath.Join(folder, filename), data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func tagRemortRooms(outputRooms string, zoneByRoom map[int]string, spawns []zoneSpawn, roomIDOffset int) error {
	remortRooms := map[int]struct{}{}
	for _, s := range spawns {
		// DarkPawns canonical remorter mob vnum is 4.
		if s.MobVnum == 4 && s.RoomVnum > -1 {
			remortRooms[s.RoomVnum+roomIDOffset] = struct{}{}
		}
	}
	for roomID := range remortRooms {
		zoneName := zoneByRoom[roomID-roomIDOffset]
		if zoneName == "" {
			continue
		}
		roomPath := filepath.Join(outputRooms, zoneFolderName(zoneName), fmt.Sprintf("%d.yaml", roomID))
		raw, err := os.ReadFile(roomPath)
		if err != nil {
			continue
		}
		var rd roomData
		if err := yaml.Unmarshal(raw, &rd); err != nil {
			return err
		}
		hasRemortTag := false
		for _, tag := range rd.Tags {
			if strings.EqualFold(strings.TrimSpace(tag), `remort`) {
				hasRemortTag = true
				break
			}
		}
		if !hasRemortTag {
			rd.Tags = append(rd.Tags, `remort`)
		}
		data, err := yaml.Marshal(&rd)
		if err != nil {
			return err
		}
		if err := os.WriteFile(roomPath, data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func writeItems(outputRoot string, items []parsedItem, itemIDOffset int) error {
	folder := filepath.Join(outputRoot, "other-0")
	if err := os.MkdirAll(folder, 0o755); err != nil {
		return err
	}
	for _, it := range items {
		t, st := mapItemType(it.ObjType)
		id := it.Vnum + itemIDOffset
		idata := itemData{
			ItemID:      id,
			Name:        it.Name,
			NameSimple:  it.NameSimple,
			Description: it.Description,
			Type:        t,
			Subtype:     st,
			Value:       max(0, it.Value),
		}
		data, err := yaml.Marshal(&idata)
		if err != nil {
			return err
		}
		filename := fmt.Sprintf("%d-%s.yaml", id, safeName(it.Name))
		if err := os.WriteFile(filepath.Join(folder, filename), data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func applySpawns(outputRooms string, zoneByRoom map[int]string, spawns []zoneSpawn, roomIDOffset, mobIDOffset, itemIDOffset int) error {
	byRoom := map[int][]roomSpawnEntry{}
	byRoomContainers := map[int]map[string]roomContainer{}
	for _, s := range spawns {
		entry := roomSpawnEntry{RespawnRate: "15 real minutes"}
		if s.MobVnum > 0 {
			entry.MobID = s.MobVnum + mobIDOffset
		}
		if s.ItemVnum > 0 {
			entry.ItemID = s.ItemVnum + itemIDOffset
		}
		if s.Command == "P" && s.ContainerObjectVnum > 0 {
			entry.Container = fmt.Sprintf("container_%d", s.ContainerObjectVnum+itemIDOffset)
			roomID := s.RoomVnum + roomIDOffset
			if _, ok := byRoomContainers[roomID]; !ok {
				byRoomContainers[roomID] = map[string]roomContainer{}
			}
			if _, ok := byRoomContainers[roomID][entry.Container]; !ok {
				byRoomContainers[roomID][entry.Container] = roomContainer{}
			}
		}
		if entry.MobID == 0 && entry.ItemID == 0 {
			continue
		}
		byRoom[s.RoomVnum+roomIDOffset] = append(byRoom[s.RoomVnum+roomIDOffset], entry)
	}

	for roomID, entries := range byRoom {
		zoneName := zoneByRoom[roomID-roomIDOffset]
		if zoneName == "" {
			continue
		}
		roomPath := filepath.Join(outputRooms, zoneFolderName(zoneName), fmt.Sprintf("%d.yaml", roomID))
		raw, err := os.ReadFile(roomPath)
		if err != nil {
			continue
		}
		var rd roomData
		if err := yaml.Unmarshal(raw, &rd); err != nil {
			return err
		}
		// Overwrite generated spawn info to keep imports idempotent.
		rd.SpawnInfo = entries
		if cMap, ok := byRoomContainers[roomID]; ok && len(cMap) > 0 {
			rd.Containers = cMap
		}
		data, err := yaml.Marshal(&rd)
		if err != nil {
			return err
		}
		if err := os.WriteFile(roomPath, data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func parseMobs(mobDir string) ([]parsedMob, error) {
	files, err := listIndexFiles(filepath.Join(mobDir, "index"))
	if err != nil {
		return nil, err
	}
	out := []parsedMob{}
	for _, f := range files {
		ms, err := parseMobFile(filepath.Join(mobDir, f))
		if err != nil {
			return nil, err
		}
		out = append(out, ms...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Vnum < out[j].Vnum })
	return out, nil
}

func parseItems(objDir string) ([]parsedItem, error) {
	files, err := listIndexFiles(filepath.Join(objDir, "index"))
	if err != nil {
		return nil, err
	}
	out := []parsedItem{}
	for _, f := range files {
		is, err := parseObjFile(filepath.Join(objDir, f))
		if err != nil {
			return nil, err
		}
		out = append(out, is...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Vnum < out[j].Vnum })
	return out, nil
}

func parseZoneSpawns(zonDir string) ([]zoneSpawn, error) {
	files, err := listIndexFiles(filepath.Join(zonDir, "index"))
	if err != nil {
		return nil, err
	}
	out := []zoneSpawn{}
	for _, f := range files {
		zs, err := parseZoneSpawnFile(filepath.Join(zonDir, f))
		if err != nil {
			return nil, err
		}
		out = append(out, zs...)
	}
	return out, nil
}

func parseMobFile(path string) ([]parsedMob, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.ReplaceAll(string(raw), "\r\n", "\n"), "\n")
	out := []parsedMob{}
	for i := 0; i < len(lines); {
		line := strings.TrimSpace(lines[i])
		if line == "" {
			i++
			continue
		}
		if line == "$" {
			break
		}
		if !strings.HasPrefix(line, "#") {
			i++
			continue
		}
		vnum, _ := strconv.Atoi(strings.TrimPrefix(line, "#"))
		i++
		keywords, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		shortName, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		_, ni, err = readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		desc, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		if i >= len(lines) {
			break
		}
		metaFields := strings.Fields(strings.TrimSpace(lines[i]))
		i++
		zoneVnum := 0
		if len(metaFields) > 0 {
			zoneVnum, _ = strconv.Atoi(metaFields[0])
		}
		level := 1
		if i < len(lines) {
			combatFields := strings.Fields(strings.TrimSpace(lines[i]))
			if len(combatFields) > 0 {
				if l, err := strconv.Atoi(combatFields[0]); err == nil && l > 0 {
					level = l
				}
			}
			i++
		}

		raceID := 1
		for i < len(lines) {
			next := strings.TrimSpace(lines[i])
			i++
			if next == "E" {
				break
			}
			if strings.HasPrefix(next, "Race:") {
				r := strings.TrimSpace(strings.TrimPrefix(next, "Race:"))
				if val, err := strconv.Atoi(r); err == nil {
					raceID = val
				}
			}
		}

		name := sanitizeMobName(shortName, keywords)
		out = append(out, parsedMob{
			Vnum:        vnum,
			ZoneVnum:    zoneVnum,
			Name:        name,
			Description: strings.TrimSpace(desc),
			Level:       level,
			RaceID:      raceID,
		})
	}
	return out, nil
}

func parseObjFile(path string) ([]parsedItem, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.ReplaceAll(string(raw), "\r\n", "\n"), "\n")
	out := []parsedItem{}
	for i := 0; i < len(lines); {
		line := strings.TrimSpace(lines[i])
		if line == "" {
			i++
			continue
		}
		if line == "$" {
			break
		}
		if !strings.HasPrefix(line, "#") {
			i++
			continue
		}
		vnum, _ := strconv.Atoi(strings.TrimPrefix(line, "#"))
		i++
		keywords, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		shortName, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		longName, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		_, ni, err = readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		if i >= len(lines) {
			break
		}
		objType := 0
		typeFields := strings.Fields(strings.TrimSpace(lines[i]))
		if len(typeFields) > 0 {
			objType, _ = strconv.Atoi(typeFields[0])
		}
		i++
		if i >= len(lines) {
			break
		}
		i++ // skip values line
		value := 0
		if i < len(lines) {
			wcr := strings.Fields(strings.TrimSpace(lines[i]))
			if len(wcr) > 1 {
				value, _ = strconv.Atoi(wcr[1])
			}
			i++
		}

		for i < len(lines) {
			next := strings.TrimSpace(lines[i])
			if next == "" {
				i++
				continue
			}
			if next == "$" || strings.HasPrefix(next, "#") {
				break
			}
			if next == "E" {
				i++
				_, ni, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				_, ni, err = readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				continue
			}
			i++
		}

		out = append(out, parsedItem{
			Vnum:        vnum,
			Name:        sanitizeItemName(shortName, keywords),
			NameSimple:  firstKeyword(keywords),
			Description: strings.TrimSpace(longName),
			ObjType:     objType,
			Value:       value,
		})
	}
	return out, nil
}

func parseZoneSpawnFile(path string) ([]zoneSpawn, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	out := []zoneSpawn{}
	lastMobRoom := -1
	// Track known room location for object vnums to help resolve P (put object into object) commands.
	objectRoom := map[int]int{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || line == "$" || strings.HasPrefix(line, "#") {
			continue
		}
		if line == "S" {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 5 {
			continue
		}
		switch parts[0] {
		case "M":
			mobVnum, _ := strconv.Atoi(parts[2])
			roomVnum, _ := strconv.Atoi(parts[4])
			if roomVnum > -1 && mobVnum > 0 {
				lastMobRoom = roomVnum
				out = append(out, zoneSpawn{RoomVnum: roomVnum, MobVnum: mobVnum, Command: "M"})
			}
		case "O":
			itemVnum, _ := strconv.Atoi(parts[2])
			roomVnum, _ := strconv.Atoi(parts[4])
			if roomVnum > -1 && itemVnum > 0 {
				objectRoom[itemVnum] = roomVnum
				out = append(out, zoneSpawn{RoomVnum: roomVnum, ItemVnum: itemVnum, Command: "O"})
			}
		case "G", "E":
			// Give/equip object to most recently loaded mob.
			itemVnum, _ := strconv.Atoi(parts[2])
			if itemVnum > 0 && lastMobRoom > -1 {
				objectRoom[itemVnum] = lastMobRoom
				out = append(out, zoneSpawn{RoomVnum: lastMobRoom, ItemVnum: itemVnum, Command: parts[0]})
			}
		case "P":
			// Put object into another object/container.
			// Format: P <ifflag> <obj-vnum> <max-existing> <container-obj-vnum>
			itemVnum, _ := strconv.Atoi(parts[2])
			containerVnum, _ := strconv.Atoi(parts[4])
			if itemVnum > 0 {
				if roomVnum, ok := objectRoom[containerVnum]; ok && roomVnum > -1 {
					objectRoom[itemVnum] = roomVnum
					out = append(out, zoneSpawn{RoomVnum: roomVnum, ItemVnum: itemVnum, ContainerObjectVnum: containerVnum, Command: "P"})
				} else if lastMobRoom > -1 {
					// Fallback if container room could not be resolved.
					objectRoom[itemVnum] = lastMobRoom
					out = append(out, zoneSpawn{RoomVnum: lastMobRoom, ItemVnum: itemVnum, ContainerObjectVnum: containerVnum, Command: "P"})
				}
			}
		}
	}
	return out, sc.Err()
}

func mapItemType(objType int) (string, string) {
	switch objType {
	case 19:
		return "food", "edible"
	case 23:
		return "drink", "drinkable"
	case 2:
		return "scroll", "usable"
	case 5, 6, 7:
		return "weapon", "generic"
	default:
		return "object", "mundane"
	}
}

func sanitizeMobName(shortName, keywords string) string {
	s := strings.TrimSpace(strings.TrimSuffix(shortName, "~"))
	s = strings.TrimPrefix(s, "a ")
	s = strings.TrimPrefix(s, "an ")
	s = strings.TrimPrefix(s, "the ")
	if s == "" {
		s = firstKeyword(keywords)
	}
	if s == "" {
		s = "unknown_mob"
	}
	return s
}

func sanitizeItemName(shortName, keywords string) string {
	s := strings.TrimSpace(strings.TrimSuffix(shortName, "~"))
	s = strings.TrimPrefix(s, "a ")
	s = strings.TrimPrefix(s, "an ")
	s = strings.TrimPrefix(s, "the ")
	if s == "" {
		s = firstKeyword(keywords)
	}
	if s == "" {
		s = "unknown_item"
	}
	return s
}

func firstKeyword(keywords string) string {
	parts := strings.Fields(strings.TrimSpace(strings.TrimSuffix(keywords, "~")))
	if len(parts) < 1 {
		return ""
	}
	return parts[0]
}

func safeName(s string) string {
	return zoneFolderName(strings.ToLower(s))
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func parseZoneNames(zonDir string) (map[int]string, error) {
	indexFiles, err := listIndexFiles(filepath.Join(zonDir, "index"))
	if err != nil {
		return nil, err
	}
	out := map[int]string{}
	for _, fileName := range indexFiles {
		zoneID, err := strconv.Atoi(strings.TrimSuffix(fileName, ".zon"))
		if err != nil {
			continue
		}
		f, err := os.Open(filepath.Join(zonDir, fileName))
		if err != nil {
			return nil, err
		}
		sc := bufio.NewScanner(f)
		if !sc.Scan() || !sc.Scan() {
			_ = f.Close()
			continue
		}
		zoneName := strings.TrimSuffix(strings.TrimSpace(sc.Text()), "~")
		if zoneName != "" {
			out[zoneID] = zoneName
		}
		_ = f.Close()
	}
	return out, nil
}

type parsedRoom struct {
	Vnum        int
	ZoneVnum    int
	Title       string
	Description string
	Exits       map[string]int
}

var directionByIndex = map[int]string{
	0: "north",
	1: "east",
	2: "south",
	3: "west",
	4: "up",
	5: "down",
}

func parseRooms(wldDir string) ([]parsedRoom, error) {
	indexFiles, err := listIndexFiles(filepath.Join(wldDir, "index"))
	if err != nil {
		return nil, err
	}
	out := make([]parsedRoom, 0, 4096)
	for _, fileName := range indexFiles {
		fileRooms, err := parseWldFile(filepath.Join(wldDir, fileName))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", fileName, err)
		}
		out = append(out, fileRooms...)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Vnum < out[j].Vnum })
	return out, nil
}

func parseWldFile(path string) ([]parsedRoom, error) {
	rawBytes, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.ReplaceAll(string(rawBytes), "\r\n", "\n"), "\n")
	rooms := []parsedRoom{}
	for i := 0; i < len(lines); {
		line := strings.TrimSpace(lines[i])
		if line == "" {
			i++
			continue
		}
		if line == "$" {
			break
		}
		if !strings.HasPrefix(line, "#") {
			i++
			continue
		}
		vnum, err := strconv.Atoi(strings.TrimPrefix(line, "#"))
		if err != nil {
			return nil, fmt.Errorf("invalid room vnum %q", line)
		}
		i++
		title, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		desc, ni, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = ni
		if i >= len(lines) {
			return nil, fmt.Errorf("missing room metadata for room %d", vnum)
		}
		metaFields := strings.Fields(strings.TrimSpace(lines[i]))
		i++
		if len(metaFields) < 1 {
			return nil, fmt.Errorf("invalid room metadata for room %d", vnum)
		}
		zoneVnum, err := strconv.Atoi(metaFields[0])
		if err != nil {
			return nil, fmt.Errorf("invalid zone vnum for room %d", vnum)
		}
		room := parsedRoom{Vnum: vnum, ZoneVnum: zoneVnum, Title: strings.TrimSpace(title), Description: strings.TrimSpace(desc), Exits: map[string]int{}}
		for i < len(lines) {
			next := strings.TrimSpace(lines[i])
			i++
			if next == "S" {
				break
			}
			if strings.HasPrefix(next, "D") {
				dirNum, err := strconv.Atoi(strings.TrimPrefix(next, "D"))
				if err != nil {
					continue
				}
				dirName, ok := directionByIndex[dirNum]
				if !ok {
					continue
				}
				_, ni, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				_, ni, err = readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				if i >= len(lines) {
					break
				}
				exitFields := strings.Fields(strings.TrimSpace(lines[i]))
				i++
				if len(exitFields) < 3 {
					continue
				}
				toRoom, err := strconv.Atoi(exitFields[2])
				if err == nil && toRoom > -1 {
					room.Exits[dirName] = toRoom
				}
				continue
			}
			if next == "E" {
				_, ni, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				_, ni, err = readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = ni
				continue
			}
			if strings.HasPrefix(next, "A") && i < len(lines) {
				i++
			}
		}
		rooms = append(rooms, room)
	}
	return rooms, nil
}

func readTildeBlock(lines []string, start int) (string, int, error) {
	if start >= len(lines) {
		return "", start, fmt.Errorf("unexpected eof while reading tilde block")
	}
	var b strings.Builder
	for i := start; i < len(lines); i++ {
		line := lines[i]
		if strings.HasSuffix(line, "~") {
			b.WriteString(strings.TrimSuffix(line, "~"))
			return b.String(), i + 1, nil
		}
		if b.Len() > 0 {
			b.WriteString("\n")
		}
		b.WriteString(line)
	}
	return "", len(lines), fmt.Errorf("unterminated tilde block")
}

func listIndexFiles(indexPath string) ([]string, error) {
	rawBytes, err := os.ReadFile(indexPath)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.ReplaceAll(string(rawBytes), "\r\n", "\n"), "\n")
	out := []string{}
	for _, line := range lines {
		s := strings.TrimSpace(line)
		if s == "" || s == "$" {
			continue
		}
		out = append(out, s)
	}
	return out, nil
}

func zoneFolderName(zone string) string {
	normalized := strings.ToLower(strings.TrimSpace(zone))
	normalized = strings.ReplaceAll(normalized, "-", " ")
	var out strings.Builder
	lastUnderscore := false
	for _, r := range normalized {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			out.WriteRune(r)
			lastUnderscore = false
			continue
		}
		if !lastUnderscore {
			out.WriteRune('_')
			lastUnderscore = true
		}
	}
	return strings.Trim(out.String(), "_")
}
