import React from 'react';
import { DraftRewardParams } from '../../../types';

interface Props {
  params: DraftRewardParams;
  onChange: (key: keyof DraftRewardParams, value: any) => void;
  inputClass: string;
  labelClass: string;
}

export const TimeoutFields: React.FC<Props> = ({ params, onChange, inputClass, labelClass }) => (
  <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
    <div>
      <label className={labelClass}>Duration (seconds)</label>
      <input 
        type="number" min="1"
        value={params.duration} 
        onChange={e => onChange('duration', parseInt(e.target.value))} 
        className={inputClass}
      />
    </div>
    <div>
      <label className={labelClass}>Reason</label>
      <input 
        type="text" 
        value={params.reason} 
        onChange={e => onChange('reason', e.target.value)} 
        placeholder="e.g. Bad luck"
        className={inputClass}
      />
    </div>
  </div>
);