export type RewardType = 'fish' | 'russian_roulette' | 'timeout' | 'robbery' | 'nothing';

export interface BaseReward {
  id: number;
  type: RewardType;
  weight: number;
  name?: string;
  xp?: number;
  message: string;
}

export interface FishReward extends BaseReward {
  type: 'fish';
  min_mass?: number;
  max_mass?: number;
  fixed_mass?: number;
  percentage?: number;
}

export type RouletteOutcomeType = 'add_mass' | 'add_percentage_mass' | 'timeout';

export interface RouletteOutcome {
  type: RouletteOutcomeType;
  mass?: number;
  percentage?: number;
  duration?: number;
  reason?: string;
}

export interface RouletteReward extends BaseReward {
  type: 'russian_roulette';
  bullets: number;
  chambers: number;
  safe_message?: string;
  shot_message?: string;
  reward?: RouletteOutcome;
  penalty?: RouletteOutcome;
}

export interface TimeoutReward extends BaseReward {
  type: 'timeout';
  duration: number;
  reason: string;
}

export interface RobberyReward extends BaseReward {
  type: 'robbery';
  percentage?: number;
  mass?: number;
}

export interface NothingReward extends BaseReward {
  type: 'nothing';
}

export type Reward = FishReward | RouletteReward | TimeoutReward | RobberyReward | NothingReward;

export interface Location {
  id: string;
  name: string;
  items_drop_rate: number;
  requirements: {
    level?: number;
    total_fish_stat?: number;
    total_mass_stat?: number;
  };
  rewards: Reward[];
}

export interface DraftRewardParams {
  xp: number | null;
  min_mass: number | null;
  max_mass: number | null;
  fish_fixed_mass: number | null;
  fish_percentage: number | null;
  duration: number | null;
  reason: string;
  bullets: number;
  chambers: number;
  robbery_percentage: number | null;
  robbery_mass: number | null;
  safe_message: string;
  shot_message: string;
  roulette_reward_type: RouletteOutcomeType;
  roulette_reward_mass: number | null;
  roulette_reward_percentage: number | null;
  roulette_reward_duration: number | null;
  roulette_reward_reason: string;
  roulette_penalty_type: RouletteOutcomeType;
  roulette_penalty_mass: number | null;
  roulette_penalty_percentage: number | null;
  roulette_penalty_duration: number | null;
  roulette_penalty_reason: string;
}

export interface GameParamsConfig {
  xp_base: number;
  xp_exponent: number;
  sell_max_bonus: number;
  sell_mid_level: number;
  sell_rate: number;
  buy_rate: number;
  rob_min_chance: number;
  rob_max_chance: number;
  rob_resist_divisor: number;
  rob_loss_divisor: number;
  rob_base_chance: number;
  fishing_cooldown: number;
  subs_fishing_cooldown: number;
}

export interface EventModifiers {
  luck_mult?: number;
  xp_mult?: number;
  cd_reduction?: number;
  bonus_mass?: number;
  [key: string]: number | undefined;
}

export interface FishingEvent {
  id: number;
  event_title: string;
  is_active: boolean;
  modifiers: EventModifiers;
  override_loot_pool?: string | null;
}
