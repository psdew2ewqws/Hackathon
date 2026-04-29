import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Stack } from "expo-router";

import { predictDeparture, type PredictDepartureResponse } from "../src/services/api";
import { getDeviceId } from "../src/store/deviceId";

const DEFAULT_ARRIVE_BY_OFFSET_MIN = 60;

function defaultArriveBy(): string {
  const d = new Date(Date.now() + DEFAULT_ARRIVE_BY_OFFSET_MIN * 60_000);
  return d.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM
}

function parseLatLng(s: string): { lat: number; lng: number } | null {
  const parts = s.split(",").map((p) => parseFloat(p.trim()));
  if (parts.length !== 2 || parts.some(isNaN)) return null;
  return { lat: parts[0]!, lng: parts[1]! };
}

export default function Home() {
  const { t } = useTranslation();
  const [origin, setOrigin] = useState("31.951, 35.923"); // Downtown Amman
  const [dest, setDest] = useState("31.987, 35.872"); // University of Jordan
  const [arriveBy, setArriveBy] = useState(defaultArriveBy());

  const mut = useMutation({
    mutationFn: async (): Promise<PredictDepartureResponse> => {
      const o = parseLatLng(origin);
      const d = parseLatLng(dest);
      if (!o || !d) throw new Error("Bad lat,lng");
      return predictDeparture(
        { origin: o, dest: d, arriveBy: new Date(arriveBy).toISOString() },
        getDeviceId(),
      );
    },
  });

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: t("appName") }} />
      <Text style={styles.tagline}>{t("home.tagline")}</Text>

      <Text style={styles.label}>{t("home.originLabel")}</Text>
      <TextInput style={styles.input} value={origin} onChangeText={setOrigin} placeholder={t("home.originPlaceholder")} placeholderTextColor="#666" />

      <Text style={styles.label}>{t("home.destLabel")}</Text>
      <TextInput style={styles.input} value={dest} onChangeText={setDest} placeholder={t("home.destPlaceholder")} placeholderTextColor="#666" />

      <Text style={styles.label}>{t("home.arriveByLabel")}</Text>
      <TextInput style={styles.input} value={arriveBy} onChangeText={setArriveBy} placeholder="YYYY-MM-DDTHH:MM" placeholderTextColor="#666" />

      <Pressable style={styles.button} onPress={() => mut.mutate()} disabled={mut.isPending}>
        <Text style={styles.buttonText}>{mut.isPending ? t("result.loading") : t("home.submit")}</Text>
      </Pressable>

      {mut.isPending && <ActivityIndicator style={{ marginTop: 16 }} color="#fff" />}
      {mut.isError && <Text style={styles.error}>{t("result.error")}</Text>}
      {mut.data && <Result data={mut.data} arriveBy={arriveBy} />}
    </View>
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
  container: { flex: 1, padding: 24, backgroundColor: "#0F1115" },
  tagline: { color: "#8B95A8", fontSize: 16, marginBottom: 24 },
  label: { color: "#8B95A8", fontSize: 13, marginTop: 12, marginBottom: 4 },
  input: {
    color: "#fff",
    backgroundColor: "#1A1F29",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 8,
    fontSize: 16,
  },
  button: {
    marginTop: 24,
    backgroundColor: "#3B82F6",
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: "center",
  },
  buttonText: { color: "#fff", fontWeight: "600", fontSize: 16 },
  resultCard: {
    marginTop: 32,
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
