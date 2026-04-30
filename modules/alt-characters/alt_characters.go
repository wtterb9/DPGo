package altcharacters

import (
	"embed"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"

	"github.com/GoMudEngine/GoMud/internal/characters"
	"github.com/GoMudEngine/GoMud/internal/configs"
	"github.com/GoMudEngine/GoMud/internal/events"
	"github.com/GoMudEngine/GoMud/internal/items"
	"github.com/GoMudEngine/GoMud/internal/mudlog"
	"github.com/GoMudEngine/GoMud/internal/plugins"
	"github.com/GoMudEngine/GoMud/internal/races"
	"github.com/GoMudEngine/GoMud/internal/rooms"
	"github.com/GoMudEngine/GoMud/internal/skills"
	"github.com/GoMudEngine/GoMud/internal/templates"
	"github.com/GoMudEngine/GoMud/internal/term"
	"github.com/GoMudEngine/GoMud/internal/usercommands"
	"github.com/GoMudEngine/GoMud/internal/users"
	"github.com/GoMudEngine/GoMud/internal/util"
	"gopkg.in/yaml.v2"

	mobs "github.com/GoMudEngine/GoMud/internal/mobs"
)

var (
	//go:embed files/*
	files embed.FS
)

const (
	characterTag = "character"
)

func init() {
	m := &AltCharactersModule{
		plug: plugins.New(`alt-characters`, `1.0`),
	}

	if err := m.plug.AttachFileSystem(files); err != nil {
		panic(err)
	}

	m.plug.Web.AdminPage("Config", "alt-characters-config", "html/admin/alt-characters-config.html", true, "Modules", "Alt Characters", nil)
	m.plug.AddUserCommand(`character`, m.characterCommand, true, false)

	m.plug.ReserveTags(characterTag)

	rooms.OnRoomLook.Register(m.onRoomLook)

	// Export functions so core packages can call alt-character functionality
	// via usercommands.GetExportedFunction / users.GetExportedFunction.

	// LoadAlts: used by leaderboards and other modules.
	m.plug.ExportFunction(`LoadAlts`, func(userId int) []characters.Character {
		return loadAlts(userId)
	})

	// MaxAltCharacters: read the module config value.
	m.plug.ExportFunction(`MaxAltCharacters`, func() int {
		return maxAltCharacters(m)
	})

	// GetAltNames: returns the alt character names for a userId.
	// Consumed by internal/usercommands/start.go via usercommands.GetExportedFunction.
	m.plug.ExportFunction(`GetAltNames`, func(userId int) []string {
		var names []string
		for _, c := range loadAlts(userId) {
			names = append(names, c.Name)
		}
		return names
	})

	// SwapToAlt: performs the alt-character swap on behalf of users.UserRecord.
	// Consumed by internal/users/userrecord.go via users.GetExportedFunction.
	m.plug.ExportFunction(`SwapToAlt`, func(u *users.UserRecord, targetAltName string) bool {
		return swapToAlt(u, targetAltName)
	})

	// AltNameSearch: searches a user's alts for a character name match.
	// Consumed by internal/users/users.go via users.GetExportedFunction.
	m.plug.ExportFunction(`AltNameSearch`, func(userId int, username, nameToFind string) (int, string) {
		for _, char := range loadAlts(userId) {
			if strings.EqualFold(char.Name, nameToFind) {
				return userId, username
			}
		}
		return 0, ``
	})
}

type AltCharactersModule struct {
	plug *plugins.Plugin
}

// maxAltCharacters reads MaxAltCharacters from the module config.
func maxAltCharacters(m *AltCharactersModule) int {
	v := m.plug.Config.Get(`MaxAltCharacters`)
	if v == nil {
		return 0
	}
	switch val := v.(type) {
	case int:
		return val
	case float64:
		return int(val)
	}
	return 0
}

// ---------------------------------------------------------------------------
// Alt file I/O (module-internal)
// ---------------------------------------------------------------------------

func altsFilePath(userId int) string {
	return util.FilePath(string(configs.GetFilePathsConfig().DataFiles), `/users/`, strconv.Itoa(userId)+`.alts.yaml`)
}

func altsExists(userId int) bool {
	_, err := os.Stat(altsFilePath(userId))
	return !os.IsNotExist(err)
}

func loadAlts(userId int) []characters.Character {
	if !altsExists(userId) {
		return nil
	}

	data, err := os.ReadFile(altsFilePath(userId))
	if err != nil {
		mudlog.Error("loadAlts", "error", err.Error())
		return nil
	}

	var alts []characters.Character
	if err := yaml.Unmarshal(data, &alts); err != nil {
		mudlog.Error("loadAlts", "error", err.Error())
	}
	return alts
}

