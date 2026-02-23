import React from 'react';
import { Trash2, Package, Skull, Clock } from 'lucide-react';
import { REWARD_TYPES } from './constants';
import { Reward, RewardType, RouletteOutcome } from '../../types';

const RewardTypeBadge = ({ type }: { type: RewardType }) => {
  const def = REWARD_TYPES.find(t => t.id === type) || {
    icon: Package,
    color: 'text-slate-500',
    bg: 'bg-slate-100',
  };
  const Icon = def.icon;

  return (
    <div className={`p-2 rounded-lg inline-flex ${def.bg} ${def.color}`}>
      <Icon className="w-5 h-5" />
    </div>
  );
};

const renderRouletteOutcome = (label: string, outcome?: RouletteOutcome) => {
  if (!outcome) {
    return null;
  }

  if (outcome.type === 'add_mass') {
    return (
      <span className="text-slate-600 dark:text-slate-400">
        {label}: add_mass {outcome.mass ?? 0}
      </span>
    );
  }

  if (outcome.type === 'add_percentage_mass') {
    return (
      <span className="text-slate-600 dark:text-slate-400">
        {label}: add_percentage_mass {((outcome.percentage ?? 0) * 100).toFixed(0)}%
      </span>
    );
  }

  return (
    <span className="text-slate-600 dark:text-slate-400">
      {label}: timeout {outcome.duration ?? 0}s{outcome.reason ? ` (${outcome.reason})` : ''}
    </span>
  );
};

const RewardParamsDisplay = ({ reward }: { reward: Reward }) => {
  switch (reward.type) {
    case 'fish':
      return (
        <div className="flex flex-col gap-0.5">
          {(reward.min_mass !== undefined || reward.max_mass !== undefined) && (
            <span className="text-blue-600 dark:text-blue-400">
              Range: {reward.min_mass ?? 0}-{reward.max_mass ?? 0}kg
            </span>
          )}
          {reward.fixed_mass !== undefined && (
            <span className="text-emerald-600 dark:text-emerald-400">
              Fixed: {reward.fixed_mass}kg
            </span>
          )}
          {reward.percentage !== undefined && (
            <span className="text-cyan-600 dark:text-cyan-400">
              Percentage: {(reward.percentage * 100).toFixed(0)}%
            </span>
          )}
        </div>
      );
    case 'russian_roulette':
      return (
        <div className="flex flex-col gap-0.5">
          <span className="text-red-600 dark:text-red-400 flex items-center gap-1">
            <Skull className="w-3 h-3" /> {reward.bullets}/{reward.chambers}
          </span>
          {reward.safe_message && (
            <span className="text-slate-600 dark:text-slate-400">safe: {reward.safe_message}</span>
          )}
          {reward.shot_message && (
            <span className="text-slate-600 dark:text-slate-400">shot: {reward.shot_message}</span>
          )}
          {renderRouletteOutcome('Reward', reward.reward)}
          {renderRouletteOutcome('Penalty', reward.penalty)}
        </div>
      );
    case 'timeout':
      return (
        <div className="flex flex-col gap-0.5">
          <span className="text-orange-600 dark:text-orange-400 flex items-center gap-1">
            <Clock className="w-3 h-3" /> {reward.duration}s
          </span>
          {reward.reason && (
            <span className="text-slate-600 dark:text-slate-400">{reward.reason}</span>
          )}
        </div>
      );
    case 'robbery':
      return (
        <div className="flex flex-col gap-0.5">
          {reward.percentage !== undefined && (
            <span className="text-purple-600 dark:text-purple-400">
              Steal: {(reward.percentage * 100).toFixed(0)}%
            </span>
          )}
          {reward.mass !== undefined && (
            <span className="text-purple-600 dark:text-purple-400">Mass: {reward.mass}</span>
          )}
        </div>
      );
    default:
      return <span className="text-slate-400 dark:text-slate-600">-</span>;
  }
};

interface LootTableProps {
  rewards: Reward[];
  onDelete: (id: number) => void;
}

export const LootTable: React.FC<LootTableProps> = ({ rewards, onDelete }) => {
  if (!rewards || rewards.length === 0) {
    return (
      <div
        className="p-12 text-center border-t 
        border-slate-200 text-slate-500 
        dark:border-slate-800 dark:text-slate-600"
      >
        <Package className="w-12 h-12 mx-auto mb-3 opacity-20" />
        No rewards configured for this location.
      </div>
    );
  }

  const totalWeight = rewards.reduce((sum, r) => sum + r.weight, 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr
            className="text-xs uppercase tracking-wider border-b
            bg-slate-50/50 border-slate-200/50 text-slate-500 
            dark:bg-slate-950/30 dark:border-slate-800/50 dark:text-slate-400"
          >
            <th className="p-4 font-semibold">Reward Type</th>
            <th className="p-4 font-semibold">Config</th>
            <th className="p-4 font-semibold text-right">Weight</th>
            <th className="p-4 font-semibold text-right">Chance</th>
            <th className="p-4 font-semibold text-center">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200/50 dark:divide-slate-800/50">
          {rewards.map(reward => {
            const chance = totalWeight > 0 ? ((reward.weight / totalWeight) * 100).toFixed(1) : '0.0';
            return (
              <tr
                key={reward.id}
                className="transition-colors group
                hover:bg-slate-100/50 dark:hover:bg-slate-800/40"
              >
                <td className="p-4">
                  <div className="flex items-center gap-3">
                    <RewardTypeBadge type={reward.type} />
                    <div>
                      <div
                        className="font-bold text-sm capitalize
                        text-slate-800 dark:text-slate-200"
                      >
                        {reward.name || reward.type.replace('_', ' ')}
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-500">
                        type: {reward.type.replace('_', ' ')}
                        {reward.xp !== undefined ? ` | xp: ${reward.xp}` : ''}
                      </div>
                      <div
                        className="text-xs truncate max-w-[260px]
                        text-slate-500 dark:text-slate-500"
                        title={reward.message}
                      >
                        {reward.message || '-'}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="p-4 text-xs font-mono">
                  <RewardParamsDisplay reward={reward} />
                </td>
                <td
                  className="p-4 text-right font-mono text-sm
                  text-slate-600 dark:text-slate-400"
                >
                  {reward.weight}
                </td>
                <td
                  className="p-4 text-right font-mono text-sm font-bold
                  text-slate-800 dark:text-slate-300"
                >
                  {chance}%
                </td>
                <td className="p-4 text-center">
                  <button
                    onClick={() => onDelete(reward.id)}
                    className="p-2 rounded-lg transition-all
                        text-slate-400 hover:text-red-700 hover:bg-red-50 
                        dark:text-slate-500 dark:hover:text-red-400 dark:hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
