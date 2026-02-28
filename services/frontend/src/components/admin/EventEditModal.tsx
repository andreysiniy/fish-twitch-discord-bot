import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { FishingEvent } from '../../types';

type EventDraft = Omit<FishingEvent, 'id'>;

interface EventEditModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialEvent: FishingEvent | null;
  onClose: () => void;
  onSave: (event: EventDraft) => void;
}

const DEFAULT_DRAFT: EventDraft = {
  event_title: '',
  is_active: false,
  modifiers: {
    luck_mult: 1,
    xp_mult: 1,
    cd_reduction: 0,
    bonus_mass: 0,
  },
  override_loot_pool: '',
};

export const EventEditModal: React.FC<EventEditModalProps> = ({
  isOpen,
  mode,
  initialEvent,
  onClose,
  onSave,
}) => {
  const [draft, setDraft] = useState<EventDraft>(DEFAULT_DRAFT);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    if (mode === 'edit' && initialEvent) {
      setDraft({
        event_title: initialEvent.event_title,
        is_active: initialEvent.is_active,
        modifiers: {
          luck_mult: initialEvent.modifiers.luck_mult ?? 1,
          xp_mult: initialEvent.modifiers.xp_mult ?? 1,
          cd_reduction: initialEvent.modifiers.cd_reduction ?? 0,
          bonus_mass: initialEvent.modifiers.bonus_mass ?? 0,
        },
        override_loot_pool: initialEvent.override_loot_pool ?? '',
      });
      return;
    }

    setDraft(DEFAULT_DRAFT);
  }, [isOpen, mode, initialEvent]);

  if (!isOpen) {
    return null;
  }

  const inputClass = `w-full rounded p-2 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 border transition-all
    bg-slate-50 border-slate-200 text-slate-900 
    dark:bg-slate-950 dark:border-slate-800 dark:text-slate-200`;
  const labelClass = 'block text-xs font-bold uppercase mb-1 text-slate-500 dark:text-slate-500';

  const handleModifierChange = (
    key: 'luck_mult' | 'xp_mult' | 'cd_reduction' | 'bonus_mass',
    value: string,
  ) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      return;
    }

    setDraft(prev => ({
      ...prev,
      modifiers: {
        ...prev.modifiers,
        [key]: parsed,
      },
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const title = draft.event_title.trim();
    if (!title) {
      return;
    }

    onSave({
      event_title: title,
      is_active: draft.is_active,
      modifiers: {
        luck_mult: draft.modifiers.luck_mult ?? 1,
        xp_mult: draft.modifiers.xp_mult ?? 1,
        cd_reduction: draft.modifiers.cd_reduction ?? 0,
        bonus_mass: draft.modifiers.bonus_mass ?? 0,
      },
      override_loot_pool: draft.override_loot_pool?.trim() || null,
    });
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
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">
            {mode === 'create' ? 'Add Event' : 'Edit Event'}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto">
          <form id="eventEditForm" onSubmit={handleSubmit} className="space-y-5">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Event Title</label>
                <input
                  type="text"
                  value={draft.event_title}
                  onChange={e => setDraft(prev => ({ ...prev, event_title: e.target.value }))}
                  placeholder="Golden Rush"
                  className={inputClass}
                  required
                />
              </div>
              <div>
                <label className={labelClass}>Override Loot Pool</label>
                <input
                  type="text"
                  value={draft.override_loot_pool ?? ''}
                  onChange={e => setDraft(prev => ({ ...prev, override_loot_pool: e.target.value }))}
                  placeholder="default"
                  className={inputClass}
                />
              </div>
            </div>

            <div className="p-4 rounded-lg border bg-slate-50 border-slate-200 dark:bg-slate-950/50 dark:border-slate-800/50">
              <h3 className="text-xs font-bold uppercase mb-3 text-indigo-600 dark:text-indigo-400">
                Modifiers
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={labelClass}>luck_mult</label>
                  <input
                    type="number"
                    step="0.01"
                    value={draft.modifiers.luck_mult ?? 1}
                    onChange={e => handleModifierChange('luck_mult', e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>xp_mult</label>
                  <input
                    type="number"
                    step="0.01"
                    value={draft.modifiers.xp_mult ?? 1}
                    onChange={e => handleModifierChange('xp_mult', e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>cd_reduction</label>
                  <input
                    type="number"
                    step="0.01"
                    value={draft.modifiers.cd_reduction ?? 0}
                    onChange={e => handleModifierChange('cd_reduction', e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>bonus_mass</label>
                  <input
                    type="number"
                    step="0.01"
                    value={draft.modifiers.bonus_mass ?? 0}
                    onChange={e => handleModifierChange('bonus_mass', e.target.value)}
                    className={inputClass}
                  />
                </div>
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={draft.is_active}
                onChange={e => setDraft(prev => ({ ...prev, is_active: e.target.checked }))}
                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              Event is active
            </label>
          </form>
        </div>

        <div
          className="p-4 border-t flex justify-end gap-3 rounded-b-xl transition-colors
          bg-slate-50 border-slate-200
          dark:bg-slate-900 dark:border-slate-800"
        >
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
            form="eventEditForm"
            type="submit"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-bold shadow-lg shadow-indigo-500/20 transition-all active:scale-95"
          >
            Save Event
          </button>
        </div>
      </div>
    </div>
  );
};