func saveAlts(userId int, alts []characters.Character) bool {

	fileWritten := false
	tmpSaved := false
	tmpCopied := false
	completed := false

	defer func() {
		mudlog.Info("saveAlts()", "userId", strconv.Itoa(userId), "wrote-file", fileWritten, "tmp-file", tmpSaved, "tmp-copied", tmpCopied, "completed", completed)
	}()

	data, err := yaml.Marshal(&alts)
	if err != nil {
		mudlog.Error("saveAlts", "error", err.Error())
		return false
	}

	carefulSave := configs.GetFilePathsConfig().CarefulSaveFiles
	path := altsFilePath(userId)
	saveFilePath := path
	if carefulSave {
		saveFilePath += `.new`
	}

	if err := os.WriteFile(saveFilePath, data, 0777); err != nil {
		mudlog.Error("saveAlts", "error", err.Error())
		return false
	}
	fileWritten = true
	if carefulSave {
		tmpSaved = true
	}

	if carefulSave {
		if err := os.Rename(saveFilePath, path); err != nil {
			mudlog.Error("saveAlts", "error", err.Error())
			return false
		}
		tmpCopied = true
	}

	completed = true
	return true
}

// ---------------------------------------------------------------------------
// SwapToAlt – moved here from users.UserRecord
// ---------------------------------------------------------------------------

func swapToAlt(u *users.UserRecord, targetAltName string) bool {

	altNames := []string{}
	nameToAlt := map[string]characters.Character{}

	for _, char := range loadAlts(u.UserId) {
		altNames = append(altNames, char.Name)
		nameToAlt[char.Name] = char
	}

	match, closeMatch := util.FindMatchIn(targetAltName, altNames...)
	if match == `` {
		match = closeMatch
	}
	if match == `` {
		return false
	}

	selectedChar, ok := nameToAlt[match]
	if !ok {
		return false
	}

	retiredCharName := u.Character.Name

	newAlts := []characters.Character{}
	for _, altChar := range nameToAlt {
		if altChar.Name != selectedChar.Name {
			newAlts = append(newAlts, altChar)
		}
	}

	newAlts = append(newAlts, *u.Character)
	saveAlts(u.UserId, newAlts)

	selectedChar.Validate()
	selectedChar.SetUserId(u.UserId)
	u.Character = &selectedChar

	users.SaveUser(*u)

	events.AddToQueue(events.CharacterChanged{
		UserId:            u.UserId,
		LastCharacterName: retiredCharName,
		CharacterName:     u.Character.Name,
	})

	return true
}

// ---------------------------------------------------------------------------
// Room look hook
// ---------------------------------------------------------------------------

func (m *AltCharactersModule) onRoomLook(d rooms.RoomTemplateDetails) rooms.RoomTemplateDetails {
	for _, t := range d.Tags {
		if strings.EqualFold(t, characterTag) {
			d.RoomAlerts = append(d.RoomAlerts,
				`      <ansi fg="yellow-bold">This is a character room!</ansi> Type <ansi fg="command">character</ansi> to interact.`,
			)
			return d
		}
	}
	return d
}

