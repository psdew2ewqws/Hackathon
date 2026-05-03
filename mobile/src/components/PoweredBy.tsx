import { StyleSheet, Text, View } from "react-native";

export function PoweredBy() {
  return (
    <View style={styles.wrap}>
      <Text style={styles.text}>
        Powered by <Text style={styles.brand}>9xAI</Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", paddingVertical: 16 },
  text: { color: "#5C6373", fontSize: 11, letterSpacing: 0.5 },
  brand: { color: "#8B95A8", fontWeight: "700" },
});
