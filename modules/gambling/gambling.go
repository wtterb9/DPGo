package gambling

import (
	"embed"
	"fmt"
	"io/fs"
	"strings"
	"time"

	"github.com/GoMudEngine/GoMud/internal/events"
	"github.com/GoMudEngine/GoMud/internal/items"
	"github.com/GoMudEngine/GoMud/internal/mudlog"
	"github.com/GoMudEngine/GoMud/internal/plugins"
	"github.com/GoMudEngine/GoMud/internal/rooms"
	"github.com/GoMudEngine/GoMud/internal/users"
	"github.com/GoMudEngine/GoMud/internal/util"
	lru "github.com/hashicorp/golang-lru/v2"
)

var (
	//go:embed files/*
	files embed.FS
)

const defaultCost = 10

func init() {

	roomTagCache, _ := lru.New[int, roomTagEntry](64)
	g := &GamblingModule{
		plug:         plugins.New(`gambling`, `1.0`),
		state:        make(SlotState),
		roomTagCache: roomTagCache,
	}

	if err := g.plug.AttachFileSystem(files); err != nil {
		panic(err)
	}

	g.plug.Web.AdminPage("Config", "gambling-config", "html/admin/gambling-config.html", true, "Modules", "Gambling", nil)
	for itemId, path := range map[int]string{
		1040000: `files/datafiles/items/1040000-6_sided_die.js`,
		1040001: `files/datafiles/items/1040001-lucky_coin.js`,
		1040002: `files/datafiles/items/1040002-tarot_deck.js`,
		1040003: `files/datafiles/items/1040003-magic_8_ball.js`,
		1040004: `files/datafiles/items/1040004-empty_bottle.js`,
		1040005: `files/datafiles/items/1040005-deck_of_cards.js`,
	} {
		scriptBytes, err := fs.ReadFile(files, path)
		if err != nil {
			mudlog.Error("gambling: failed to read item script", "path", path, "error", err)
			continue
		}
		items.RegisterItemScript(itemId, string(scriptBytes))
	}

	// Register the "play" user command (handles both slots and claw machine).
	g.plug.AddUserCommand(`play`, g.playCommand, false, false)

	g.plug.ReserveTags(`slots`, `slot machine`, `claw machine`)

	// Persist the jackpot across restarts.
	g.plug.Callbacks.SetOnLoad(g.load)
	g.plug.Callbacks.SetOnSave(g.save)

	// Hook into room look to inject slot machine and claw machine alerts.
	rooms.OnRoomLook.Register(g.onRoomLook)
	rooms.OnRoomLook.Register(g.onRoomLookClaw)

	// Intercept "look" commands before the engine processes them so that
	// "look slot machine" and "look claw machine" are handled directly by
	// the module without requiring nouns to be injected into room state.
	events.RegisterListener(events.Input{}, g.onLookInput, events.First)
}

// parseLookTarget extracts the target string from a look command input, stripping
// the leading "at " and "the " prefixes that the core look command also strips.
// Returns an empty string if the input is not a look command or has no target.
func parseLookTarget(inputText string) string {
	lower := strings.ToLower(strings.TrimSpace(inputText))

	cmd, rest, _ := strings.Cut(lower, " ")
	if cmd != `look` && cmd != `l` {
		return ""
	}

	rest = strings.TrimSpace(rest)
	if strings.HasPrefix(rest, `at `) {
		rest = strings.TrimPrefix(rest, `at `)
	}
	if strings.HasPrefix(rest, `the `) {
		rest = strings.TrimPrefix(rest, `the `)
	}
	return strings.TrimSpace(rest)
}

// onLookInput intercepts look commands directed at gambling fixtures before the
// engine's look handler runs. If the target matches a fixture present in the
// room, it sends the description directly and cancels the event so the engine
// does not process it further.
func (g *GamblingModule) onLookInput(e events.Event) events.ListenerReturn {
	evt, ok := e.(events.Input)
	if !ok || evt.UserId == 0 {
		return events.Continue
	}

	target := parseLookTarget(evt.InputText)
	if target == "" {
		return events.Continue
	}

	user := users.GetByUserId(evt.UserId)
	if user == nil {
		return events.Continue
	}

	room := rooms.LoadRoom(user.Character.RoomId)
	if room == nil {
		return events.Continue
	}

	hasSlots, hasClaw := g.cachedRoomTags(room)

	if _, c := util.FindMatchIn(target, `slot machine`, `slots`, `slot`); c != `` && hasSlots {
		g.sendLookDescription(user, room, `slot machine`, g.slotMachineNounDesc(room.RoomId))
		return events.Cancel
	}

	if _, c := util.FindMatchIn(target, `claw machine`, `claw`); c != `` && hasClaw {
		g.sendLookDescription(user, room, `claw machine`, g.clawMachineNounDesc())
		return events.Cancel
	}

	return events.Continue
}

