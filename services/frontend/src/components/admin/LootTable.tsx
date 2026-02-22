import React from 'react';
import { Trash2, Package, Skull, Clock } from 'lucide-react';
import { REWARD_TYPES } from './constants';
import { Reward, RewardType } from '../../types';

const RewardTypeBadge = ({ type }: { type: RewardType }) => {
  const def = REWARD_TYPES.find(t => t.id === type) || { icon: Package, color: 'text-slate-500', bg: 'bg-slate-100' };
  const Icon = def.icon;
  
  return (
    <div className={`p-2 rounded-lg inline-flex ${def.bg} ${def.color}`}>
      <Icon className="w-5 h-5" />
    </div>
  );
};

const RewardParamsDisplay = ({ reward }: { reward: Reward }) => {
  switch (reward.type) {
    case 'fish':
      return reward.fixed_mass 
        ? <span className="text-emerald-600 dark:text-emerald-400">Fixed: {reward.fixed_mass}kg</span> 
        : <span className="text-blue-600 dark:text-blue-400">Range: {reward.min_mass}-{reward.max_mass}kg</span>;
    case 'russian_roulette':
      return <span className="text-red-600 dark:text-red-400 flex items-center gap-1"><Skull className="w-3 h-3"/> {reward.bullets}/{reward.chambers}</span>;
    case 'timeout':
      return <span className="text-orange-600 dark:text-orange-400 flex items-center gap-1"><Clock className="w-3 h-3"/> {reward.duration}s</span>;
    case 'robbery':
      return <span className="text-purple-600 dark:text-purple-400">Steal: {(reward.percentage * 100).toFixed(0)}%</span>;
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
      <div className="p-12 text-center border-t 
        border-slate-200 text-slate-500 
        dark:border-slate-800 dark:text-slate-600"
      >
        <Package className="w-12 h-12 mx-auto mb-3 opacity-20" />
        No events configured for this location.
      </div>
    );
  }

  const totalWeight = rewards.reduce((sum, r) => sum + r.weight, 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="text-xs uppercase tracking-wider border-b
            bg-slate-50/50 border-slate-200/50 text-slate-500 
            dark:bg-slate-950/30 dark:border-slate-800/50 dark:text-slate-400"
          >
            <th className="p-4 font-semibold">Event Type</th>
            <th className="p-4 font-semibold">Config</th>
            <th className="p-4 font-semibold text-right">Weight</th>
            <th className="p-4 font-semibold text-right">Chance</th>
            <th className="p-4 font-semibold text-center">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200/50 dark:divide-slate-800/50">
          {rewards.map((reward) => {
            const chance = totalWeight > 0 ? ((reward.weight / totalWeight) * 100).toFixed(1) : '0.0';
            return (
              <tr key={reward.id} className="transition-colors group
                hover:bg-slate-100/50 dark:hover:bg-slate-800/40"
              >
                <td className="p-4">
                  <div className="flex items-center gap-3">
                    <RewardTypeBadge type={reward.type} />
                    <div>
                      <div className="font-bold text-sm capitalize
                        text-slate-800 dark:text-slate-200"
                      >
                        {reward.type.replace('_', ' ')}
                      </div>
                      <div className="text-xs truncate max-w-[200px]
                        text-slate-500 dark:text-slate-500" 
                        title={reward.message}
                      >
                        {reward.message}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="p-4 text-xs font-mono">
                  <RewardParamsDisplay reward={reward} />
                </td>
                <td className="p-4 text-right font-mono text-sm
                  text-slate-600 dark:text-slate-400"
                >
                  {reward.weight}
                </td>
                <td className="p-4 text-right font-mono text-sm font-bold
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