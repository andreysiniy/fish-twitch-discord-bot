import React, { useState } from 'react';
import { Settings, Plus, Save, Map, CheckCircle2 } from 'lucide-react';
import { LootTable } from './components/admin/LootTable';
import { AddRewardModal } from './components/admin/AddRewardModal';
import { LocationSettingsModal } from './components/admin/LocationSettingsModal';
import { Location, Reward } from './types';

type LocationSettingsDraft = Pick<Location, 'id' | 'name' | 'items_drop_rate' | 'requirements'>;

const LOCATION_BG: Record<string, string> = {
  lake_default:
    'https://media.npr.org/assets/img/2023/05/04/thejames_usvi_4_custom-06b438ea24075fa022d2bcf81f97d1a678cf8a5b.jpg',
  tel_aviv: 'https://media-cdn.tripadvisor.com/media/photo-m/1280/16/ff/c3/55/img-20190326-wa0099-largejpg.jpg',
  default: 'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&q=80',
};

const MOCK_LOCATIONS: Location[] = [
  {
    id: 'lake_default',
    name: 'Mystic Lake',
    items_drop_rate: 0.1,
    requirements: {},
    rewards: [
      { id: 1, type: 'fish', weight: 2000, message: 'Common Carp!', min_mass: 0.8, max_mass: 1.2 },
      { id: 2, type: 'timeout', weight: 50, message: 'haha timeout!', duration: 60, reason: 'bad luck' },
    ] as Reward[],
  },
  {
    id: 'tel_aviv',
    name: 'Tel Aviv Beach',
    items_drop_rate: 0.15,
    requirements: {
      level: 3,
      total_mass_stat: 10,
    },
    rewards: [],
  },
];

const normalizeLocationId = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'location';

