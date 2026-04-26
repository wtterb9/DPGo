package usercommands

import (
	"fmt"
	"sort"
	"strings"

	"github.com/GoMudEngine/GoMud/internal/buffs"
	"github.com/GoMudEngine/GoMud/internal/configs"
	"github.com/GoMudEngine/GoMud/internal/events"
	"github.com/GoMudEngine/GoMud/internal/rooms"
	"github.com/GoMudEngine/GoMud/internal/skills"
	"github.com/GoMudEngine/GoMud/internal/users"
)

const remortConfirmPhrase = "confirm"

func Remort(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {
	cfg := configs.GetGamePlayConfig().Remort
	if !cfg.Enabled {
		user.SendText(`Remort is currently disabled.`)
		return true, nil
	}

	if user.Role == users.RoleAdmin {
		user.SendText(`Immortals cannot remort.`)
		return true, nil
	}

	if cfg.RequireRoomTag {
		requiredTag := strings.TrimSpace(strings.ToLower(string(cfg.RoomTag)))
		if requiredTag == `` {
			requiredTag = `remort`
		}
		hasTag := false
		for _, tag := range room.Tags {
			if strings.ToLower(strings.TrimSpace(tag)) == requiredTag {
				hasTag = true
				break
			}
		}
		if !hasTag {
			user.SendText(`You must visit a remorter to perform this ritual.`)
			return true, nil
		}
	}

	rest = strings.TrimSpace(strings.ToLower(rest))
	if rest == `` || rest == `help` || rest == `status` {
		sendRemortStatus(user, int(cfg.MinLevel), int(cfg.CostGold))
		return true, nil
	}

	if rest != remortConfirmPhrase {
		user.SendText(fmt.Sprintf(`Type %s to complete remort, or %s to view requirements.`, `<ansi fg="command">remort confirm</ansi>`, `<ansi fg="command">remort</ansi>`))
		return true, nil
	}

	if user.Character.Level < int(cfg.MinLevel) {
		user.SendText(fmt.Sprintf(`You can't remort until level %d.`, int(cfg.MinLevel)))
		return true, nil
	}

	if user.Character.Gold < int(cfg.CostGold) {
		user.SendText(fmt.Sprintf(`It costs %d gold to remort.`, int(cfg.CostGold)))
		return true, nil
	}

	if len(user.Character.GetAllWornItems()) > 0 {
		user.SendText(`You must come to the remorter without any equipment worn.`)
		return true, nil
	}

	remortPath := determineRemortPath(user)

	user.Character.Gold -= int(cfg.CostGold)
	user.Character.Level = 1
	user.Character.Experience = 1
	user.Character.TrainingPoints = 10
	user.Character.StatPoints = 0
	user.Character.Health = user.Character.HealthMax.Value
	user.Character.Mana = user.Character.ManaMax.Value
	user.Character.Cooldowns = map[string]int{}
	user.Character.Skills = map[string]int{}
	user.Character.SpellBook = map[string]int{}
	user.Character.Aggro = nil
	user.Character.CancelBuffsWithFlag(buffs.All)

	applyRemortSkillPackage(user, remortPath)

	remortCount := 0
	if existing, ok := user.Character.MiscData[`remort_count`]; ok {
		if n, ok := existing.(int); ok {
			remortCount = n
		} else if n, ok := existing.(float64); ok {
			remortCount = int(n)
		}
	}
	remortCount++
	user.Character.MiscData[`remort_count`] = remortCount
	user.Character.MiscData[`remort_path`] = remortPath

	user.Character.Validate()

	user.SendText(fmt.Sprintf(`The remort ritual completes. You are reborn as a <ansi fg="yellow-bold">%s</ansi>.`, remortPath))
	user.SendText(fmt.Sprintf(`You have remorted <ansi fg="yellow">%d</ansi> time(s).`, remortCount))
	room.SendText(fmt.Sprintf(`<ansi fg="username">%s</ansi> is engulfed in spiraling light and emerges reborn.`, user.Character.Name), user.UserId)

	return true, nil
}

func sendRemortStatus(user *users.UserRecord, minLevel int, costGold int) {
	path := determineRemortPath(user)
	user.SendText(`Remort requirements:`)
	user.SendText(fmt.Sprintf(` - Minimum Level: <ansi fg="yellow">%d</ansi> (you are %d)`, minLevel, user.Character.Level))
	user.SendText(fmt.Sprintf(` - Cost: <ansi fg="gold">%d gold</ansi> (you have %d)`, costGold, user.Character.Gold))
	user.SendText(fmt.Sprintf(` - Current remort path: <ansi fg="yellow-bold">%s</ansi>`, path))
	user.SendText(` - You must have no equipped items.`)
	user.SendText(fmt.Sprintf(`Use <ansi fg="command">remort %s</ansi> to proceed.`, remortConfirmPhrase))
}

func determineRemortPath(user *users.UserRecord) string {
	ranks := skills.GetProfessionRanks(user.Character.GetAllSkillRanks())
	sort.Slice(ranks, func(i, j int) bool { return ranks[i].Completion > ranks[j].Completion })
	if len(ranks) == 0 || ranks[0].Completion <= 0 {
		return `ranger`
	}

	top := strings.ToLower(ranks[0].Profession)
	raceName := ``
	if raceInfo := user.Character.Race(); raceInfo != `` {
		raceName = strings.ToLower(raceInfo)
	}

	switch top {
	case `warrior`, `paladin`, `ranger`, `monster hunter`:
		if raceName == `human` || raceName == `elf` {
			return `paladin`
		}
		return `ranger`
	case `assassin`:
		return `assassin`
	case `sorcerer`:
		return `magus`
	case `arcane scholar`, `explorer`:
		return `mystic`
	default:
		return `ranger`
	}
}

func applyRemortSkillPackage(user *users.UserRecord, remortPath string) {
	set := func(tag skills.SkillTag, lvl int) {
		user.Character.SetSkill(tag.String(), lvl)
	}

	switch remortPath {
	case `paladin`:
		set(skills.Brawling, 2)
		set(skills.Protection, 2)
	case `ranger`:
		set(skills.Track, 2)
		set(skills.Map, 1)
		set(skills.Search, 1)
	case `assassin`:
		set(skills.Skulduggery, 2)
		set(skills.DualWield, 1)
		set(skills.Track, 1)
	case `magus`:
		set(skills.Cast, 2)
		set(skills.Enchant, 1)
	case `mystic`:
		set(skills.Scribe, 2)
		set(skills.Inspect, 1)
		set(skills.Portal, 1)
	default:
		set(skills.Track, 1)
	}
}
