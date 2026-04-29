import { useMemo } from "react";
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { formatRelative, toLocalDateTimeString, tomorrowAt } from "../lib/time";

interface Props {
  value: string;
  onChange: (v: string) => void;
}

interface Preset {
  label: string;
  date: Date;
}

function buildPresets(): Preset[] {
  const now = new Date();
  const plus = (min: number) => new Date(Date.now() + min * 60_000);
  return [
    { label: "+1h", date: plus(60) },
    { label: "+2h", date: plus(120) },
    { label: now.getHours() < 9 ? "Today 9 AM" : "Tomorrow 9 AM", date: tomorrowAt(9) },
    { label: now.getHours() < 17 ? "Today 5 PM" : "Tomorrow 5 PM", date: tomorrowAt(17) },
  ];
}

const TONE_COLORS = {
  good: "#10B981",
  tight: "#F59E0B",
  bad: "#F87171",
  neutral: "#8B95A8",
} as const;

export function ArriveByPicker({ value, onChange }: Props) {
  const presets = useMemo(() => buildPresets(), []);
  const relative = useMemo(() => (value ? formatRelative(new Date(value)) : null), [value]);

  return (
    <View>
      <Text style={styles.label}>Arrive by</Text>

      <View style={styles.chips}>
        {presets.map((p) => {
          const active = value === toLocalDateTimeString(p.date);
          return (
            <Pressable
              key={p.label}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => onChange(toLocalDateTimeString(p.date))}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{p.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {Platform.OS === "web" ? (
        <NativeDateTimeInput value={value} onChange={onChange} />
      ) : (
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChange}
          placeholder="YYYY-MM-DDTHH:MM"
          placeholderTextColor="#5C6373"
        />
      )}

      {relative && (
        <Text style={[styles.relative, { color: TONE_COLORS[relative.tone] }]}>{relative.text}</Text>
      )}
    </View>
  );
}

function NativeDateTimeInput({ value, onChange }: Props) {
  // Plain DOM <input> styled to match the dark theme. react-native-web
  // happily passes children through, so this just renders as <input>.
  const inputStyle = {
    backgroundColor: "#1A1F29",
    color: "#fff",
    border: "none",
    outline: "none",
    padding: "12px 14px",
    borderRadius: 8,
    fontSize: 16,
    fontFamily: "inherit",
    width: "100%",
    boxSizing: "border-box" as const,
    colorScheme: "dark" as const,
  };
  return (
    <View>
      <input
        type="datetime-local"
        value={value}
        step={60}
        onChange={(e: { target: { value: string } }) => onChange(e.target.value)}
        style={inputStyle}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  label: { color: "#8B95A8", fontSize: 13, marginTop: 16, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "#1A1F29",
    borderWidth: 1,
    borderColor: "#1A1F29",
  },
  chipActive: { backgroundColor: "#1E3A8A", borderColor: "#3B82F6" },
  chipText: { color: "#A8B3C5", fontSize: 13, fontWeight: "500" },
  chipTextActive: { color: "#fff" },
  input: {
    color: "#fff",
    backgroundColor: "#1A1F29",
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 8,
    fontSize: 16,
  },
  relative: { fontSize: 12, marginTop: 6, fontStyle: "italic" },
});
