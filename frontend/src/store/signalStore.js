// frontend/src/store/signalStore.js
import { create } from 'zustand'

export const useSignalStore = create((set, get) => ({
  signals: [],          // today's signals
  ltpMap: {},           // { instrument_key: ltp }
  filter: 'ALL',        // 'ALL' | 'S1' | 'S2'
  wsConnected: false,

  setFilter: (f) => set({ filter: f }),
  setWsConnected: (v) => set({ wsConnected: v }),

  // Called when WebSocket sends new_signals
  addSignals: (incoming) => set((state) => {
    const existing = new Map(state.signals.map(s => [s.id, s]))
    incoming.forEach(s => existing.set(s.id, s))
    return { signals: Array.from(existing.values()) }
  }),

  // Called on WS ltp tick
  updateLtp: (instrument_key, ltp) => set((state) => ({
    ltpMap: { ...state.ltpMap, [instrument_key]: ltp }
  })),

  // Called on status_update
  updateStatus: (signal_id, status, ltp) => set((state) => ({
    signals: state.signals.map(s =>
      s.id === signal_id ? { ...s, status, ltp } : s
    )
  })),

  // Replace entire signal list (on page load)
  setSignals: (signals) => set({ signals }),

  filteredSignals: () => {
    const { signals, filter } = get()
    if (filter === 'ALL') return signals
    return signals.filter(s => s.strategy === filter)
  },

  getLtp: (upstox_key) => get().ltpMap[upstox_key] ?? null,
}))