const AdminPanel = () => {
  const [locations, setLocations] = useState<Location[]>(MOCK_LOCATIONS);
  const [selectedLocationId, setSelectedLocationId] = useState<string>(MOCK_LOCATIONS[0].id);
  const [isRewardModalOpen, setIsRewardModalOpen] = useState(false);
  const [isLocationSettingsOpen, setIsLocationSettingsOpen] = useState(false);
  const [locationSettingsMode, setLocationSettingsMode] = useState<'create' | 'edit'>('edit');

  const currentLocation = locations.find(loc => loc.id === selectedLocationId) || locations[0];
  const currentBgImage = LOCATION_BG[currentLocation.id] || LOCATION_BG.default;

  const handleDeleteReward = (id: number) => {
    setLocations(prev =>
      prev.map(loc => {
        if (loc.id !== selectedLocationId) {
          return loc;
        }
        return { ...loc, rewards: loc.rewards.filter(r => r.id !== id) };
      }),
    );
  };

  const handleAddReward = (newRewardWithoutId: Omit<Reward, 'id'>) => {
    setLocations(prev =>
      prev.map(loc => {
        if (loc.id !== selectedLocationId) {
          return loc;
        }
        const newReward = { ...newRewardWithoutId, id: Date.now() } as Reward;
        return { ...loc, rewards: [...loc.rewards, newReward] };
      }),
    );
    setIsRewardModalOpen(false);
  };

  const getUniqueLocationId = (requestedId: string): string => {
    const baseId = normalizeLocationId(requestedId);
    let nextId = baseId;
    let counter = 1;

    while (locations.some(loc => loc.id === nextId)) {
      nextId = `${baseId}_${counter}`;
      counter += 1;
    }

    return nextId;
  };

  const handleOpenCreateLocationSettings = () => {
    setLocationSettingsMode('create');
    setIsLocationSettingsOpen(true);
  };

  const handleOpenEditLocationSettings = () => {
    setLocationSettingsMode('edit');
    setIsLocationSettingsOpen(true);
  };

  const handleSaveLocationSettings = (draft: LocationSettingsDraft) => {
    if (locationSettingsMode === 'create') {
      const uniqueId = getUniqueLocationId(draft.id || draft.name);
      const nextLocation: Location = {
        id: uniqueId,
        name: draft.name,
        items_drop_rate: draft.items_drop_rate,
        requirements: draft.requirements,
        rewards: [],
      };

      setLocations(prev => [...prev, nextLocation]);
      setSelectedLocationId(uniqueId);
      setIsLocationSettingsOpen(false);
      return;
    }

    setLocations(prev =>
      prev.map(loc =>
        loc.id === selectedLocationId
          ? {
              ...loc,
              name: draft.name,
              items_drop_rate: draft.items_drop_rate,
              requirements: draft.requirements,
            }
          : loc,
      ),
    );
    setIsLocationSettingsOpen(false);
  };

  return (
    <div className="relative min-h-screen font-sans">
      <div
        className="fixed inset-0 z-0 transition-all duration-1000 ease-in-out"
        style={{
          backgroundImage: `url(${currentBgImage})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />

      <div
        className="fixed inset-0 z-0 transition-colors duration-300
        bg-slate-50/20
        dark:bg-slate-950/85
        backdrop-blur-[1px] dark:backdrop-blur-[2px]"
      />

      <div className="relative z-10 p-6 transition-colors duration-300 text-slate-900 dark:text-slate-200">
        <div className="max-w-6xl mx-auto animate-in fade-in duration-500">
          <div className="mb-8">
            <div className="bg-white/35 dark:bg-slate-900/50 p-4 rounded-xl backdrop-blur-sm border border-white/20 dark:border-slate-800/50 shadow-sm">
              <h1 className="text-3xl font-bold flex items-center gap-3 text-slate-900 dark:text-white">
                <Settings className="w-8 h-8 text-indigo-600 dark:text-indigo-500" />
                Loot Table Editor
              </h1>
              <p className="mt-1 text-sm font-medium text-slate-600 dark:text-slate-400">
                Configure drop rates and rewards for your channel.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <div className="lg:col-span-1 space-y-4">
              <div
                className="rounded-xl border p-4 transition-colors backdrop-blur-md shadow-lg
                bg-white/60 border-white/25 
                dark:bg-slate-900/80 dark:border-slate-700/50"
              >
                <div className="mb-3 flex items-center justify-between">
                  <h2
                    className="text-xs uppercase tracking-wider font-bold flex items-center gap-2
                    text-slate-500 dark:text-slate-500"
                  >
                    <Map className="w-4 h-4" /> Locations
                  </h2>
                  <button
                    onClick={handleOpenCreateLocationSettings}
                    className="px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide flex items-center gap-1 transition-colors
                      bg-indigo-600 text-white hover:bg-indigo-500"
                  >
                    <Plus className="w-3 h-3" /> Add Location
                  </button>
                </div>
                <div className="space-y-2">
                  {locations.map(loc => (
                    <button
                      key={loc.id}
                      onClick={() => setSelectedLocationId(loc.id)}
                      className={`w-full text-left px-4 py-3 rounded-lg transition-all flex items-center justify-between border ${
                        selectedLocationId === loc.id
                          ? 'bg-indigo-50/80 border-indigo-200 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300 dark:border-indigo-500/30'
                          : 'border-transparent text-slate-600 hover:bg-slate-100/50 dark:text-slate-400 dark:hover:bg-slate-800/50'
                      }`}
                    >
                      <span className="font-medium text-sm">{loc.name}</span>
                      {selectedLocationId === loc.id && <CheckCircle2 className="w-4 h-4" />}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="lg:col-span-3">
              <div
                className="rounded-xl border overflow-hidden min-h-[600px] flex flex-col transition-colors backdrop-blur-md shadow-lg
                bg-white/60 border-white/25 
                dark:bg-slate-900/80 dark:border-slate-700/50"
              >
                <div
                  className="p-6 border-b flex items-center justify-between sticky top-0 z-10 backdrop-blur-md
                  bg-white/45 border-slate-200/40 
                  dark:bg-slate-900/60 dark:border-slate-800/50"
                >
                  <div>
                    <h2 className="text-xl font-bold text-slate-900 dark:text-white drop-shadow-sm">
                      {currentLocation.name}
                    </h2>
                    <div className="flex items-center gap-2 text-sm mt-1 text-slate-500 dark:text-slate-400">
                      <span
                        className="font-mono text-xs px-1.5 py-0.5 rounded
                        bg-slate-100/80 text-slate-600
                        dark:bg-slate-950/80 dark:text-slate-400"
                      >
                        {currentLocation.id}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      className="px-4 py-2 rounded-lg font-bold shadow-lg flex items-center gap-2 transition-colors text-white
                        bg-indigo-600 hover:bg-indigo-500 shadow-indigo-500/20"
                    >
                      <Save className="w-4 h-4" /> Save Location
                    </button>
                    <button
                      onClick={handleOpenEditLocationSettings}
                      className="px-4 py-2 rounded-lg font-bold shadow-lg border flex items-center gap-2 transition-colors
                        bg-slate-100 text-slate-900 border-slate-400 hover:bg-slate-200
                        dark:!bg-slate-700 dark:!text-slate-100 dark:border-slate-600 dark:hover:!bg-slate-600 shadow-slate-500/20"
                    >
                      <Settings className="w-4 h-4" /> Edit Settings
                    </button>
                    <button
                      onClick={() => setIsRewardModalOpen(true)}
                      className="px-4 py-2 rounded-lg font-bold shadow-lg flex items-center gap-2 transition-colors text-white
                        bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/20"
                    >
                      <Plus className="w-4 h-4" /> Add Reward
                    </button>
                  </div>
                </div>

                <LootTable rewards={currentLocation.rewards} onDelete={handleDeleteReward} />
              </div>
            </div>
          </div>

          <AddRewardModal
            isOpen={isRewardModalOpen}
            onClose={() => setIsRewardModalOpen(false)}
            onAdd={handleAddReward}
          />
          <LocationSettingsModal
            isOpen={isLocationSettingsOpen}
            mode={locationSettingsMode}
            initialLocation={locationSettingsMode === 'edit' ? currentLocation : null}
            onClose={() => setIsLocationSettingsOpen(false)}
            onSave={handleSaveLocationSettings}
          />
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;
