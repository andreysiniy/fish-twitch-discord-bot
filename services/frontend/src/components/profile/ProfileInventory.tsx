import React from 'react';
import { Backpack } from 'lucide-react';
import { getRarityColor } from './getRarityColor';
import type { UserInventory } from './types';

interface ProfileInventoryProps {
  inventory: UserInventory;
}

export const ProfileInventory: React.FC<ProfileInventoryProps> = ({ inventory }) => {
  const slots = Array.from({ length: inventory.max_slots }, (_, index) => index + 1);
  const itemsBySlot = new Map(inventory.items.map((item) => [item.slot_id, item]));

  return (
    <div className="lg:col-span-2">
      <div
        className="rounded-xl p-5 border shadow-lg h-full transition-colors backdrop-blur-md
          bg-white/60 border-white/25
          dark:bg-slate-900/80 dark:border-slate-700/50"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold flex items-center gap-2 text-slate-900 dark:text-white">
            <Backpack className="w-5 h-5 text-emerald-500 dark:text-emerald-400" /> Inventory
          </h2>
          <span
            className="text-xs font-mono px-2 py-1 rounded
              bg-slate-100/80 text-slate-600
              dark:bg-slate-900/50 dark:text-slate-400"
          >
            {inventory.items.length} / {inventory.max_slots} Slots
          </span>
        </div>

        <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-5 gap-3">
          {slots.map((slotId) => {
            const item = itemsBySlot.get(slotId);
            const isEquipped = inventory.equipped_rod_slot === slotId;

            return (
              <div
                key={slotId}
                className={`
                  relative aspect-square rounded-lg border-2 flex flex-col items-center justify-center p-2 transition-all hover:scale-105 cursor-pointer backdrop-blur-sm
                  ${
                    item
                      ? getRarityColor(item.rarity)
                      : 'border-slate-200/50 bg-white/40 dark:border-slate-700/50 dark:bg-slate-900/45'
                  }
                  ${isEquipped ? 'ring-2 ring-green-500 dark:ring-green-400 shadow-[0_0_10px_rgba(74,222,128,0.5)]' : ''}
                `}
                title={item ? item.description : 'Empty Slot'}
              >
                {isEquipped && (
                  <div className="absolute top-1 right-1 w-3 h-3 bg-green-500 rounded-full animate-pulse" title="Equipped" />
                )}

                {item ? (
                  <>
                    <img src={item.image_url} alt={item.name} className="w-10 h-10 object-contain drop-shadow-md mb-1" />
                    <span className="text-[10px] font-bold text-center leading-tight line-clamp-2 text-slate-700 dark:text-slate-200">
                      {item.name}
                    </span>
                    {item.quantity > 1 && (
                      <div className="absolute bottom-1 right-1 bg-black/60 text-white text-[10px] px-1.5 rounded-full">x{item.quantity}</div>
                    )}
                  </>
                ) : (
                  <span className="text-slate-400 dark:text-slate-600 text-xs font-mono">{slotId}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
