import React from 'react';
import { DraftRewardParams, RouletteOutcomeType } from '../../../types';

interface Props {
  title: string;
  typeKey: 'roulette_reward_type' | 'roulette_penalty_type';
  massKey: 'roulette_reward_mass' | 'roulette_penalty_mass';
  percentageKey: 'roulette_reward_percentage' | 'roulette_penalty_percentage';
  durationKey: 'roulette_reward_duration' | 'roulette_penalty_duration';
  reasonKey: 'roulette_reward_reason' | 'roulette_penalty_reason';
  params: DraftRewardParams;
  onChange: (
    key: keyof DraftRewardParams,
    value: DraftRewardParams[keyof DraftRewardParams],
  ) => void;
  inputClass: string;
  labelClass: string;
}

export const RouletteOutcomeFields: React.FC<Props> = ({
  title,
  typeKey,
  massKey,
  percentageKey,
  durationKey,
  reasonKey,
  params,
  onChange,
  inputClass,
  labelClass,
}) => {
  const outcomeType = params[typeKey] as RouletteOutcomeType;

  return (
    <div className="rounded-lg border border-slate-200/80 p-3 dark:border-slate-800/80">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={labelClass}>{title} Type</label>
          <select
            value={outcomeType}
            onChange={e => onChange(typeKey, e.target.value as RouletteOutcomeType)}
            className={inputClass}
          >
            <option value="add_mass">add_mass</option>
            <option value="add_percentage_mass">add_percentage_mass</option>
            <option value="timeout">timeout</option>
          </select>
        </div>

        {outcomeType === 'add_mass' && (
          <div className="col-span-2">
            <label className={labelClass}>Mass</label>
            <input
              type="number"
              step="0.1"
              value={(params[massKey] as number | null) ?? ''}
              onChange={e => onChange(massKey, e.target.value === '' ? null : parseFloat(e.target.value))}
              className={inputClass}
            />
          </div>
        )}

        {outcomeType === 'add_percentage_mass' && (
          <div className="col-span-2">
            <label className={labelClass}>Percentage</label>
            <input
              type="number"
              step="0.01"
              value={(params[percentageKey] as number | null) ?? ''}
              onChange={e =>
                onChange(percentageKey, e.target.value === '' ? null : parseFloat(e.target.value))
              }
              className={inputClass}
            />
          </div>
        )}

        {outcomeType === 'timeout' && (
          <>
            <div>
              <label className={labelClass}>Duration</label>
              <input
                type="number"
                min="1"
                value={(params[durationKey] as number | null) ?? ''}
                onChange={e =>
                  onChange(durationKey, e.target.value === '' ? null : parseInt(e.target.value, 10))
                }
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>Reason</label>
              <input
                type="text"
                value={(params[reasonKey] as string) ?? ''}
                onChange={e => onChange(reasonKey, e.target.value)}
                className={inputClass}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
};
