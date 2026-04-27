package characters

import "github.com/GoMudEngine/GoMud/internal/items"

type Worn struct {
	Weapon  items.Item `yaml:"weapon,omitempty"`
	Offhand items.Item `yaml:"offhand,omitempty"`
	Head    items.Item `yaml:"head,omitempty"`
	Neck    items.Item `yaml:"neck,omitempty"` // legacy alias; normalized to Neck1/Neck2
	Neck1   items.Item `yaml:"neck1,omitempty"`
	Neck2   items.Item `yaml:"neck2,omitempty"`
	Body    items.Item `yaml:"body,omitempty"`
	Belt    items.Item `yaml:"belt,omitempty"` // legacy alias; normalized to Waist
	Waist   items.Item `yaml:"waist,omitempty"`
	Back    items.Item `yaml:"back,omitempty"`
	Light   items.Item `yaml:"light,omitempty"`
	Gloves  items.Item `yaml:"gloves,omitempty"`
	Ring    items.Item `yaml:"ring,omitempty"` // legacy alias; normalized to Ring1/Ring2
	Ring1   items.Item `yaml:"ring1,omitempty"`
	Ring2   items.Item `yaml:"ring2,omitempty"`
	Wrist1  items.Item `yaml:"wrist1,omitempty"`
	Wrist2  items.Item `yaml:"wrist2,omitempty"`
	Legs    items.Item `yaml:"legs,omitempty"`
	Feet    items.Item `yaml:"feet,omitempty"`
}

func (w *Worn) StatMod(stat ...string) int {

	return w.Weapon.StatMod(stat...) +
		w.Offhand.StatMod(stat...) +
		w.Head.StatMod(stat...) +
		w.Neck.StatMod(stat...) +
		w.Neck1.StatMod(stat...) +
		w.Neck2.StatMod(stat...) +
		w.Body.StatMod(stat...) +
		w.Belt.StatMod(stat...) +
		w.Waist.StatMod(stat...) +
		w.Back.StatMod(stat...) +
		w.Light.StatMod(stat...) +
		w.Gloves.StatMod(stat...) +
		w.Ring.StatMod(stat...) +
		w.Ring1.StatMod(stat...) +
		w.Ring2.StatMod(stat...) +
		w.Wrist1.StatMod(stat...) +
		w.Wrist2.StatMod(stat...) +
		w.Legs.StatMod(stat...) +
		w.Feet.StatMod(stat...)
}

func (w *Worn) EnableAll() {
	if w.Weapon.ItemId < 0 {
		w.Weapon = items.Item{}
	}
	if w.Offhand.ItemId < 0 {
		w.Offhand = items.Item{}
	}
	if w.Head.ItemId < 0 {
		w.Head = items.Item{}
	}
	if w.Neck.ItemId < 0 {
		w.Neck = items.Item{}
	}
	if w.Neck1.ItemId < 0 {
		w.Neck1 = items.Item{}
	}
	if w.Neck2.ItemId < 0 {
		w.Neck2 = items.Item{}
	}
	if w.Body.ItemId < 0 {
		w.Body = items.Item{}
	}
	if w.Belt.ItemId < 0 {
		w.Belt = items.Item{}
	}
	if w.Waist.ItemId < 0 {
		w.Waist = items.Item{}
	}
	if w.Back.ItemId < 0 {
		w.Back = items.Item{}
	}
	if w.Light.ItemId < 0 {
		w.Light = items.Item{}
	}
	if w.Gloves.ItemId < 0 {
		w.Gloves = items.Item{}
	}
	if w.Ring.ItemId < 0 {
		w.Ring = items.Item{}
	}
	if w.Ring1.ItemId < 0 {
		w.Ring1 = items.Item{}
	}
	if w.Ring2.ItemId < 0 {
		w.Ring2 = items.Item{}
	}
	if w.Wrist1.ItemId < 0 {
		w.Wrist1 = items.Item{}
	}
	if w.Wrist2.ItemId < 0 {
		w.Wrist2 = items.Item{}
	}
	if w.Legs.ItemId < 0 {
		w.Legs = items.Item{}
	}
	if w.Feet.ItemId < 0 {
		w.Feet = items.Item{}
	}

	// Normalize legacy slots into canonical multi-slot equipment.
	if w.Neck.ItemId > 0 {
		if w.Neck1.ItemId == 0 {
			w.Neck1 = w.Neck
		} else if w.Neck2.ItemId == 0 {
			w.Neck2 = w.Neck
		}
		w.Neck = items.Item{}
	}
	if w.Ring.ItemId > 0 {
		if w.Ring1.ItemId == 0 {
			w.Ring1 = w.Ring
		} else if w.Ring2.ItemId == 0 {
			w.Ring2 = w.Ring
		}
		w.Ring = items.Item{}
	}
	if w.Belt.ItemId > 0 {
		if w.Waist.ItemId == 0 {
			w.Waist = w.Belt
		}
		w.Belt = items.Item{}
	}
}

func (w *Worn) GetAllItems() []items.Item {
	iList := []items.Item{}
	if w.Weapon.ItemId > 0 {
		iList = append(iList, w.Weapon)
	}
	if w.Offhand.ItemId > 0 {
		iList = append(iList, w.Offhand)
	}
	if w.Head.ItemId > 0 {
		iList = append(iList, w.Head)
	}
	if w.Neck.ItemId > 0 {
		iList = append(iList, w.Neck)
	}
	if w.Neck1.ItemId > 0 {
		iList = append(iList, w.Neck1)
	}
	if w.Neck2.ItemId > 0 {
		iList = append(iList, w.Neck2)
	}
	if w.Body.ItemId > 0 {
		iList = append(iList, w.Body)
	}
	if w.Belt.ItemId > 0 {
		iList = append(iList, w.Belt)
	}
	if w.Waist.ItemId > 0 {
		iList = append(iList, w.Waist)
	}
	if w.Back.ItemId > 0 {
		iList = append(iList, w.Back)
	}
	if w.Light.ItemId > 0 {
		iList = append(iList, w.Light)
	}
	if w.Gloves.ItemId > 0 {
		iList = append(iList, w.Gloves)
	}
	if w.Ring.ItemId > 0 {
		iList = append(iList, w.Ring)
	}
	if w.Ring1.ItemId > 0 {
		iList = append(iList, w.Ring1)
	}
	if w.Ring2.ItemId > 0 {
		iList = append(iList, w.Ring2)
	}
	if w.Wrist1.ItemId > 0 {
		iList = append(iList, w.Wrist1)
	}
	if w.Wrist2.ItemId > 0 {
		iList = append(iList, w.Wrist2)
	}
	if w.Legs.ItemId > 0 {
		iList = append(iList, w.Legs)
	}
	if w.Feet.ItemId > 0 {
		iList = append(iList, w.Feet)
	}
	return iList
}

func GetAllSlotTypes() []string {
	return []string{
		string(items.Weapon),
		string(items.Offhand),
		string(items.Head),
		string(items.Neck1),
		string(items.Neck2),
		string(items.Body),
		string(items.Waist),
		string(items.Back),
		string(items.Light),
		string(items.Gloves),
		string(items.Ring1),
		string(items.Ring2),
		string(items.Wrist1),
		string(items.Wrist2),
		string(items.Legs),
		string(items.Feet),
	}
}