// sendLookDescription sends a noun look response matching the framing used by
// the core look command: blank line, "You look at the <noun>:", blank line,
// description lines, blank line. Also broadcasts the examine message to the room.
func (g *GamblingModule) sendLookDescription(user *users.UserRecord, room *rooms.Room, noun, desc string) {
	user.SendText(``)
	user.SendText(fmt.Sprintf(`You look at the <ansi fg="noun">%s</ansi>:`, noun))
	user.SendText(``)
	for _, line := range strings.Split(desc, "\n") {
		user.SendText(line)
	}
	user.SendText(``)

	room.SendText(
		fmt.Sprintf(`<ansi fg="username">%s</ansi> is examining the <ansi fg="noun">%s</ansi>.`, user.Character.Name, noun),
		user.UserId,
	)
}

const roomTagCacheTTL = 30 * time.Second

// roomTagEntry is a cached result of the tag checks for one room.
type roomTagEntry struct {
	hasSlots bool
	hasClaw  bool
	expiry   time.Time
}

// GamblingModule holds module-level state for the gambling plugin.
type GamblingModule struct {
	plug         *plugins.Plugin
	state        SlotState
	roomTagCache *lru.Cache[int, roomTagEntry]
}

func (g *GamblingModule) load() {
	g.plug.ReadIntoStruct(`slotstate`, &g.state)
}

func (g *GamblingModule) save() {
	g.plug.WriteStruct(`slotstate`, g.state)
}

// cachedRoomTags returns the cached slot/claw tag results for the room,
// recomputing them if the cache entry is absent or expired.
func (g *GamblingModule) cachedRoomTags(r *rooms.Room) (hasSlots bool, hasClaw bool) {
	if entry, ok := g.roomTagCache.Get(r.RoomId); ok && time.Now().Before(entry.expiry) {
		return entry.hasSlots, entry.hasClaw
	}
	hasSlots = roomHasSlots(r)
	hasClaw = roomHasClaw(r)
	g.roomTagCache.Add(r.RoomId, roomTagEntry{
		hasSlots: hasSlots,
		hasClaw:  hasClaw,
		expiry:   time.Now().Add(roomTagCacheTTL),
	})
	return hasSlots, hasClaw
}

// onRoomLook injects a slot machine alert when the room has the slots tag.
func (g *GamblingModule) onRoomLook(d rooms.RoomTemplateDetails) rooms.RoomTemplateDetails {
	for _, t := range d.Tags {
		tl := strings.ToLower(t)
		if tl == `slots` || tl == `slot machine` {
			d.RoomAlerts = append(d.RoomAlerts,
				`There is a <ansi fg="cyan-bold">slot machine</ansi> here! You can <ansi fg="command">look</ansi> at or <ansi fg="command">play</ansi> it.`,
			)
			return d
		}
	}
	return d
}

// playCommand handles "play slots" / "play slot machine" / "play claw machine" / "play claw".
func (g *GamblingModule) playCommand(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {

	arg := strings.TrimSpace(rest)

	if m, c := util.FindMatchIn(arg, `slot machine`, `slots`, `slot`); m != `` || c != `` {
		hasSlots, _ := g.cachedRoomTags(room)
		if !hasSlots {
			user.SendText(`There is no slot machine here.`)
			return true, nil
		}
		g.playSlots(user, room)
		return true, nil
	}

	if m, c := util.FindMatchIn(arg, `claw machine`, `claw`); m != `` || c != `` {
		_, hasClaw := g.cachedRoomTags(room)
		if !hasClaw {
			user.SendText(`There is no claw machine here.`)
			return true, nil
		}
		g.playClaw(user, room)
		return true, nil
	}

	user.SendText(`Play what? Try <ansi fg="command">play slots</ansi> or <ansi fg="command">play claw machine</ansi>.`)
	return true, nil
}
