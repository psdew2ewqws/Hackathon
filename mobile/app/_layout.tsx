import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Slot, useRouter, useSegments, type Href } from "expo-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

import "../src/i18n";
import { useProfile } from "../src/store/profile";
import { useHistory } from "../src/store/history";
import { useLastRoute } from "../src/store/lastRoute";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 5 * 60_000 } },
});

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <SafeAreaProvider>
        <StatusBar style="light" />
        <AuthGate />
      </SafeAreaProvider>
    </QueryClientProvider>
  );
}

function AuthGate() {
  const profile = useProfile((s) => s.profile);
  const hydrated = useProfile((s) => s.hydrated);
  const hydrateProfile = useProfile((s) => s.hydrate);
  const hydrateHistory = useHistory((s) => s.hydrate);
  const hydrateLastRoute = useLastRoute((s) => s.hydrate);

  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    void hydrateProfile();
    void hydrateHistory();
    void hydrateLastRoute();
  }, [hydrateProfile, hydrateHistory, hydrateLastRoute]);

  useEffect(() => {
    if (!hydrated) return;
    // segments is a string[] at runtime; typed routes narrow it to known group
    // names, so cast for the comparison and the replace target.
    const inAuthGroup = (segments[0] as string) === "(auth)";
    if (!profile && !inAuthGroup) {
      router.replace("/(auth)/login" as Href);
    } else if (profile && inAuthGroup) {
      router.replace("/(tabs)" as Href);
    }
  }, [hydrated, profile, segments, router]);

  if (!hydrated) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator color="#3B82F6" />
      </View>
    );
  }

  return <Slot />;
}

const styles = StyleSheet.create({
  splash: { flex: 1, backgroundColor: "#0F1115", alignItems: "center", justifyContent: "center" },
});
