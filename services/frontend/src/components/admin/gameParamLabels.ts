import { GameParamsConfig } from '../../types';

export const GAME_PARAM_LABELS: Record<keyof GameParamsConfig, string> = {
  xp_base: 'Base XP',
  xp_exponent: 'XP Growth Exponent',
  sell_max_bonus: 'Max Sell Bonus Multiplier',
  sell_mid_level: 'Sell Bonus Mid Level',
  sell_rate: 'Sell Rate (points per 1kg)',
  buy_rate: 'Buy Rate (points per 1kg)',
  rob_min_chance: 'Robbery Min Chance',
  rob_max_chance: 'Robbery Max Chance',
  rob_resist_divisor: 'Robbery Resistance Divisor',
  rob_loss_divisor: 'Robbery Loss Divisor',
  rob_base_chance: 'Robbery Base Chance',
  fishing_cooldown: 'Fishing Cooldown (seconds)',
  subs_fishing_cooldown: 'Subscribers Fishing Cooldown (seconds)',
};
