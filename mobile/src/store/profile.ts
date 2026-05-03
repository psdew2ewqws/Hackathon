import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

const STORAGE_KEY = "taregak.profile.v1";

export interface Profile {
  name: string;
  phone: string;
  createdAt: string;
}

interface ProfileState {
  profile: Profile | null;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  signIn: (input: { name: string; phone: string }) => Promise<void>;
  signOut: () => Promise<void>;
}

export const useProfile = create<ProfileState>((set) => ({
  profile: null,
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      const profile = raw ? (JSON.parse(raw) as Profile) : null;
      set({ profile, hydrated: true });
    } catch {
      set({ profile: null, hydrated: true });
    }
  },
  signIn: async ({ name, phone }) => {
    const profile: Profile = {
      name: name.trim(),
      phone: phone.trim(),
      createdAt: new Date().toISOString(),
    };
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
    set({ profile });
  },
  signOut: async () => {
    await AsyncStorage.removeItem(STORAGE_KEY);
    set({ profile: null });
  },
}));
