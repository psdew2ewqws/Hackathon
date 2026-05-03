import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";

import { confirmAction } from "../../src/lib/confirm";
import { useHistory, type TripEntry } from "../../src/store/history";

export default function HistoryTab() {
  const { t } = useTranslation();
  const trips = useHistory((s) => s.trips);
  const remove = useHistory((s) => s.remove);
  const clear = useHistory((s) => s.clear);

  const onClear = () => {
    confirmAction(
      {
        title: t("history.clearConfirmTitle"),
        message: t("history.clearConfirmBody"),
        confirmLabel: t("history.clearAll"),
        cancelLabel: t("common.cancel"),
        destructive: true,
      },
      () => void clear(),
    );
  };

  if (trips.length === 0) {
    return (
      <View style={styles.empty}>
        <Ionicons name="time-outline" size={48} color="#3A4253" />
        <Text style={styles.emptyTitle}>{t("history.empty")}</Text>
        <Text style={styles.emptyBody}>{t("history.emptyBody")}</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <Text style={styles.count}>{t("history.count", { n: trips.length })}</Text>
        <Pressable onPress={onClear} hitSlop={8}>
          <Text style={styles.clearLink}>{t("history.clearAll")}</Text>
        </Pressable>
      </View>
      {trips.map((trip) => (
        <TripCard key={trip.id} trip={trip} onDelete={() => void remove(trip.id)} />
      ))}
    </ScrollView>
  );
}

function TripCard({ trip, onDelete }: { trip: TripEntry; onDelete: () => void }) {
  const { t } = useTranslation();
  const arriveBy = new Date(trip.arriveBy);
  const dep = trip.recommendedDeparture ? new Date(trip.recommendedDeparture) : null;
  const arr = trip.expectedArrival ? new Date(trip.expectedArrival) : null;

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={[styles.dot, { backgroundColor: "#3B82F6" }]} />
        <Text style={styles.placeName} numberOfLines={1}>{trip.origin.name}</Text>
      </View>
      <View style={styles.connector} />
      <View style={styles.row}>
        <View style={[styles.dot, { backgroundColor: "#EF4444" }]} />
        <Text style={styles.placeName} numberOfLines={1}>{trip.dest.name}</Text>
      </View>

      <View style={styles.metaRow}>
        <View style={styles.metaCol}>
          <Text style={styles.metaLabel}>{t("history.arriveBy")}</Text>
          <Text style={styles.metaValue}>{formatDateTime(arriveBy)}</Text>
        </View>
        {dep && (
          <View style={styles.metaCol}>
            <Text style={styles.metaLabel}>{t("history.leftAt")}</Text>
            <Text style={styles.metaValue}>{formatTime(dep)}</Text>
          </View>
        )}
        {arr && (
          <View style={styles.metaCol}>
            <Text style={styles.metaLabel}>{t("history.arrived")}</Text>
            <Text style={styles.metaValue}>{formatTime(arr)}</Text>
          </View>
        )}
      </View>

      {trip.status === "IMPOSSIBLE" && (
        <Text style={styles.impossibleTag}>{t("history.impossible")}</Text>
      )}

      <Pressable style={styles.deleteBtn} onPress={onDelete} hitSlop={8}>
        <Ionicons name="trash-outline" size={16} color="#5C6373" />
      </Pressable>
    </View>
  );
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(d: Date): string {
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} · ${formatTime(d)}`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0F1115" },
  content: { padding: 16, paddingBottom: 48 },
  empty: {
    flex: 1,
    backgroundColor: "#0F1115",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
  },
  emptyTitle: { color: "#fff", fontSize: 18, fontWeight: "600", marginTop: 12 },
  emptyBody: { color: "#8B95A8", fontSize: 14, marginTop: 6, textAlign: "center" },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
    paddingHorizontal: 4,
  },
  count: { color: "#8B95A8", fontSize: 13 },
  clearLink: { color: "#F87171", fontSize: 13, fontWeight: "600" },
  card: {
    backgroundColor: "#1A1F29",
    borderRadius: 12,
    padding: 16,
    marginBottom: 10,
    position: "relative",
  },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  connector: { width: 2, height: 14, backgroundColor: "#2A3343", marginLeft: 4, marginVertical: 2 },
  placeName: { color: "#fff", fontSize: 15, fontWeight: "500", flex: 1 },
  metaRow: { flexDirection: "row", marginTop: 14, gap: 18 },
  metaCol: { flex: 1 },
  metaLabel: { color: "#5C6373", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 },
  metaValue: { color: "#A8B3C5", fontSize: 13, marginTop: 2 },
  impossibleTag: {
    color: "#F87171",
    fontSize: 11,
    fontWeight: "600",
    marginTop: 10,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  deleteBtn: { position: "absolute", top: 12, right: 12, padding: 4 },
});
