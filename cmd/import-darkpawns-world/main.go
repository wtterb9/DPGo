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

type zoneConfig struct {
	Name   string `yaml:"name"`
	RoomID int    `yaml:"roomid"`
}

type roomFile struct {
	RoomID      int                 `yaml:"roomid"`
	Zone        string              `yaml:"zone"`
	Title       string              `yaml:"title"`
	Description string              `yaml:"description"`
	Exits       map[string]roomExit `yaml:"exits,omitempty"`
}

type roomExit struct {
	RoomID int `yaml:"roomid"`
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

func main() {
	darkPawnsWorld := flag.String("darkpawns-world", "", "Path to DarkPawns lib/world directory")
	outputRooms := flag.String("output-rooms", "", "Path to GoMUD world/default/rooms directory")
	zonePrefix := flag.String("zone-prefix", "DarkPawns", "Prefix used for migrated zone names")
	roomIDOffset := flag.Int("room-id-offset", 2000000, "Numeric offset to apply to all imported room IDs")
	flag.Parse()

	if *darkPawnsWorld == "" || *outputRooms == "" {
		fmt.Fprintln(os.Stderr, "usage: go run ./cmd/import-darkpawns-world -darkpawns-world <path>/lib/world -output-rooms <path>/_datafiles/world/default/rooms")
		os.Exit(2)
	}

	zoneNames, err := parseZoneNames(filepath.Join(*darkPawnsWorld, "zon"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse zone names: %v\n", err)
		os.Exit(1)
	}

	rooms, err := parseRooms(filepath.Join(*darkPawnsWorld, "wld"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse world rooms: %v\n", err)
		os.Exit(1)
	}

	if err := writeRooms(*outputRooms, *zonePrefix, zoneNames, rooms, *roomIDOffset); err != nil {
		fmt.Fprintf(os.Stderr, "failed to write converted rooms: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Imported %d rooms into %s\n", len(rooms), *outputRooms)
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
		if !sc.Scan() {
			_ = f.Close()
			continue
		}
		if !sc.Scan() {
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

	sort.Slice(out, func(i, j int) bool {
		return out[i].Vnum < out[j].Vnum
	})

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

		title, nextIdx, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = nextIdx

		desc, nextIdx, err := readTildeBlock(lines, i)
		if err != nil {
			return nil, err
		}
		i = nextIdx

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
			return nil, fmt.Errorf("invalid zone vnum %q for room %d", metaFields[0], vnum)
		}

		room := parsedRoom{
			Vnum:        vnum,
			ZoneVnum:    zoneVnum,
			Title:       strings.TrimSpace(title),
			Description: strings.TrimSpace(desc),
			Exits:       map[string]int{},
		}

		for i < len(lines) {
			next := strings.TrimSpace(lines[i])
			i++

			if next == "S" {
				break
			}
			if strings.HasPrefix(next, "D") {
				dirNum, err := strconv.Atoi(strings.TrimPrefix(next, "D"))
				if err != nil {
					return nil, fmt.Errorf("invalid direction marker %q in room %d", next, vnum)
				}
				dirName, ok := directionByIndex[dirNum]
				if !ok {
					continue
				}

				_, idxAfterKw, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = idxAfterKw

				_, idxAfterDesc, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = idxAfterDesc

				if i >= len(lines) {
					return nil, fmt.Errorf("missing exit metadata in room %d", vnum)
				}
				exitFields := strings.Fields(strings.TrimSpace(lines[i]))
				i++
				if len(exitFields) < 3 {
					continue
				}

				toRoom, err := strconv.Atoi(exitFields[2])
				if err != nil || toRoom <= -1 {
					continue
				}
				room.Exits[dirName] = toRoom
				continue
			}
			if next == "E" {
				_, idxAfterKw, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = idxAfterKw
				_, idxAfterDesc, err := readTildeBlock(lines, i)
				if err != nil {
					return nil, err
				}
				i = idxAfterDesc
				continue
			}
			if strings.HasPrefix(next, "A") {
				// Circle room affect line is followed by one numeric line.
				if i < len(lines) {
					i++
				}
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

func writeRooms(outputRoot, zonePrefix string, zoneNames map[int]string, rooms []parsedRoom, roomIDOffset int) error {
	roomsByZone := map[string][]parsedRoom{}
	for _, room := range rooms {
		rawZoneName := zoneNames[room.ZoneVnum]
		if rawZoneName == "" {
			rawZoneName = fmt.Sprintf("Zone %d", room.ZoneVnum)
		}
		zoneName := fmt.Sprintf("%s %s", zonePrefix, rawZoneName)
		roomsByZone[zoneName] = append(roomsByZone[zoneName], room)
	}

	zoneNamesSorted := make([]string, 0, len(roomsByZone))
	for zoneName := range roomsByZone {
		zoneNamesSorted = append(zoneNamesSorted, zoneName)
	}
	sort.Strings(zoneNamesSorted)

	for _, zoneName := range zoneNamesSorted {
		zoneRooms := roomsByZone[zoneName]
		sort.Slice(zoneRooms, func(i, j int) bool { return zoneRooms[i].Vnum < zoneRooms[j].Vnum })

		folder := filepath.Join(outputRoot, zoneFolderName(zoneName))
		if err := os.MkdirAll(folder, 0o755); err != nil {
			return err
		}

		for _, pr := range zoneRooms {
			rf := roomFile{
				RoomID:      pr.Vnum + roomIDOffset,
				Zone:        zoneName,
				Title:       pr.Title,
				Description: pr.Description,
			}
			if len(pr.Exits) > 0 {
				rf.Exits = map[string]roomExit{}
				for dir, toRoom := range pr.Exits {
					rf.Exits[dir] = roomExit{RoomID: toRoom + roomIDOffset}
				}
			}

			data, err := yaml.Marshal(&rf)
			if err != nil {
				return err
			}
			if err := os.WriteFile(filepath.Join(folder, fmt.Sprintf("%d.yaml", pr.Vnum+roomIDOffset)), data, 0o644); err != nil {
				return err
			}
		}

		zc := zoneConfig{
			Name:   zoneName,
			RoomID: zoneRooms[0].Vnum + roomIDOffset,
		}
		data, err := yaml.Marshal(&zc)
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(folder, "zone-config.yaml"), data, 0o644); err != nil {
			return err
		}
	}

	return nil
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
