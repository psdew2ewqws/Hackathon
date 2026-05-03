import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { SanadMark } from "./SanadMark";

interface Props {
  onPress: () => void;
  loading?: boolean;
  label: string;
}

const SANAD_GREEN = "#0F5F50";
const SANAD_GREEN_PRESSED = "#0B4A3E";

export function SanadButton({ onPress, loading, label }: Props) {
  return (
    <Pressable
      onPress={loading ? undefined : onPress}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: pressed ? SANAD_GREEN_PRESSED : SANAD_GREEN },
        loading && styles.disabled,
      ]}
    >
      <View style={styles.markBox}>
        <SanadMark tone="light" />
      </View>
      <View style={styles.divider} />
      <Text style={styles.label}>{label}</Text>
      {loading && <ActivityIndicator color="#fff" style={styles.spinner} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 12,
    minHeight: 64,
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
  },
  disabled: { opacity: 0.7 },
  markBox: { width: 64, alignItems: "center", justifyContent: "center" },
  divider: { width: 1, height: 32, backgroundColor: "rgba(255,255,255,0.18)", marginHorizontal: 12 },
  label: { color: "#fff", fontSize: 17, fontWeight: "700", letterSpacing: 0.3, flex: 1 },
  spinner: { marginLeft: 8 },
});
