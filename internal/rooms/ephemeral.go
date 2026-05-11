package rooms

import (
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/GoMudEngine/GoMud/internal/mudlog"
	"github.com/GoMudEngine/GoMud/internal/util"
)

const (
	ephemeralChunksLimit = 100     // The maximum number of ephemeral chunks that can be created
	ephemeralChunkSize   = 1000    // The maximum quantity of ephemeral room's that can be copied/created in a given chunk.
	roomIdMin32Bit       = 1000000 // 1,000,000 - Safe for 32-bit systems (was 1,000,000,000 which overflows when multiplied by 1000)
)

var (
	ephemeralRoomIdMinimum = roomIdMin32Bit                // 1,000,000 is assuming 32 bit. the init() function may override this value to 1,000,000,000 on 64-bit systems.
	ephemeralRoomChunks    = [ephemeralChunksLimit][]int{} // map of ranges to actual rooms. If empty, slot is available.
	originalRoomIdLookups  = map[int]int{}                 // a map of ephemeralId's to their original RoomId's, for special purposes
	// errors
	errNoRoomIdsProvided   = errors.New(`no RoomId's were provided`)
	errInvalidRoomQuantity = errors.New(`one or more empty rooms must be requested.`)
	errRoomNotFound        = errors.New(`the requested RoomId wasn't found`)
	errZoneNotFound        = errors.New(`the requested zone wasn't found`)
	errEphemeralChunkLimit = fmt.Errorf(`the ephemeral chunk limit of %d has been reached.`, ephemeralChunksLimit)
	errEphemeralRoomLimit  = fmt.Errorf(`the ephemeral room request limit of %d is exceeded.`, ephemeralChunkSize)
	errNonUniqueRoomId     = errors.New(`a RoomId has been provided more than once. they must all be unique`)
)

func GetChunkCount() int {
	result := 0
	for i := 0; i < ephemeralChunksLimit; i++ {
		if len(ephemeralRoomChunks[i]) > 0 {
			result++
		}
	}
	return result
}

// Looks at chunk array and returns the first unused/empty index, or error if none found.
func getNextAvailableChunk() (int, error) {
	for i := 0; i < ephemeralChunksLimit; i++ {
		if len(ephemeralRoomChunks[i]) == 0 {
			return i, nil
		}
	}
	return -1, errEphemeralChunkLimit
}

// Looks for any ephemeralRoomId's that exits for the given roomId.
// Returns a slice containing all found ephemeralIds
func FindEphemeralRoomIds(roomId int) []int {

	allEphemeralRoomIds := []int{}
	for ephemeralRoomId, originalRoomId := range originalRoomIdLookups {
		if originalRoomId == roomId {
			allEphemeralRoomIds = append(allEphemeralRoomIds, ephemeralRoomId)
		}
	}

	return allEphemeralRoomIds
}

// Accepts a quantity and returns roomId's for a chunk of empty rooms
// This is a special use function for dynamically building ephemeral rooms in code
func CreateEmptyEphemeralRooms(qty int) ([]int, error) {

	if qty > ephemeralChunkSize {
		return []int{}, errEphemeralRoomLimit
	}

	if qty < 1 {
		return []int{}, errInvalidRoomQuantity
	}

	ephemeralRoomIds := make([]int, 0, qty)

	// First find a chunk ID
	chunkId, err := getNextAvailableChunk()
	if err != nil {
		return []int{}, err
	}

	for i := 0; i < qty; i++ {
		room := NewEmptyRoom()
		room.RoomId = ephemeralRoomIdMinimum + (chunkId * ephemeralChunkSize) + i

		// Save the original room ID in case we need it at some point
		originalRoomIdLookups[room.RoomId] = 0

		addRoomToMemory(room)

		ephemeralRoomIds = append(ephemeralRoomIds, room.RoomId)
	}

	trackedRoomIds := make([]int, len(ephemeralRoomIds))
	copy(trackedRoomIds, ephemeralRoomIds)

	ephemeralRoomChunks[chunkId] = trackedRoomIds

	mudlog.Info("CreateEmptyEphemeral...()",
		"created", len(trackedRoomIds),
		"chunkId", chunkId,
		"Ephemeral RoomIds", fmt.Sprintf("%d - %d", ephemeralRoomIds[0], ephemeralRoomIds[len(ephemeralRoomIds)-1]),
		"Chunks Remaining", ephemeralChunksLimit-GetChunkCount())

	return ephemeralRoomIds, nil
}

