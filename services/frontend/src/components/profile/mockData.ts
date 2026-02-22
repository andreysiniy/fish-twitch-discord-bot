import type { UserProfile } from './types';

export const LOCATION_BG: Record<string, string> = {
  lake_default: 'https://images.unsplash.com/photo-1506477331477-33d5d8b3dc85?auto=format&fit=crop&q=80',
  ocean_deep: 'https://images.unsplash.com/photo-1498036882173-b41c28a8ba34?auto=format&fit=crop&q=80',
  default: 'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&q=80',
};

export const MOCK_PROFILE: UserProfile = {
  username: 'TwitchFisher',
  level: 12,
  current_xp: 850,
  xp_to_next_level: 1200,
  balance_se: 4500,
  current_mass: 14.5,
  total_mass_stat: 1240.5,
  total_fish_stat: 342,
  rank: 5,
  location: 'Mystic Lake',
  location_id: 'lake_default',
  stats: {
    luck_bonus: 0.15,
    resist_bonus: 0.05,
    xp_bonus_pct: 0.1,
  },
  inventory: {
    max_slots: 20,
    equipped_rod_slot: 1,
    items: [
      {
        slot_id: 1,
        item_id: 'rod_beginner',
        name: 'Old Bamboo Rod',
        type: 'rod',
        rarity: 'common',
        quantity: 1,
        image_url: 'https://cdn-icons-png.flaticon.com/512/3576/3576924.png',
        stats: { luck_bonus: 0.05 },
        description: 'A simple rod for beginners.',
      },
      {
        slot_id: 2,
        item_id: 'fish_carp',
        name: 'Common Carp',
        type: 'fish',
        rarity: 'common',
        quantity: 5,
        image_url: 'https://cdn-icons-png.flaticon.com/512/1998/1998610.png',
        description: 'Just a regular fish.',
      },
      {
        slot_id: 3,
        item_id: 'fish_golden',
        name: 'Golden Koi',
        type: 'fish',
        rarity: 'legendary',
        quantity: 1,
        image_url: 'https://cdn-icons-png.flaticon.com/512/2970/2970078.png',
        description: 'Shines brightly in the sun.',
      },
    ],
  },
};
