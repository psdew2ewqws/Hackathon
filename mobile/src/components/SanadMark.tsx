import { StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

interface Props {
  tone?: "light" | "dark";
}

/**
 * Approximation of the Sanad (سند) logo: an Arabic wordmark with a calligraphic
 * flourish on top and the SANAD wordmark below. This is a mock — not the real
 * brand asset — but it reads as Sanad at glance.
 */
export function SanadMark({ tone = "light" }: Props) {
  const stroke = tone === "light" ? "#A6E5D5" : "#0F5F50";
  const wordColor = tone === "light" ? "#A6E5D5" : "#0F5F50";
  return (
    <View style={styles.wrap}>
      {/* Calligraphic flourish above the wordmark */}
      <Svg width={42} height={10} viewBox="0 0 42 10" style={styles.flourish}>
        <Path
          d="M2 7 C 8 1, 14 1, 20 5 S 32 9, 40 3"
          stroke={stroke}
          strokeWidth={1.6}
          strokeLinecap="round"
          fill="none"
        />
      </Svg>
      <Text style={[styles.arabic, { color: wordColor }]}>سند</Text>
      <Text style={[styles.latin, { color: wordColor }]}>SANAD</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center" },
  flourish: { marginBottom: -2 },
  arabic: { fontSize: 18, fontWeight: "600", lineHeight: 22, letterSpacing: 1 },
  latin: { fontSize: 8, fontWeight: "700", letterSpacing: 2.5, marginTop: -2 },
});
