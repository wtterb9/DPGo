package usercommands

import (
	"testing"

	"github.com/GoMudEngine/GoMud/internal/items"
)

func TestIsAutoGoldServiceItem(t *testing.T) {
	tests := []struct {
		name string
		item items.Item
		want bool
	}{
		{
			name: "coin pile service converts to gold",
			item: items.Item{
				ItemId: 1,
				Spec: &items.ItemSpec{
					Type:  items.Service,
					Name:  "a huge pile of gold coins",
					Value: 250,
				},
			},
			want: true,
		},
		{
			name: "hoard service converts to gold",
			item: items.Item{
				ItemId: 2,
				Spec: &items.ItemSpec{
					Type:  items.Service,
					Name:  "a hoard of gold coins",
					Value: 500,
				},
			},
			want: true,
		},
		{
			name: "mountain service converts to gold",
			item: items.Item{
				ItemId: 6,
				Spec: &items.ItemSpec{
					Type:  items.Service,
					Name:  "a mountain of gold and gems",
					Value: 1000,
				},
			},
			want: true,
		},
		{
			name: "golden portal service does not convert",
			item: items.Item{
				ItemId: 3,
				Spec: &items.ItemSpec{
					Type:  items.Service,
					Name:  "a shimmering golden portal",
					Value: 1,
				},
			},
			want: false,
		},
		{
			name: "coin object does not auto convert",
			item: items.Item{
				ItemId: 4,
				Spec: &items.ItemSpec{
					Type:  items.Object,
					Name:  "a single gold coin",
					Value: 1,
				},
			},
			want: false,
		},
		{
			name: "service item without value does not convert",
			item: items.Item{
				ItemId: 5,
				Spec: &items.ItemSpec{
					Type:  items.Service,
					Name:  "a large pile of gold",
					Value: 0,
				},
			},
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isAutoGoldServiceItem(tt.item)
			if got != tt.want {
				t.Fatalf("isAutoGoldServiceItem() = %v, want %v", got, tt.want)
			}
		})
	}
}

