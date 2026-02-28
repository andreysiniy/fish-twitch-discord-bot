import React, { useMemo, useState } from 'react';
import { CalendarDays, Pencil, Plus, Save, Trash2 } from 'lucide-react';
import { EventEditModal } from './components/admin/EventEditModal';
import { FishingEvent } from './types';

const MOCK_EVENTS: FishingEvent[] = [
  {
    id: 1,
    event_title: 'Golden Rush',
    modifiers: {
      luck_mult: 1.5,
      xp_mult: 2.0,
      cd_reduction: 0.2,
      bonus_mass: 0.2,
    },
    is_active: false,
    override_loot_pool: null,
  },
  {
    id: 2,
    event_title: 'Weekend Madness',
    modifiers: {
      luck_mult: 2.0,
      xp_mult: 1.25,
      cd_reduction: 0.35,
      bonus_mass: 0.3,
    },
    is_active: true,
    override_loot_pool: null,
  },
  {
    id: 3,
    event_title: 'Night Fishing',
    modifiers: {
      luck_mult: 1.1,
      xp_mult: 1.4,
      cd_reduction: 0.1,
      bonus_mass: 0.05,
    },
    is_active: false,
    override_loot_pool: 'default',
  },
];

const ActiveToggle: React.FC<{ checked: boolean; onChange: (next: boolean) => void }> = ({
  checked,
  onChange,
}) => (
  <button
    onClick={() => onChange(!checked)}
    className={`relative w-12 h-6 rounded-full transition-colors ${
      checked ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-700'
    }`}
    title={checked ? 'Active' : 'Inactive'}
  >
    <span
      className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
        checked ? 'translate-x-6' : 'translate-x-0'
      }`}
    />
  </button>
);

const formatModifierValue = (value?: number) => {
  if (value === undefined) {
    return '-';
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
};

const EventsSettingsPage: React.FC = () => {
  const [events, setEvents] = useState<FishingEvent[]>(MOCK_EVENTS);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [selectedEvent, setSelectedEvent] = useState<FishingEvent | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const activeCount = useMemo(() => events.filter(event => event.is_active).length, [events]);

  const handleToggleActive = (id: number, next: boolean) => {
    setEvents(prev => prev.map(event => (event.id === id ? { ...event, is_active: next } : event)));
  };

  const handleDelete = (id: number) => {
    const event = events.find(item => item.id === id);
    if (!event) {
      return;
    }
    const confirmed = window.confirm(`Delete event "${event.event_title}"?`);
    if (!confirmed) {
      return;
    }
    setEvents(prev => prev.filter(item => item.id !== id));
  };

  const handleOpenCreate = () => {
    setModalMode('create');
    setSelectedEvent(null);
    setIsModalOpen(true);
  };

  const handleOpenEdit = (event: FishingEvent) => {
    setModalMode('edit');
    setSelectedEvent(event);
    setIsModalOpen(true);
  };

  const handleSaveEvent = (draft: Omit<FishingEvent, 'id'>) => {
    if (modalMode === 'create') {
      setEvents(prev => [...prev, { ...draft, id: Date.now() }]);
      setIsModalOpen(false);
      return;
    }

    if (!selectedEvent) {
      return;
    }

    setEvents(prev => prev.map(event => (event.id === selectedEvent.id ? { ...event, ...draft } : event)));
    setIsModalOpen(false);
  };

  const handleSaveConfig = () => {
    window.alert('Events config saved (mock).');
  };

  return (
    <div className="relative min-h-screen font-sans">
      <div className="relative z-10 p-6 transition-colors duration-300 text-slate-900 dark:text-slate-200">
        <div className="max-w-6xl mx-auto animate-in fade-in duration-500">
          <div className="mb-8 bg-white/90 dark:bg-slate-900/80 p-4 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <h1 className="text-3xl font-bold flex items-center gap-3 text-slate-900 dark:text-white">
              <CalendarDays className="w-8 h-8 text-indigo-600 dark:text-indigo-500" />
              Events Settings
            </h1>
            <p className="mt-1 text-sm font-medium text-slate-600 dark:text-slate-400">
              Configure fishing events, modifiers and activation state.
            </p>
          </div>

          <div className="rounded-xl border overflow-hidden min-h-[600px] flex flex-col transition-colors shadow-lg bg-white/90 border-slate-200 dark:bg-slate-900/85 dark:border-slate-700">
            <div className="p-6 border-b flex items-center justify-between sticky top-0 z-10 backdrop-blur-md bg-white/85 border-slate-200/70 dark:bg-slate-900/85 dark:border-slate-800/70">
              <div>
                <h2 className="text-xl font-bold text-slate-900 dark:text-white drop-shadow-sm">
                  Channel Events
                </h2>
                <div className="text-sm mt-1 text-slate-500 dark:text-slate-400">
                  Total: {events.length} | Active: {activeCount}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveConfig}
                  className="px-4 py-2 rounded-lg font-bold shadow-lg flex items-center gap-2 transition-colors text-white bg-indigo-600 hover:bg-indigo-500 shadow-indigo-500/20"
                >
                  <Save className="w-4 h-4" /> Save Config
                </button>
                <button
                  onClick={handleOpenCreate}
                  className="px-4 py-2 rounded-lg font-bold shadow-lg flex items-center gap-2 transition-colors text-white bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/20"
                >
                  <Plus className="w-4 h-4" /> Add Event
                </button>
              </div>
            </div>

            {events.length === 0 ? (
              <div className="p-12 text-center border-t border-slate-200 text-slate-500 dark:border-slate-800 dark:text-slate-600">
                No events configured.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="text-xs uppercase tracking-wider border-b bg-slate-50/50 border-slate-200/50 text-slate-500 dark:bg-slate-950/30 dark:border-slate-800/50 dark:text-slate-400">
                      <th className="p-4 font-semibold">Event</th>
                      <th className="p-4 font-semibold">Modifiers</th>
                      <th className="p-4 font-semibold text-center">Active</th>
                      <th className="p-4 font-semibold">Override Pool</th>
                      <th className="p-4 font-semibold text-center">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200/50 dark:divide-slate-800/50">
                    {events.map(event => (
                      <tr
                        key={event.id}
                        className="transition-colors hover:bg-slate-100/50 dark:hover:bg-slate-800/40"
                      >
                        <td className="p-4">
                          <div className="font-bold text-sm text-slate-800 dark:text-slate-200">
                            {event.event_title}
                          </div>
                        </td>
                        <td className="p-4 text-xs font-mono">
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-600 dark:text-slate-400">
                            <span>luck: {formatModifierValue(event.modifiers.luck_mult)}</span>
                            <span>xp: {formatModifierValue(event.modifiers.xp_mult)}</span>
                            <span>cd: {formatModifierValue(event.modifiers.cd_reduction)}</span>
                            <span>mass: {formatModifierValue(event.modifiers.bonus_mass)}</span>
                          </div>
                        </td>
                        <td className="p-4 text-center">
                          <div className="flex justify-center">
                            <ActiveToggle
                              checked={event.is_active}
                              onChange={next => handleToggleActive(event.id, next)}
                            />
                          </div>
                        </td>
                        <td className="p-4 text-sm text-slate-600 dark:text-slate-400 font-mono">
                          {event.override_loot_pool || '-'}
                        </td>
                        <td className="p-4">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => handleOpenEdit(event)}
                              className="p-2 rounded-lg transition-all text-slate-500 hover:text-indigo-700 hover:bg-indigo-50 dark:text-slate-500 dark:hover:text-indigo-300 dark:hover:bg-indigo-500/10"
                              title="Edit Event"
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(event.id)}
                              className="p-2 rounded-lg transition-all text-slate-400 hover:text-red-700 hover:bg-red-50 dark:text-slate-500 dark:hover:text-red-400 dark:hover:bg-red-500/10"
                              title="Delete Event"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      <EventEditModal
        isOpen={isModalOpen}
        mode={modalMode}
        initialEvent={selectedEvent}
        onClose={() => setIsModalOpen(false)}
        onSave={handleSaveEvent}
      />
    </div>
  );
};

export default EventsSettingsPage;
