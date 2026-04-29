import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { placesAutocomplete, placeDetails, type PlaceDetails, type Prediction } from "../services/api";

const DEBOUNCE_MS = 300;

interface Props {
  label: string;
  placeholder?: string;
  value: PlaceDetails | null;
  onChange: (place: PlaceDetails | null) => void;
}

function newSessionToken(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function PlaceSearchInput({ label, placeholder, value, onChange }: Props) {
  const [text, setText] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sessionTokenRef = useRef(newSessionToken());
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset session token whenever a place is committed (Google billing model)
  const commitPlace = async (p: Prediction) => {
    setOpen(false);
    setText(p.mainText);
    setLoading(true);
    setError(null);
    try {
      const details = await placeDetails(p.placeId, sessionTokenRef.current);
      onChange(details);
      sessionTokenRef.current = newSessionToken();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text || text === value?.name) {
      setPredictions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await placesAutocomplete(text, sessionTokenRef.current);
        setPredictions(list);
        setOpen(true);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [text, value?.name]);

  const showClear = useMemo(() => Boolean(value), [value]);

  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={(t) => {
            setText(t);
            if (value) onChange(null); // user is editing — invalidate previous selection
          }}
          placeholder={placeholder}
          placeholderTextColor="#5C6373"
          autoCorrect={false}
          autoCapitalize="none"
          onFocus={() => predictions.length > 0 && setOpen(true)}
        />
        {loading && <ActivityIndicator color="#8B95A8" style={{ marginLeft: 8 }} />}
        {showClear && !loading && (
          <Pressable
            onPress={() => {
              setText("");
              onChange(null);
              setPredictions([]);
              setOpen(false);
            }}
          >
            <Text style={styles.clear}>×</Text>
          </Pressable>
        )}
      </View>
      {error && <Text style={styles.error}>{error}</Text>}
      {open && predictions.length > 0 && (
        <View style={styles.dropdown}>
          {predictions.slice(0, 5).map((p) => (
            <Pressable key={p.placeId} style={styles.suggestion} onPress={() => commitPlace(p)}>
              <Text style={styles.suggestionMain}>{p.mainText}</Text>
              {p.secondaryText && <Text style={styles.suggestionSecondary}>{p.secondaryText}</Text>}
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: 8 },
  label: { color: "#8B95A8", fontSize: 13, marginTop: 12, marginBottom: 4 },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1A1F29",
    borderRadius: 8,
    paddingHorizontal: 14,
  },
  input: { flex: 1, color: "#fff", paddingVertical: 12, fontSize: 16 },
  clear: { color: "#5C6373", fontSize: 22, paddingHorizontal: 8 },
  dropdown: {
    marginTop: 4,
    backgroundColor: "#1A1F29",
    borderRadius: 8,
    overflow: "hidden",
  },
  suggestion: {
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#0F1115",
  },
  suggestionMain: { color: "#fff", fontSize: 15 },
  suggestionSecondary: { color: "#8B95A8", fontSize: 12, marginTop: 2 },
  error: { color: "#F87171", fontSize: 12, marginTop: 4 },
});
