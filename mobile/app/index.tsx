import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Stack } from "expo-router";

import { PlaceSearchInput } from "../src/components/PlaceSearchInput";
import { MapPicker } from "../src/components/MapPicker";
import {
  predictDeparture,
  type PlaceDetails,
  type PredictDepartureResponse,
} from "../src/services/api";
import { getDeviceId } from "../src/store/deviceId";

const DEFAULT_ARRIVE_BY_OFFSET_MIN = 120;

/**
 * Returns "YYYY-MM-DDTHH:MM" in the user's *local* timezone, because that's
 * how an HTML <input type="datetime-local"> (and a plain text input parsed
 * via `new Date(...)`) interpret a string with no timezone suffix.
 */
function defaultArriveBy(): string {
  const d = new Date(Date.now() + DEFAULT_ARRIVE_BY_OFFSET_MIN * 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

export default function Home() {
  const { t } = useTranslation();
  const [origin, setOrigin] = useState<PlaceDetails | null>(null);
  const [dest, setDest] = useState<PlaceDetails | null>(null);
  const [arriveBy, setArriveBy] = useState(defaultArriveBy());

  const canSubmit = Boolean(origin && dest && arriveBy);

  const mut = useMutation({
    mutationFn: async (): Promise<PredictDepartureResponse> => {
      if (!origin || !dest) throw new Error("Pick origin and destination");
      return predictDeparture(
        {
          origin: origin.location,
          dest: dest.location,
          arriveBy: new Date(arriveBy).toISOString(),
        },
        getDeviceId(),
      );
    },
  });

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: t("appName") }} />
      <Text style={styles.tagline}>{t("home.tagline")}</Text>

      <MapPicker origin={origin} dest={dest} onOriginChange={setOrigin} onDestChange={setDest} />

      <PlaceSearchInput
        label={t("home.originLabel")}
        placeholder="Or type a place in Amman…"
        value={origin}
        onChange={setOrigin}
      />
      <PlaceSearchInput
        label={t("home.destLabel")}
        placeholder="Or type a place in Amman…"
        value={dest}
        onChange={setDest}
      />

      <Text style={styles.label}>{t("home.arriveByLabel")}</Text>
      <TextInput
        style={styles.input}
        value={arriveBy}
        onChangeText={setArriveBy}
        placeholder="YYYY-MM-DDTHH:MM"
        placeholderTextColor="#5C6373"
      />

      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={() => mut.mutate()}
        disabled={!canSubmit || mut.isPending}
      >
        <Text style={styles.buttonText}>{mut.isPending ? t("result.loading") : t("home.submit")}</Text>
      </Pressable>

      {mut.isPending && <ActivityIndicator style={{ marginTop: 16 }} color="#fff" />}
      {mut.isError && <Text style={styles.error}>{(mut.error as Error).message}</Text>}
      {mut.data && <Result data={mut.data} arriveBy={arriveBy} />}
    </ScrollView>
  );
}

function Result({ data, arriveBy }: { data: PredictDepartureResponse; arriveBy: string }) {
  const { t } = useTranslation();
  if (data.status === "IMPOSSIBLE") {
    const earliest = data.earliestArrival ? new Date(data.earliestArrival) : null;
    return (
      <View style={styles.resultCard}>
        <Text style={styles.resultHero}>—</Text>
        <Text style={styles.resultSub}>
          Earliest possible arrival: {earliest ? formatTime(earliest) : "n/a"}
        </Text>
      </View>
    );
  }
  const dep = new Date(data.recommendedDeparture!);
  const arr = new Date(data.expectedArrival!);
  const deadline = new Date(arriveBy);
  const slackMin = Math.round((deadline.getTime() - arr.getTime()) / 60_000);
  return (
    <View style={styles.resultCard}>
      <Text style={styles.resultHero}>
        {t("result.leaveAt")} {formatTime(dep)}
      </Text>
      <Text style={styles.resultSub}>
        {t("result.arrives")} {formatTime(arr)} — {t("result.minutesEarly", { n: slackMin })}
      </Text>
      <Text style={styles.resultMeta}>{t("result.based")} · {data.apiCallsUsed} API calls</Text>
    </View>
  );
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0F1115" },
  content: { padding: 24, paddingBottom: 64 },
  tagline: { color: "#8B95A8", fontSize: 16, marginBottom: 8 },
  label: { color: "#8B95A8", fontSize: 13, marginTop: 12, marginBottom: 4 },
  input: {
    color: "#fff",
    backgroundColor: "#1A1F29",
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 8,
    fontSize: 16,
  },
  button: {
    marginTop: 20,
    backgroundColor: "#3B82F6",
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: "center",
  },
  buttonDisabled: { backgroundColor: "#2A3343" },
  buttonText: { color: "#fff", fontWeight: "600", fontSize: 16 },
  resultCard: {
    marginTop: 24,
    padding: 24,
    backgroundColor: "#1A1F29",
    borderRadius: 12,
    alignItems: "center",
  },
  resultHero: { color: "#fff", fontSize: 36, fontWeight: "700" },
  resultSub: { color: "#A8B3C5", fontSize: 14, marginTop: 8, textAlign: "center" },
  resultMeta: { color: "#5C6373", fontSize: 11, marginTop: 12 },
  error: { color: "#F87171", marginTop: 16 },
});
