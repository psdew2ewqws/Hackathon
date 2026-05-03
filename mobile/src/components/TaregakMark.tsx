import { View, StyleSheet } from "react-native";
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from "react-native-svg";

interface Props {
  size?: number;
}

/**
 * Brand mark: two route waypoints (origin + destination) connected by a curved
 * dashed path. Mirrors the actual app behavior — pick A, pick B, we route.
 * Built from primitives so it scales crisply on every platform.
 */
export function TaregakMark({ size = 96 }: Props) {
  const w = size;
  const h = size * 0.62;
  return (
    <View style={[styles.wrap, { width: w, height: h }]}>
      <Svg width={w} height={h} viewBox="0 0 96 60">
        <Defs>
          <LinearGradient id="route" x1="0" y1="1" x2="1" y2="0">
            <Stop offset="0" stopColor="#3B82F6" stopOpacity="1" />
            <Stop offset="1" stopColor="#EF4444" stopOpacity="1" />
          </LinearGradient>
        </Defs>

        {/* Curved route path connecting the two waypoints */}
        <Path
          d="M10 46 C 28 46, 36 32, 50 28 S 78 18, 86 14"
          stroke="url(#route)"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeDasharray="3 5"
          fill="none"
          opacity={0.85}
        />

        {/* Origin halo + dot */}
        <Circle cx={10} cy={46} r={9} fill="#3B82F6" opacity={0.18} />
        <Circle cx={10} cy={46} r={5} fill="#3B82F6" />
        <Circle cx={10} cy={46} r={1.6} fill="#0F1115" />

        {/* Destination halo + dot */}
        <Circle cx={86} cy={14} r={9} fill="#EF4444" opacity={0.18} />
        <Circle cx={86} cy={14} r={5} fill="#EF4444" />
        <Circle cx={86} cy={14} r={1.6} fill="#0F1115" />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center" },
});
