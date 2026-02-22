import React, { useState } from 'react';
import { Settings, Plus, Save, Map, CheckCircle2 } from 'lucide-react';
import { LootTable } from './components/admin/LootTable';
import { AddRewardModal } from './components/admin/AddRewardModal';
import { Location, Reward } from './types';

// --- CONFIG ---
const LOCATION_BG: Record<string, string> = {
  'lake_default': 'https://media.npr.org/assets/img/2023/05/04/thejames_usvi_4_custom-06b438ea24075fa022d2bcf81f97d1a678cf8a5b.jpg',
  'ocean_deep': 'https://www.oqfoundation.org/wp-content/uploads/2025/01/spotlite-scaled.jpg',
  'default': 'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&q=80'
};

// Mock Data
const MOCK_LOCATIONS: Location[] = [
  {
    id: "lake_default",
    name: "Mystic Lake",
    rewards: [
      { id: 1, type: "fish", weight: 2000, message: "🐟 Common Carp!", min_mass: 0.8, max_mass: 1.2 },
      { id: 2, type: "timeout", weight: 50, message: "haha timeout!", duration: 60, reason: "bad luck" },
    ] as Reward[]
  },
  {
    id: "ocean_deep",
    name: "Deep Ocean",
    rewards: []
  }
];

const AdminPanel = () => {
  const [locations, setLocations] = useState<Location[]>(MOCK_LOCATIONS);
  const [selectedLocationId, setSelectedLocationId] = useState<string>(MOCK_LOCATIONS[0].id);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const currentLocation = locations.find(loc => loc.id === selectedLocationId) || locations[0];
  
  const currentBgImage = LOCATION_BG[currentLocation.id] || LOCATION_BG['default'];

  const handleDeleteReward = (id: number) => {
    setLocations(prev => prev.map(loc => {
      if (loc.id !== selectedLocationId) return loc;
      return { ...loc, rewards: loc.rewards.filter(r => r.id !== id) };
    }));
  };

  const handleAddReward = (newRewardWithoutId: Omit<Reward, 'id'>) => {
    setLocations(prev => prev.map(loc => {
      if (loc.id !== selectedLocationId) return loc;
      const newReward = { ...newRewardWithoutId, id: Date.now() } as Reward;
      return { 
        ...loc, 
        rewards: [...loc.rewards, newReward] 
      };
    }));
    setIsModalOpen(false);
  };

  return (
    <div className="relative min-h-screen font-sans">
      
      {/* --- BACKGROUND LAYER --- */}
      <div 
        className="fixed inset-0 z-0 transition-all duration-1000 ease-in-out"
        style={{ 
          backgroundImage: `url(${currentBgImage})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />
      
      {/* --- OVERLAY LAYER --- */}
      <div className="fixed inset-0 z-0 transition-colors duration-300
        bg-slate-50/20
        dark:bg-slate-950/85
        backdrop-blur-[1px] dark:backdrop-blur-[2px]"
      />

      {/* --- CONTENT LAYER --- */}
      <div className="relative z-10 p-6 transition-colors duration-300 text-slate-900 dark:text-slate-200">
        <div className="max-w-6xl mx-auto animate-in fade-in duration-500">
          
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div className="bg-white/35 dark:bg-slate-900/50 p-4 rounded-xl backdrop-blur-sm border border-white/20 dark:border-slate-800/50 shadow-sm">
              <h1 className="text-3xl font-bold flex items-center gap-3 text-slate-900 dark:text-white">
                <Settings className="w-8 h-8 text-indigo-600 dark:text-indigo-500" />
                Loot Table Editor
              </h1>
              <p className="mt-1 text-sm font-medium text-slate-600 dark:text-slate-400">Configure drop rates and events for your channel.</p>
            </div>
            <button className="px-5 py-2.5 rounded-xl font-bold shadow-lg flex items-center gap-2 transition-transform active:scale-95 text-white
              bg-indigo-600 hover:bg-indigo-500 shadow-indigo-500/20"
            >
              <Save className="w-4 h-4" /> Save Configuration
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            
            {/* Sidebar (Location List) */}
            <div className="lg:col-span-1 space-y-4">
              <div className="rounded-xl border p-4 transition-colors backdrop-blur-md shadow-lg
                bg-white/60 border-white/25 
                dark:bg-slate-900/80 dark:border-slate-700/50"
              >
                <h2 className="text-xs uppercase tracking-wider font-bold mb-3 flex items-center gap-2
                  text-slate-500 dark:text-slate-500"
                >
                  <Map className="w-4 h-4" /> Locations
                </h2>
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

            {/* Main Content (Table Container) */}
            <div className="lg:col-span-3">
              <div className="rounded-xl border overflow-hidden min-h-[600px] flex flex-col transition-colors backdrop-blur-md shadow-lg
                bg-white/60 border-white/25 
                dark:bg-slate-900/80 dark:border-slate-700/50"
              >
                
                {/* Toolbar */}
                <div className="p-6 border-b flex items-center justify-between sticky top-0 z-10 backdrop-blur-md
                  bg-white/45 border-slate-200/40 
                  dark:bg-slate-900/60 dark:border-slate-800/50"
                >
                  <div>
                    <h2 className="text-xl font-bold text-slate-900 dark:text-white drop-shadow-sm">
                      {currentLocation.name}
                    </h2>
                    <div className="flex items-center gap-2 text-sm mt-1 text-slate-500 dark:text-slate-400">
                      <span className="font-mono text-xs px-1.5 py-0.5 rounded
                        bg-slate-100/80 text-slate-600
                        dark:bg-slate-950/80 dark:text-slate-400"
                      >
                        {currentLocation.id}
                      </span>
                    </div>
                  </div>
                  <button 
                    onClick={() => setIsModalOpen(true)}
                    className="px-4 py-2 rounded-lg font-bold shadow-lg flex items-center gap-2 transition-colors text-white
                      bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/20"
                  >
                    <Plus className="w-4 h-4" /> Add Event
                  </button>
                </div>

                {/* Loot Table Component */}
                <LootTable 
                  rewards={currentLocation.rewards} 
                  onDelete={handleDeleteReward} 
                />

              </div>
            </div>
          </div>

          {/* Modal Component */}
          <AddRewardModal 
            isOpen={isModalOpen} 
            onClose={() => setIsModalOpen(false)} 
            onAdd={handleAddReward} 
          />
          
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;