func roomIsCharacter(room *rooms.Room) bool {
	for _, t := range room.Tags {
		if strings.EqualFold(t, characterTag) {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// character command
// ---------------------------------------------------------------------------

func (m *AltCharactersModule) characterCommand(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {

	if !roomIsCharacter(room) {
		return false, fmt.Errorf(`not in a character room`)
	}

	altNames := []string{}
	nameToAlt := map[string]characters.Character{}

	for _, char := range loadAlts(user.UserId) {
		altNames = append(altNames, char.Name)
		nameToAlt[char.Name] = char
	}

	maxAlts := maxAltCharacters(m)

	if maxAlts == 0 {
		user.SendText(`<ansi fg="203">Alt character are disabled on this server.</ansi>`)
		return true, fmt.Errorf(`alt characters disabled`)
	}

	if user.Character.Level < 5 && len(nameToAlt) < 1 {
		user.SendText(`<ansi fg="203">You must reach level 5 with this character to access character alts.</ansi>`)
		return true, fmt.Errorf(`level 5 minimum`)
	}

	hiredOutChars := map[string]characters.Character{}
	for _, mobInstanceId := range user.Character.GetCharmIds() {
		mob := mobs.GetInstance(mobInstanceId)
		if mob == nil {
			continue
		}
		hiredOutChars[mob.Character.Name] = mob.Character
	}

	menuOptions := []string{`new`}

	cmdPrompt, isNew := user.StartPrompt(`character`, rest)

	if isNew {
		if len(altNames) > 0 {
			menuOptions = append(menuOptions, `view`)
			menuOptions = append(menuOptions, `change`)
			menuOptions = append(menuOptions, `delete`)
			menuOptions = append(menuOptions, `hire`)
		}

		if len(nameToAlt) > 0 {
			altTblTxt := getAltTable(nameToAlt, hiredOutChars, user.UserId, maxAlts)
			user.SendText(``)
			user.SendText(altTblTxt)
		}
	}

	menuOptions = append(menuOptions, `quit`)

	question := cmdPrompt.Ask(`What would you like to do?`, menuOptions, `quit`)
	if !question.Done {
		return true, nil
	}

	if question.Response == `quit` {
		user.ClearPrompt()
		return true, nil
	}

	/////////////////////////
	// Create a new alt
	/////////////////////////
	if question.Response == `new` {

		if len(altNames) >= maxAlts {
			user.SendText(`<ansi fg="203">You already have too many alts.</ansi>`)
			user.SendText(`<ansi fg="203">You'll need to delete one to create a new one.</ansi>`)
			question.RejectResponse()
			return true, nil
		}

		question := cmdPrompt.Ask(`Are you SURE? (Your current character will be saved here to change back to later)`, []string{`yes`, `no`}, `no`)
		if !question.Done {
			return true, nil
		}

		if question.Response == `no` {
			user.ClearPrompt()
			return true, nil
		}

		newAlts := []characters.Character{}
		for _, char := range nameToAlt {
			newAlts = append(newAlts, char)
		}
		newAlts = append(newAlts, *user.Character)
		saveAlts(user.UserId, newAlts)

		user.Character = characters.New()
		user.Character.Name = user.TempName()

		room.RemovePlayer(user.UserId)
		rooms.MoveToRoom(user.UserId, -1)

	}

	/////////////////////////
	// Delete an existing alt
	/////////////////////////
	if question.Response == `delete` {

		if len(nameToAlt) > 0 {
			altTblTxt := getAltTable(nameToAlt, hiredOutChars, user.UserId, maxAlts)
			user.SendText(``)
			user.SendText(altTblTxt)
		}

		question := cmdPrompt.Ask(`Enter the name of the character you wish to delete:`, []string{})
		if !question.Done {
			return true, nil
		}

		match, closeMatch := util.FindMatchIn(question.Response, altNames...)
		if match == `` {
			match = closeMatch
		}

		if match != `` {

			delChar := nameToAlt[match]

			if friend, ok := hiredOutChars[delChar.Name]; ok && friend.Description == delChar.Description {
				user.SendText(fmt.Sprintf(`<ansi fg="mobname">%s</ansi> is currently hired out.`, delChar.Name))
				user.ClearPrompt()
				return true, nil
			}

			question := cmdPrompt.Ask(`<ansi fg="red">Are you SURE you want to delete <ansi fg="username">`+delChar.Name+`</ansi>?</ansi>`, []string{`yes`, `no`}, `no`)
			if !question.Done {
				return true, nil
			}

			if question.Response == `no` {
				user.SendText(`<ansi fg="203">Okay. Aborting.</ansi>`)
				user.ClearPrompt()
				return true, nil
			}

			newAlts := []characters.Character{}
			for _, char := range nameToAlt {
				if char.Name != match {
					newAlts = append(newAlts, char)
				}
			}
			saveAlts(user.UserId, newAlts)

			user.EventLog.Add(`char`, `Deleted alt character: <ansi fg="username">`+match+`</ansi>`)
			user.SendText(`<ansi fg="username">` + match + `</ansi> <ansi fg="red">is deleted.</ansi>`)
			user.ClearPrompt()
			return true, nil
		}

		user.SendText(`<ansi fg="203">No character with the name <ansi fg="username">` + question.Response + `</ansi> found.</ansi>`)
		user.ClearPrompt()
		return true, nil
	}

	/////////////////////////
	// Swap characters
	/////////////////////////
	if question.Response == `change` {

		if len(nameToAlt) > 0 {
			altTblTxt := getAltTable(nameToAlt, hiredOutChars, user.UserId, maxAlts)
			user.SendText(``)
			user.SendText(altTblTxt)
		}

		question := cmdPrompt.Ask(`Enter the name of the character you wish to change to:`, []string{})
		if !question.Done {
			return true, nil
		}

		match, closeMatch := util.FindMatchIn(question.Response, altNames...)
		if match == `` {
			match = closeMatch
		}

		if match != `` {

			char := nameToAlt[match]

			if friend, ok := hiredOutChars[char.Name]; ok && friend.Description == char.Description {
				user.SendText(fmt.Sprintf(`<ansi fg="mobname">%s</ansi> is currently hired out.`, char.Name))
				user.ClearPrompt()
				return true, nil
			}

			question := cmdPrompt.Ask(`<ansi fg="51">Are you SURE you want to change to <ansi fg="username">`+char.Name+`</ansi>?</ansi>`, []string{`yes`, `no`}, `no`)
			if !question.Done {
				return true, nil
			}

			if question.Response == `no` {
				user.SendText(`<ansi fg="203">Okay. Aborting.</ansi>`)
				user.ClearPrompt()
				return true, nil
			}

			oldName := user.Character.Name

			success := swapToAlt(user, match)
			if !success {
				user.SendText(`<ansi fg="203">Something went wrong.</ansi>`)
				user.ClearPrompt()
				return true, nil
			}

			newRoom := rooms.LoadRoom(user.Character.RoomId)
			if newRoom == nil {
				user.Character.RoomId = 0
				newRoom = rooms.LoadRoom(user.Character.RoomId)
			}

			room.RemovePlayer(user.UserId)
			newRoom.AddPlayer(user.UserId)

			users.SaveUser(*user)

			user.EventLog.Add(`char`, `Changed from <ansi fg="username">`+oldName+`</ansi> to alt character: <ansi fg="username">`+char.Name+`</ansi>`)

			user.SendText(term.CRLFStr + `You dematerialize as <ansi fg="username">` + oldName + `</ansi>. and rematerialize as <ansi fg="username">` + char.Name + `</ansi>!` + term.CRLFStr)
			room.SendText(`<ansi fg="username">`+oldName+`</ansi> vanishes, and <ansi fg="username">`+char.Name+`</ansi> appears in a shower of sparks!`, user.UserId)

			user.ClearPrompt()

			events.AddToQueue(events.PlayerChanged{UserId: user.UserId})

			return true, nil
		}

		user.SendText(`<ansi fg="203">No character with the name <ansi fg="username">` + question.Response + `</ansi> found.</ansi>`)
		user.ClearPrompt()
		return true, nil
	}

	/////////////////////////
	// View characters
	/////////////////////////
	if question.Response == `view` {

		if len(nameToAlt) > 0 {
			altTblTxt := getAltTable(nameToAlt, hiredOutChars, user.UserId, maxAlts)
			user.SendText(``)
			user.SendText(altTblTxt)
		}

		question := cmdPrompt.Ask(`Enter the name of the character you wish to view:`, []string{})
		if !question.Done {
			return true, nil
		}

		match, closeMatch := util.FindMatchIn(question.Response, altNames...)
		if match == `` {
			match = closeMatch
		}

		if match != `` {

			char := nameToAlt[match]

			if friend, ok := hiredOutChars[char.Name]; ok && friend.Description == char.Description {
				user.SendText(fmt.Sprintf(`<ansi fg="mobname">%s</ansi> is currently hired out.`, char.Name))
				user.ClearPrompt()
				return true, nil
			}

			char.Validate()

			tmpChar := user.Character
			user.Character = &char

			usercommands.TryCommand(`status`, ``, user.UserId, flags)

			user.Character = tmpChar

			mob := mobs.NewMobById(59, user.Character.RoomId)
			mob.Character = char
			room.AddMob(mob.InstanceId)
			mob.Character.Charm(user.UserId, -1, `suicide vanish`)

			user.ClearPrompt()
			return true, nil
		}

		user.SendText(`<ansi fg="203">No character with the name <ansi fg="username">` + question.Response + `</ansi> found.</ansi>`)
		user.ClearPrompt()
		return true, nil
	}

	/////////////////////////
	// Spawn a helper clone
	/////////////////////////
	if question.Response == `hire` {

		question := cmdPrompt.Ask(`Enter the name of the character you wish to hire:`, []string{})
		if !question.Done {
			return true, nil
		}

		match, closeMatch := util.FindMatchIn(question.Response, altNames...)
		if match == `` {
			match = closeMatch
		}

		if match != `` {

			char := nameToAlt[match]

			if friend, ok := hiredOutChars[char.Name]; ok && friend.Description == char.Description {
				user.SendText(fmt.Sprintf(`<ansi fg="mobname">%s</ansi> is already hired out.`, char.Name))
				user.ClearPrompt()
				return true, nil
			}

			char.Validate()

			gearValue := char.GetGearValue()
			charValue := gearValue + (250 * char.Level)

			mudlog.Debug(`Hire Alt`, `UserId`, user.UserId, `alt-name`, char.Name, `gear-value`, gearValue, `level`, char.Level, `total`, charValue)

			question := cmdPrompt.Ask(fmt.Sprintf(`<ansi fg="51">The price to hire <ansi fg="username">%s</ansi> is <ansi fg="gold">%d gold</ansi>. Are you sure?</ansi>`, char.Name, charValue), []string{`yes`, `no`}, `no`)
			if !question.Done {
				return true, nil
			}

			if question.Response != `yes` {
				user.ClearPrompt()
				return true, nil
			}

			if user.Character.Gold < charValue {
				user.SendText(fmt.Sprintf(`You only have <ansi fg="gold">%d gold</ansi> and it would cost <ansi fg="gold">%d gold</ansi> to hire <ansi fg="username">%s</ansi>.`, charValue, charValue, char.Name))
				user.ClearPrompt()
				return true, nil
			}

			maxCharmed := user.Character.GetSkillLevel(skills.Tame) + 1
			if len(hiredOutChars) >= maxCharmed {
				user.SendText(fmt.Sprintf(`You can only have %d mobs following you at a time.`, maxCharmed))
				user.ClearPrompt()
				return true, nil
			}

			user.Character.Gold -= charValue
			events.AddToQueue(events.EquipmentChange{
				UserId:     user.UserId,
				GoldChange: -charValue,
			})

			mob := mobs.NewMobById(59, user.Character.RoomId)
			mob.Character = char

			mob.Character.Items = []items.Item{}
			mob.Character.Gold = 0
			mob.Character.Bank = 0
			mob.Character.Shop = characters.Shop{}

			mob.Character.AddBuff(36, true)

			room.AddMob(mob.InstanceId)

			mob.Character.Charm(user.UserId, -1, `suicide vanish`)
			user.Character.TrackCharmed(mob.InstanceId, true)

			user.EventLog.Add(`char`, `Hired an alt character to help you out: <ansi fg="username">`+mob.Character.Name+`</ansi>`)

			user.SendText(`<ansi fg="username">` + mob.Character.Name + `</ansi> appears to help you out!`)
			room.SendText(`<ansi fg="username">`+mob.Character.Name+`</ansi> appears to help <ansi fg="username">`+user.Character.Name+`</ansi>!`, user.UserId)

			mob.Command(`emote waves sheepishly.`, 2)

			user.ClearPrompt()
			return true, nil
		}

		user.SendText(`<ansi fg="203">No character with the name <ansi fg="username">` + question.Response + `</ansi> found.</ansi>`)
		user.ClearPrompt()
		return true, nil
	}

	return true, nil
}

func getAltTable(nameToAlt map[string]characters.Character, charmedChars map[string]characters.Character, viewingUserId int, maxAlts int) string {

	headers := []string{"Name", "Level", "Race", "Profession", "Alignment", "Status"}
	rows := [][]string{}

	for _, char := range nameToAlt {

		allRanks := char.GetAllSkillRanks()
		raceName := `Unknown`
		if raceInfo := races.GetRace(char.RaceId); raceInfo != nil {
			raceName = raceInfo.Name
		}

		mobBusy := ``
		if c, ok := charmedChars[char.Name]; ok {
			if c.Description == char.Description {
				mobBusy = `<ansi fg="210">busy</ansi>`
			}
		}

		rows = append(rows, []string{
			fmt.Sprintf(`<ansi fg="username">%s</ansi>`, char.Name),
			strconv.Itoa(char.Level),
			raceName,
			skills.GetProfession(allRanks),
			fmt.Sprintf(`<ansi fg="%s">%s</ansi>`, char.AlignmentName(), char.AlignmentName()),
			mobBusy,
		})
	}

	sort.Slice(rows, func(i, j int) bool {
		num1, _ := strconv.Atoi(rows[i][1])
		num2, _ := strconv.Atoi(rows[j][1])
		return num1 < num2
	})

	altTableData := templates.GetTable(fmt.Sprintf(`Your alt characters (%d/%d)`, len(nameToAlt), maxAlts), headers, rows)
	tplTxt, _ := templates.Process("tables/generic", altTableData, viewingUserId)

	return tplTxt
}