// accepts RoomId's as arguments, and creates ephemeral copies of them, returning the new ID's of the copies.
func CreateEphemeralRoomIds(roomIds ...int) (map[int]int, error) {
	if len(roomIds) == 0 {
		return map[int]int{}, errNoRoomIdsProvided
	}

	if len(roomIds) > ephemeralChunkSize {
		return map[int]int{}, errEphemeralRoomLimit
	}

	ephemeralRooms := make(map[int]int, len(roomIds))

	// Make sure that all values in the roomIds slice are unique.
	roomIdReplacements := map[int]int{} // original=>ephemeral replacements
	for _, roomId := range roomIds {
		if _, ok := roomIdReplacements[roomId]; ok {
			return ephemeralRooms, errNonUniqueRoomId
		}
		roomIdReplacements[roomId] = 0
	}

	// First find a chunk ID
	chunkId, err := getNextAvailableChunk()
	if err != nil {
		return map[int]int{}, err
	}

	ephemeralRoomIds := []int{}
	for i, roomId := range roomIds {
		// Load only data from the template

		if roomId == 0 {
			continue
		}

		room := LoadRoomTemplate(roomId)
		if room == nil {
			continue
		}

		room.RoomId = ephemeralRoomIdMinimum + (chunkId * ephemeralChunkSize) + i

		// Save the original room ID in case we need it at some point
		originalRoomIdLookups[room.RoomId] = roomId

		// Temporarily track what the original room has been copied to.
		roomIdReplacements[roomId] = room.RoomId

		addRoomToMemory(room)

		ephemeralRooms[roomId] = room.RoomId
		ephemeralRoomIds = append(ephemeralRoomIds, room.RoomId)
	}

	// Replace references to original RoomId's with new Ephemeral ones
	for _, roomId := range ephemeralRoomIds {
		room := LoadRoom(roomId)
		if room == nil {
			continue
		}

		for exitName, exitInfo := range room.Exits {
			if replacementRoomId, ok := roomIdReplacements[exitInfo.RoomId]; ok {
				exitInfo.RoomId = replacementRoomId
				room.Exits[exitName] = exitInfo
			}
		}

	}

	ephemeralRoomChunks[chunkId] = ephemeralRoomIds

	roomIdRange := "none"
	if len(ephemeralRoomIds) > 0 {
		roomIdRange = fmt.Sprintf("%d - %d", ephemeralRoomIds[0], ephemeralRoomIds[len(ephemeralRoomIds)-1])
	}

	mudlog.Info("CreateEphemeral...()",
		"created", len(ephemeralRoomIds),
		"chunkId", chunkId,
		"Ephemeral RoomIds", roomIdRange,
		"Chunks Remaining", ephemeralChunksLimit-GetChunkCount())

	return ephemeralRooms, nil
}

// accepts RoomId's as arguments, and creates ephemeral copies of them, returning the new ID's of the copies.
func CreateEphemeralZone(zoneName string) (map[int]int, error) {

	if _, exists := roomManager.zones[zoneName]; !exists {
		return nil, errZoneNotFound
	}

	roomIds := make([]int, len(roomManager.zones[zoneName].RoomIds))

	idx := 0
	for roomId, _ := range roomManager.zones[zoneName].RoomIds {
		roomIds[idx] = roomId
		idx++
	}

	return CreateEphemeralRoomIds(roomIds...)
}

func IsEphemeralRoomId(roomId int) bool {
	return roomId >= ephemeralRoomIdMinimum
}

func TryEphemeralCleanup(ephemeralRoomId int) []int {

	chunkId := int(math.Floor(float64(ephemeralRoomId-ephemeralRoomIdMinimum) / ephemeralChunkSize))

	for _, ephemeralRoomId := range ephemeralRoomChunks[chunkId] {

		room := LoadRoom(ephemeralRoomId)
		if room == nil {
			continue
		}

		if len(room.players) > 0 {
			return []int{}
		}
	}

	deletedMin := 0
	deletedMax := 0

	deletedRoomIds := make([]int, len(ephemeralRoomChunks[chunkId]))

	for i, ephemeralRoomId := range ephemeralRoomChunks[chunkId] {

		deletedRoomIds[i] = ephemeralRoomId

		if deletedMin == 0 || ephemeralRoomId < deletedMin {
			deletedMin = ephemeralRoomId
		}
		if deletedMax == 0 || ephemeralRoomId > deletedMax {
			deletedMax = ephemeralRoomId
		}

		room := LoadRoom(ephemeralRoomId)
		if room == nil {
			continue
		}

		delete(originalRoomIdLookups, room.RoomId)
		removeRoomFromMemory(room)
	}

	ephemeralRoomChunks[chunkId] = []int{}

	mudlog.Info("TryEphemeralCleanup", "deleted", len(deletedRoomIds), "chunkId", chunkId, "RoomIds", fmt.Sprintf("%d - %d", deletedMin, deletedMax), "Chunks Remaining", GetChunkCount())

	return deletedRoomIds
}

// All this does is unload chunks with no players in them.
func EphemeralRoomMaintenance() []int {
	start := time.Now()
	defer func() {
		util.TrackTime(`EphemeralRoomMaintenance()`, time.Since(start).Seconds())
	}()

	// If no lookups are stored, then there can't be anything in the chunks (unless we messed up)
	if len(originalRoomIdLookups) == 0 {
		return []int{}
	}

	for i := 0; i < ephemeralChunksLimit; i++ {
		if len(ephemeralRoomChunks[i]) > 0 {
			return TryEphemeralCleanup(ephemeralRoomChunks[i][0])
		}
	}
	return []int{}
}

func GetOriginalRoom(roomId int) int {
	if roomId < ephemeralRoomIdMinimum {
		return roomId
	}
	return originalRoomIdLookups[roomId]
}

func init() {
	if math.MaxInt > ephemeralRoomIdMinimum*1000 {
		ephemeralRoomIdMinimum = ephemeralRoomIdMinimum * 1000 // 1,000,000 => 1,000,000,000 on 64-bit systems
	}
}
