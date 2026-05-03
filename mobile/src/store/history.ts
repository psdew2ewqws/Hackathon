import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

const STORAGE_KEY = "taregak.history.v1";
const MAX_ENTRIES = 25;

export interface TripEntry {
  id: string;
  origin: { name: string; lat: number; lng: number };
  dest: { name: string; lat: number; lng: number };
  arriveBy: string;
  status: "OK" | "IMPOSSIBLE";
  recommendedDeparture?: string;
  expectedArrival?: string;
  expectedDurationSec?: number;
  savedAt: string;
}

interface HistoryState {
  trips: TripEntry[];
  hydrated: boolean;
  hydrate: () => Promise<void>;
  push: (entry: TripEntry) => Promise<void>;
  remove: (id: string) => Promise<void>;
  clear: () => Promise<void>;
}

export const useHistory = create<HistoryState>((set, get) => ({
  trips: [],
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      const trips = raw ? (JSON.parse(raw) as TripEntry[]) : [];
      set({ trips, hydrated: true });
    } catch {
      set({ trips: [], hydrated: true });
    }
  },
  push: async (entry) => {
    const next = [entry, ...get().trips].slice(0, MAX_ENTRIES);
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    set({ trips: next });
  },
  remove: async (id) => {
    const next = get().trips.filter((t) => t.id !== id);
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    set({ trips: next });
  },
  clear: async () => {
    await AsyncStorage.removeItem(STORAGE_KEY);
    set({ trips: [] });
  },
}));
