package usercommands

import (
	"fmt"

	"github.com/GoMudEngine/GoMud/internal/events"
	"github.com/GoMudEngine/GoMud/internal/rooms"
	"github.com/GoMudEngine/GoMud/internal/users"
)

func Class(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {
	currentClass := inferDarkPawnsClass(user)
	remortCount := getRemortCount(user)

	user.SendText(fmt.Sprintf(`Your DarkPawns class track: <ansi fg="yellow-bold">%s</ansi>`, currentClass))
	user.SendText(fmt.Sprintf(`Remort count: <ansi fg="yellow">%d</ansi>`, remortCount))
	if remortCount > 0 {
		user.SendText(`Use <ansi fg="command">remort</ansi> to inspect next remort requirements.`)
	}

	return true, nil
}
