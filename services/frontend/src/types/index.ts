export type RewardType = 'fish' | 'russian_roulette' | 'timeout' | 'robbery' | 'nothing';

export interface BaseReward {
  id: number;
  type: RewardType;
  weight: number;
  message: string;
}

export interface FishReward extends BaseReward {
  type: 'fish';
  min_mass?: number;
  max_mass?: number;
  fixed_mass?: number;
}

export interface RouletteReward extends BaseReward {
  type: 'russian_roulette';
  bullets: number;
  chambers: number;
  penalty?: {
      type: string;
      duration?: number;
      reason?: string;
  };
}

export interface TimeoutReward extends BaseReward {
  type: 'timeout';
  duration: number;
  reason: string;
}

export interface RobberyReward extends BaseReward {
  type: 'robbery';
  percentage: number;
}

export interface NothingReward extends BaseReward {
  type: 'nothing';
}

export type Reward = FishReward | RouletteReward | TimeoutReward | RobberyReward | NothingReward;

export interface Location {
  id: string;
  name: string;
  rewards: Reward[];
}

export interface DraftRewardParams {
  min_mass: number;
  max_mass: number;
  duration: number;
  reason: string;
  bullets: number;
  chambers: number;
  percentage: number;
}