package procedural

import (
	"github.com/GoMudEngine/GoMud/internal/exit"
	"github.com/GoMudEngine/GoMud/internal/rooms"
)

func CreateEphemeralMaze2D(mazeRooms [][]*GridRoom) (allRoomIds []int, startRoomId int, endRoomId int) {

	startRoomId = 0
	endRoomId = 0

	mazeH := len(mazeRooms)
	if mazeH == 0 || len(mazeRooms[0]) == 0 {
		return allRoomIds, startRoomId, endRoomId
	}
	mazeW := len(mazeRooms[0])

	roomCt := 0
	mazeRoomToTmpRoomId := map[MazeRoom]int{}

	for x := 0; x < mazeW; x++ {
		for y := 0; y < mazeH; y++ {

			mazeRoomNow := mazeRooms[y][x]

			if mazeRoomNow == nil {
				continue
			}

			roomCt++
		}
	}

	allRoomIds, _ = rooms.CreateEmptyEphemeralRooms(roomCt)

	nextTmpRoomId := 0

	for y := 0; y < mazeH; y++ {
		for x := 0; x < mazeW; x++ {

			if mazeRooms[y][x] == nil {
				continue
			}

			tmpId1, ok := mazeRoomToTmpRoomId[mazeRooms[y][x]]
			if !ok {
				tmpId1 = allRoomIds[nextTmpRoomId]
				mazeRoomToTmpRoomId[mazeRooms[y][x]] = tmpId1
				nextTmpRoomId++
			}

			r1 := rooms.LoadRoom(tmpId1)

			if mazeRooms[y][x].IsStart() {
				startRoomId = tmpId1
			} else if mazeRooms[y][x].IsEnd() {
				endRoomId = tmpId1
			}

			if y > 0 && mazeRooms[y-1][x] != nil {
				if mazeRooms[y][x].IsConnectedTo(mazeRooms[y-1][x]) {
					// Connect the rooms
					tmpId2, ok := mazeRoomToTmpRoomId[mazeRooms[y-1][x]]
					if !ok {
						tmpId2 = allRoomIds[nextTmpRoomId]
						mazeRoomToTmpRoomId[mazeRooms[y-1][x]] = tmpId2
						nextTmpRoomId++
					}
					r2 := rooms.LoadRoom(tmpId2)

					r1.Exits["north"] = exit.RoomExit{
						RoomId:       r2.RoomId,
						MapDirection: "north",
					}
					r2.Exits["south"] = exit.RoomExit{
						RoomId:       r1.RoomId,
						MapDirection: "south",
					}
				}
			}

			if x > 0 && mazeRooms[y][x-1] != nil {
				if mazeRooms[y][x].IsConnectedTo(mazeRooms[y][x-1]) {
					// Connect the rooms
					tmpId2, ok := mazeRoomToTmpRoomId[mazeRooms[y][x-1]]
					if !ok {
						tmpId2 = allRoomIds[nextTmpRoomId]
						mazeRoomToTmpRoomId[mazeRooms[y][x-1]] = tmpId2
						nextTmpRoomId++
					}
					r2 := rooms.LoadRoom(tmpId2)

					r1.Exits["west"] = exit.RoomExit{
						RoomId:       r2.RoomId,
						MapDirection: "west",
					}
					r2.Exits["east"] = exit.RoomExit{
						RoomId:       r1.RoomId,
						MapDirection: "east",
					}
				}
			}

			if y < mazeH-1 && mazeRooms[y+1][x] != nil {

				if mazeRooms[y][x].IsConnectedTo(mazeRooms[y+1][x]) {
					// Connect the rooms
					tmpId2, ok := mazeRoomToTmpRoomId[mazeRooms[y+1][x]]
					if !ok {
						tmpId2 = allRoomIds[nextTmpRoomId]
						mazeRoomToTmpRoomId[mazeRooms[y+1][x]] = tmpId2
						nextTmpRoomId++
					}
					r2 := rooms.LoadRoom(tmpId2)

					r1.Exits["south"] = exit.RoomExit{
						RoomId:       r2.RoomId,
						MapDirection: "south",
					}
					r2.Exits["north"] = exit.RoomExit{
						RoomId:       r1.RoomId,
						MapDirection: "north",
					}
				}
			}
			if x < mazeW-1 && mazeRooms[y][x+1] != nil {
				if mazeRooms[y][x].IsConnectedTo(mazeRooms[y][x+1]) {
					// Connect the rooms
					tmpId2, ok := mazeRoomToTmpRoomId[mazeRooms[y][x+1]]
					if !ok {
						tmpId2 = allRoomIds[nextTmpRoomId]
						mazeRoomToTmpRoomId[mazeRooms[y][x+1]] = tmpId2
						nextTmpRoomId++
					}
					r2 := rooms.LoadRoom(tmpId2)

					r1.Exits["east"] = exit.RoomExit{
						RoomId:       r2.RoomId,
						MapDirection: "east",
					}
					r2.Exits["west"] = exit.RoomExit{
						RoomId:       r1.RoomId,
						MapDirection: "west",
					}
				}
			}

		}
	}

	return allRoomIds, startRoomId, endRoomId
}
