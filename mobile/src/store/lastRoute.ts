import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

import type { PlaceDetails } from "../services/api";

const STORAGE_KEY = "taregak.lastRoute.v1";

interface Snapshot {
  origin: PlaceDetails | null;
  dest: PlaceDetails | null;
}

interface LastRouteState extends Snapshot {
  hydrated: boolean;
  hydrate: () => Promise<void>;
  save: (snap: Snapshot) => Promise<void>;
}

export const useLastRoute = create<LastRouteState>((set) => ({
  origin: null,
  dest: null,
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      const snap = raw ? (JSON.parse(raw) as Snapshot) : { origin: null, dest: null };
      set({ origin: snap.origin, dest: snap.dest, hydrated: true });
    } catch {
      set({ origin: null, dest: null, hydrated: true });
    }
  },
  save: async ({ origin, dest }) => {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ origin, dest }));
    set({ origin, dest });
  },
}));
