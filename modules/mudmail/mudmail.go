package mudmail

import (
	"embed"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/GoMudEngine/GoMud/internal/configs"
	"github.com/GoMudEngine/GoMud/internal/events"
	"github.com/GoMudEngine/GoMud/internal/items"
	"github.com/GoMudEngine/GoMud/internal/language"
	"github.com/GoMudEngine/GoMud/internal/plugins"
	"github.com/GoMudEngine/GoMud/internal/rooms"
	"github.com/GoMudEngine/GoMud/internal/templates"
	"github.com/GoMudEngine/GoMud/internal/term"
	"github.com/GoMudEngine/GoMud/internal/users"
)

var (
	//go:embed files/*
	files embed.FS
)

func init() {
	m := &MudmailModule{
		plug:    plugins.New(`mudmail`, `1.0`),
		inboxes: make(map[int]Inbox),
	}

	if err := m.plug.AttachFileSystem(files); err != nil {
		panic(err)
	}

	m.plug.AddUserCommand(`inbox`, m.inboxCommand, true, false)
	m.plug.AddUserCommand(`mudmail`, m.mudmailCommand, true, true)

	m.plug.ExportFunction(`SendMudMail`, m.SendMudMail)

	m.plug.Callbacks.SetOnSave(m.onSave)

	// Admin page: Mudmail management UI.
	m.plug.Web.AdminPage(
		"View / Edit",
		"mudmail",
		"html/admin/mudmail.html",
		true,
		"Modules",
		"Mudmail",
		nil,
	)

	// Admin page: Mudmail API docs, nested under the Mudmail nav entry.
	m.plug.Web.AdminPage(
		"API Docs",
		"mudmail-api",
		"html/admin/mudmail-api.html",
		true,
		"Modules",
		"Mudmail",
		nil,
	)

	// Admin API endpoints.
	m.plug.Web.AdminAPIEndpoint("GET", "mudmail", m.apiAdminListMudmail)
	m.plug.Web.AdminAPIEndpoint("GET", "mudmail-body/{user_id}/{timestamp}", m.apiAdminGetMudmailBody)
	m.plug.Web.AdminAPIEndpoint("POST", "mudmail", m.apiAdminSendMudmail)
	m.plug.Web.AdminAPIEndpoint("DELETE", "mudmail", m.apiAdminDeleteMudmail)

	events.RegisterListener(events.PlayerSpawn{}, m.onPlayerSpawn)
	events.RegisterListener(events.PlayerDespawn{}, m.onPlayerDespawn)
}

// Message is a single inbox message.
type Message struct {
	FromUserId int         `yaml:"fromuserid,omitempty"`
	FromName   string      `yaml:"fromname"`
	Body       string      `yaml:"body"`
	Item       *items.Item `yaml:"item,omitempty"`
	Gold       int         `yaml:"gold,omitempty"`
	Read       bool        `yaml:"read,omitempty"`
	DateSent   time.Time   `yaml:"datesent"`
}

func (m Message) DateString() string {
	tFormat := string(configs.GetConfig().TextFormats.Time)
	return m.DateSent.Format(tFormat)
}

// Inbox is an ordered slice of messages for one user, newest first.
type Inbox []Message

// MudmailModule owns all inbox state.
type MudmailModule struct {
	plug    *plugins.Plugin
	inboxes map[int]Inbox // keyed by userId; loaded on PlayerSpawn
}

// inboxKey returns the plugin data identifier for a given userId.
func inboxKey(userId int) string {
	return fmt.Sprintf(`inbox-user-%d`, userId)
}

// load reads a user's inbox from the plugin data store.
func (m *MudmailModule) load(userId int) Inbox {
	var inbox Inbox
	m.plug.ReadIntoStruct(inboxKey(userId), &inbox)
	if inbox == nil {
		inbox = Inbox{}
	}
	return inbox
}

// save writes a user's inbox to the plugin data store.
func (m *MudmailModule) save(userId int, inbox Inbox) {
	m.plug.WriteStruct(inboxKey(userId), inbox)
}

// onSave persists all currently loaded inboxes.
func (m *MudmailModule) onSave() {
	for userId, inbox := range m.inboxes {
		m.save(userId, inbox)
	}
}

// onPlayerSpawn loads the user's inbox into memory and migrates legacy data.
func (m *MudmailModule) onPlayerSpawn(e events.Event) events.ListenerReturn {
	evt, ok := e.(events.PlayerSpawn)
	if !ok {
		return events.Continue
	}

	inbox := m.load(evt.UserId)

	m.inboxes[evt.UserId] = inbox

	// Notify the user if they have unread messages.
	if countUnread(inbox) > 0 {
		if u := users.GetByUserId(evt.UserId); u != nil {
			u.Command(`inbox check`)
		}
	}

	return events.Continue
}

// onPlayerDespawn saves and unloads the user's inbox.
func (m *MudmailModule) onPlayerDespawn(e events.Event) events.ListenerReturn {
	evt, ok := e.(events.PlayerDespawn)
	if !ok {
		return events.Continue
	}

	if inbox, exists := m.inboxes[evt.UserId]; exists {
		m.save(evt.UserId, inbox)
		delete(m.inboxes, evt.UserId)
	}

	return events.Continue
}

