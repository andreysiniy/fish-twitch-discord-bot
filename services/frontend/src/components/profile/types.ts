export type Rarity = 'common' | 'rare' | 'epic' | 'legendary';

export interface ItemStats {
  luck_bonus?: number;
  resist_bonus?: number;
  xp_bonus_pct?: number;
}

export interface InventoryItem {
  slot_id: number;
  item_id: string;
  name: string;
  type: 'rod' | 'fish' | 'trash' | 'chest';
  rarity: Rarity;
  quantity: number;
  image_url: string;
  description: string;
  stats?: ItemStats;
}

export interface UserInventory {
  max_slots: number;
  equipped_rod_slot: number | null;
  items: InventoryItem[];
}

export interface UserStats {
  luck_bonus: number;
  resist_bonus: number;
  xp_bonus_pct: number;
}

export interface UserProfile {
  username: string;
  level: number;
  current_xp: number;
  xp_to_next_level: number;
  balance_se: number;
  current_mass: number;
  total_mass_stat: number;
  total_fish_stat: number;
  rank: number;
  location: string;
  location_id: string;
  stats: UserStats;
  inventory: UserInventory;
}
