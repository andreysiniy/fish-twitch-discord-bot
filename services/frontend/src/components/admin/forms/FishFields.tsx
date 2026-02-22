import React from 'react';
import { DraftRewardParams } from '../../../types';

interface Props {
  params: DraftRewardParams;
  onChange: (
    key: keyof DraftRewardParams,
    value: DraftRewardParams[keyof DraftRewardParams],
  ) => void;
  inputClass: string;
  labelClass: string;
}

export const FishFields: React.FC<Props> = ({ params, onChange, inputClass, labelClass }) => (
  <div className="grid grid-cols-2 gap-4 animate-in fade-in slide-in-from-top-2 duration-200">
    <div>
      <label className={labelClass}>Min Mass (kg)</label>
      <input 
        type="number" step="0.1" 
        value={params.min_mass ?? ''} 
        onChange={e => onChange('min_mass', e.target.value === '' ? null : parseFloat(e.target.value))} 
        className={inputClass}
      />
    </div>
    <div>
      <label className={labelClass}>Max Mass (kg)</label>
      <input 
        type="number" step="0.1" 
        value={params.max_mass ?? ''} 
        onChange={e => onChange('max_mass', e.target.value === '' ? null : parseFloat(e.target.value))} 
        className={inputClass}
      />
    </div>
    <div>
      <label className={labelClass}>Fixed Mass (kg)</label>
      <input
        type="number"
        step="0.1"
        value={params.fish_fixed_mass ?? ''}
        onChange={e => onChange('fish_fixed_mass', e.target.value === '' ? null : parseFloat(e.target.value))}
        className={inputClass}
      />
    </div>
    <div>
      <label className={labelClass}>Percentage</label>
      <input
        type="number"
        step="0.01"
        value={params.fish_percentage ?? ''}
        onChange={e => onChange('fish_percentage', e.target.value === '' ? null : parseFloat(e.target.value))}
        className={inputClass}
      />
    </div>
  </div>
);
