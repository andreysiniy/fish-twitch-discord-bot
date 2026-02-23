import React, { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { Location } from '../../types';

type LocationDraft = Pick<Location, 'id' | 'name' | 'items_drop_rate' | 'requirements'>;

interface LocationSettingsModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialLocation: Location | null;
  onClose: () => void;
  onSave: (location: LocationDraft) => void;
  onDelete?: (locationId: string) => void;
}

const toInputValue = (value?: number) => (value === undefined ? '' : String(value));

const sanitizeLocationId = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

export const LocationSettingsModal: React.FC<LocationSettingsModalProps> = ({
  isOpen,
  mode,
  initialLocation,
  onClose,
  onSave,
  onDelete,
}) => {
  const [locationId, setLocationId] = useState('');
  const [locationName, setLocationName] = useState('');
  const [itemsDropRate, setItemsDropRate] = useState('0.1');
  const [requiredLevel, setRequiredLevel] = useState('');
  const [requiredFishStat, setRequiredFishStat] = useState('');
  const [requiredMassStat, setRequiredMassStat] = useState('');

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    if (mode === 'edit' && initialLocation) {
      setLocationId(initialLocation.id);
      setLocationName(initialLocation.name);
      setItemsDropRate(String(initialLocation.items_drop_rate));
      setRequiredLevel(toInputValue(initialLocation.requirements.level));
      setRequiredFishStat(toInputValue(initialLocation.requirements.total_fish_stat));
      setRequiredMassStat(toInputValue(initialLocation.requirements.total_mass_stat));
      return;
    }

    setLocationId('');
    setLocationName('');
    setItemsDropRate('0.1');
    setRequiredLevel('');
    setRequiredFishStat('');
    setRequiredMassStat('');
  }, [isOpen, mode, initialLocation]);

  const title = useMemo(
    () => (mode === 'create' ? 'Add Location Settings' : 'Edit Location Settings'),
    [mode],
  );

  if (!isOpen) {
    return null;
  }

  const inputClass = `w-full rounded p-2 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 border transition-all
    bg-slate-50 border-slate-200 text-slate-900 
    dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200`;
  const labelClass = 'block text-xs font-bold uppercase mb-1 text-slate-500 dark:text-slate-500';

  const parseOptionalNumber = (value: string): number | undefined => {
    if (!value.trim()) {
      return undefined;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const safeName = locationName.trim();
    const generatedId = sanitizeLocationId(locationId || safeName || 'location');
    const safeDropRate = Number(itemsDropRate);

    if (!safeName || !generatedId || !Number.isFinite(safeDropRate)) {
      return;
    }

    onSave({
      id: generatedId,
      name: safeName,
      items_drop_rate: safeDropRate,
      requirements: {
        level: parseOptionalNumber(requiredLevel),
        total_fish_stat: parseOptionalNumber(requiredFishStat),
        total_mass_stat: parseOptionalNumber(requiredMassStat),
      },
    });
  };

  const handleDelete = () => {
    if (mode !== 'edit' || !initialLocation || !onDelete) {
      return;
    }

    const confirmed = window.confirm(
      `Delete location "${initialLocation.name}" (${initialLocation.id})? This action cannot be undone.`,
    );

    if (!confirmed) {
      return;
    }

    onDelete(initialLocation.id);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-3xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden transition-colors
        bg-white border border-slate-200 
        dark:bg-slate-900 dark:border-slate-700"
      >
        <div
          className="p-5 border-b flex justify-between items-center transition-colors
          bg-white border-slate-200 
          dark:bg-slate-900 dark:border-slate-800"
        >
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">{title}</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto">
          <form id="locationSettingsForm" onSubmit={handleSubmit} className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Location ID</label>
                <input
                  type="text"
                  value={locationId}
                  disabled={mode === 'edit'}
                  onChange={e => setLocationId(e.target.value)}
                  placeholder="lake_default"
                  className={`${inputClass} ${mode === 'edit' ? 'opacity-60 cursor-not-allowed' : ''}`}
                />
              </div>
              <div>
                <label className={labelClass}>Location Name</label>
                <input
                  type="text"
                  value={locationName}
                  onChange={e => setLocationName(e.target.value)}
                  placeholder="Mystic Lake"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Items Drop Rate</label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={itemsDropRate}
                  onChange={e => setItemsDropRate(e.target.value)}
                  className={inputClass}
                />
              </div>
            </div>

            <div
              className="p-4 rounded-lg border transition-colors
              bg-slate-50 border-slate-200 
              dark:bg-slate-950/50 dark:border-slate-800/50"
            >
              <h3
                className="text-xs font-bold uppercase mb-3 flex items-center gap-2
                text-indigo-600 dark:text-indigo-400"
              >
                Requirements
              </h3>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className={labelClass}>Min Level</label>
                  <input
                    type="number"
                    min="0"
                    value={requiredLevel}
                    onChange={e => setRequiredLevel(e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>Min Total Fish</label>
                  <input
                    type="number"
                    min="0"
                    value={requiredFishStat}
                    onChange={e => setRequiredFishStat(e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>Min Total Mass</label>
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={requiredMassStat}
                    onChange={e => setRequiredMassStat(e.target.value)}
                    className={inputClass}
                  />
                </div>
              </div>
            </div>
          </form>
        </div>

        <div
          className="p-4 border-t flex items-center justify-between gap-3 rounded-b-xl transition-colors
          bg-slate-50 border-slate-200
          dark:bg-slate-900 dark:border-slate-800"
        >
          <div>
            {mode === 'edit' && (
              <button
                type="button"
                onClick={handleDelete}
                className="px-4 py-2 font-bold rounded-lg transition-colors
                  text-white bg-red-600 hover:bg-red-500
                  dark:bg-red-800 dark:hover:bg-red-700 dark:text-red-100"
              >
                Delete Location
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 font-medium transition-colors rounded-lg
                text-slate-600 hover:bg-slate-200 
                dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              form="locationSettingsForm"
              type="submit"
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-bold shadow-lg shadow-indigo-500/20 transition-all active:scale-95"
            >
              Save Location Settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
