import React from 'react';
import { DraftRewardParams } from '../../../types';
import { RouletteOutcomeFields } from './RouletteOutcomeFields';

interface Props {
  params: DraftRewardParams;
  onChange: (
    key: keyof DraftRewardParams,
    value: DraftRewardParams[keyof DraftRewardParams],
  ) => void;
  inputClass: string;
  labelClass: string;
}

export const RouletteFields: React.FC<Props> = ({ params, onChange, inputClass, labelClass }) => (
  <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
    <div className="grid grid-cols-2 gap-4">
      <div>
        <label className={labelClass}>Bullets</label>
        <input
          type="number"
          min="1"
          max="6"
          value={params.bullets}
          onChange={e => onChange('bullets', parseInt(e.target.value, 10))}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Chambers</label>
        <input
          type="number"
          min="1"
          max="100"
          value={params.chambers}
          onChange={e => onChange('chambers', parseInt(e.target.value, 10))}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Safe Message</label>
        <input
          type="text"
          value={params.safe_message}
          onChange={e => onChange('safe_message', e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Shot Message</label>
        <input
          type="text"
          value={params.shot_message}
          onChange={e => onChange('shot_message', e.target.value)}
          className={inputClass}
        />
      </div>
    </div>

    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <RouletteOutcomeFields
        title="Reward"
        typeKey="roulette_reward_type"
        massKey="roulette_reward_mass"
        percentageKey="roulette_reward_percentage"
        durationKey="roulette_reward_duration"
        reasonKey="roulette_reward_reason"
        params={params}
        onChange={onChange}
        inputClass={inputClass}
        labelClass={labelClass}
      />
      <RouletteOutcomeFields
        title="Penalty"
        typeKey="roulette_penalty_type"
        massKey="roulette_penalty_mass"
        percentageKey="roulette_penalty_percentage"
        durationKey="roulette_penalty_duration"
        reasonKey="roulette_penalty_reason"
        params={params}
        onChange={onChange}
        inputClass={inputClass}
        labelClass={labelClass}
      />
    </div>
  </div>
);