// SendMudMail is exported for use by other modules.
// Signature: func(userId int, fromName string, message string, gold int, itm *items.Item)
func (m *MudmailModule) SendMudMail(userId int, fromName string, message string, gold int, itm *items.Item) {
	msg := Message{
		FromName: fromName,
		Body:     message,
		Gold:     gold,
		Item:     itm,
		DateSent: time.Now(),
	}

	// Online: update in-memory inbox and notify.
	if u := users.GetByUserId(userId); u != nil {
		inbox := m.inboxes[userId]
		inbox = append(Inbox{msg}, inbox...)
		m.inboxes[userId] = inbox
		m.save(userId, inbox)
		u.Command(`inbox check`)
		return
	}

	// Offline: read from disk, append, write back.
	inbox := m.load(userId)
	inbox = append(Inbox{msg}, inbox...)
	m.save(userId, inbox)
}

// Inbox management helpers.

func countRead(inbox Inbox) int {
	ct := 0
	for _, msg := range inbox {
		if msg.Read {
			ct++
		}
	}
	return ct
}

func countUnread(inbox Inbox) int {
	ct := 0
	for _, msg := range inbox {
		if !msg.Read {
			ct++
		}
	}
	return ct
}

func (m *MudmailModule) inboxCommand(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {

	inbox := m.inboxes[user.UserId]

	if rest == `clear` {
		m.inboxes[user.UserId] = Inbox{}
		return true, nil
	}

	if rest == `check` {
		user.SendText(fmt.Sprintf(language.T(`Inbox.UnreadMessageWithCheck`), countUnread(inbox), countRead(inbox)))
		return true, nil
	}

	user.SendText(fmt.Sprintf(language.T(`Inbox.UnreadMessage`), countUnread(inbox), countRead(inbox)))

	if len(inbox) == 0 {
		return true, nil
	}

	border := `<ansi fg="mail-border">` + strings.Repeat(`_`, 80) + `</ansi>`
	user.SendText(border)

	for idx, msg := range inbox {

		if rest == `old` {
			if !msg.Read {
				continue
			}
		} else if msg.Read {
			continue
		}

		tplTxt, _ := templates.Process("mail/message", msg, user.UserId)
		user.SendText(tplTxt)

		user.SendText(border)

		if !msg.Read {
			if msg.Gold > 0 {
				user.Character.Bank += msg.Gold

				events.AddToQueue(events.EquipmentChange{
					UserId:     user.UserId,
					BankChange: msg.Gold,
				})
			}
			if msg.Item != nil {
				if user.Character.StoreItem(*msg.Item) {
					events.AddToQueue(events.ItemOwnership{
						UserId: user.UserId,
						Item:   *msg.Item,
						Gained: true,
					})
				}
			}
		}

		inbox[idx].Read = true
	}

	m.inboxes[user.UserId] = inbox

	user.SendText(``)
	user.SendText(language.T(`Inbox.ReadOldMessages`))
	user.SendText(language.T(`Inbox.ClearMessages`))
	user.SendText(``)

	return true, nil
}

func (m *MudmailModule) mudmailCommand(rest string, user *users.UserRecord, room *rooms.Room, flags events.EventFlag) (bool, error) {

	cmdPrompt, isNew := user.StartPrompt(`mudmail`, rest)
	if isNew {
		user.SendText(fmt.Sprintf(`Starting a new mud mail...%s`, term.CRLFStr))
	}

	msg := Message{
		DateSent: time.Now(),
	}

	question := cmdPrompt.Ask(`From name?`, []string{})
	if !question.Done {
		return true, nil
	}

	if question.Response == `` {
		user.SendText(`Some name must be provided.`)
		question.RejectResponse()
		return true, nil
	}

	msg.FromName = question.Response

	question = cmdPrompt.Ask(`Message?`, []string{})
	if !question.Done {
		return true, nil
	}

	if question.Response == `` {
		user.ClearPrompt()
		return true, nil
	}

	msg.Body = question.Response

	question = cmdPrompt.Ask(`Attach how much gold?`, []string{})
	if !question.Done {
		return true, nil
	}

	msg.Gold, _ = strconv.Atoi(question.Response)

	question = cmdPrompt.Ask(`Item name (or "none") to attach from your backpack?`, []string{})
	if !question.Done {
		return true, nil
	}

	if question.Response != `none` {
		if itemAttached, found := user.Character.FindInBackpack(question.Response); found {
			msg.Item = &itemAttached
		} else {
			user.SendText(`Could not find item: ` + question.Response)
			question.RejectResponse()
			return true, nil
		}
	}

	question = cmdPrompt.Ask(`Send this message to everyone?`, []string{`Yes`, `No`}, `No`)
	if !question.Done {
		tplTxt, _ := templates.Process("mail/message", msg, user.UserId)
		user.SendText(tplTxt)
		return true, nil
	}

	user.ClearPrompt()

	if !strings.HasPrefix(question.Response, `Y`) {
		user.SendText(`Okay! Cancelling mass mail.`)
		return true, nil
	}

	// Deliver to all online users.
	for _, u := range users.GetAllActiveUsers() {
		inbox := m.inboxes[u.UserId]
		inbox = append(Inbox{msg}, inbox...)
		m.inboxes[u.UserId] = inbox
		m.save(u.UserId, inbox)
		u.Command(`inbox check`)
	}

	// Deliver to all offline users.
	onlineIds := make(map[int]struct{})
	for _, u := range users.GetAllActiveUsers() {
		onlineIds[u.UserId] = struct{}{}
	}

	users.SearchOfflineUsers(func(u *users.UserRecord) bool {
		if _, online := onlineIds[u.UserId]; online {
			return true
		}
		inbox := m.load(u.UserId)
		inbox = append(Inbox{msg}, inbox...)
		m.save(u.UserId, inbox)
		return true
	})

	user.SendText(``)
	user.SendText(`<ansi fg="alert-5">Message SENT!</ansi>`)
	user.SendText(``)
	return true, nil
}
