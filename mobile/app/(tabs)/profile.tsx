import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

import { PoweredBy } from "../../src/components/PoweredBy";
import { confirmAction } from "../../src/lib/confirm";
import { useHistory } from "../../src/store/history";
import { useLastRoute } from "../../src/store/lastRoute";
import { useProfile } from "../../src/store/profile";

export default function ProfileTab() {
  const { t } = useTranslation();
  const profile = useProfile((s) => s.profile);
  const signOut = useProfile((s) => s.signOut);
  const clearHistory = useHistory((s) => s.clear);
  const saveLastRoute = useLastRoute((s) => s.save);

  const onLogout = () => {
    confirmAction(
      {
        title: t("profile.logoutConfirmTitle"),
        message: t("profile.logoutConfirmBody"),
        confirmLabel: t("profile.logout"),
        cancelLabel: t("common.cancel"),
        destructive: true,
      },
      async () => {
        await clearHistory();
        await saveLastRoute({ origin: null, dest: null });
        await signOut();
      },
    );
  };

  const switchLanguage = async () => {
    const next = i18n.language?.startsWith("ar") ? "en" : "ar";
    await i18n.changeLanguage(next);
  };

  if (!profile) return null;

  const initials = profile.name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <View style={styles.flex}>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.identityCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials || "?"}</Text>
          </View>
          <Text style={styles.name}>{profile.name}</Text>
          <Text style={styles.phone}>{profile.phone}</Text>
        </View>

        <Text style={styles.sectionLabel}>{t("profile.preferences")}</Text>
        <Pressable style={styles.row} onPress={switchLanguage}>
          <Ionicons name="language-outline" size={20} color="#A8B3C5" />
          <Text style={styles.rowLabel}>{t("profile.language")}</Text>
          <Text style={styles.rowValue}>{i18n.language?.startsWith("ar") ? "العربية" : "English"}</Text>
          <Ionicons name="chevron-forward" size={18} color="#5C6373" />
        </Pressable>

        <Text style={styles.sectionLabel}>{t("profile.account")}</Text>
        <Pressable style={styles.row} onPress={onLogout}>
          <Ionicons name="log-out-outline" size={20} color="#F87171" />
          <Text style={[styles.rowLabel, { color: "#F87171" }]}>{t("profile.logout")}</Text>
        </Pressable>
      </ScrollView>
      <PoweredBy />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: "#0F1115" },
  container: { flex: 1 },
  content: { padding: 20, paddingBottom: 32 },
  identityCard: {
    backgroundColor: "#1A1F29",
    borderRadius: 16,
    padding: 24,
    alignItems: "center",
    marginBottom: 28,
  },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: "#3B82F6",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
  },
  avatarText: { color: "#fff", fontSize: 28, fontWeight: "700" },
  name: { color: "#fff", fontSize: 20, fontWeight: "700" },
  phone: { color: "#8B95A8", fontSize: 14, marginTop: 4 },
  sectionLabel: {
    color: "#5C6373",
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginBottom: 8,
    marginTop: 16,
    paddingHorizontal: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1A1F29",
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderRadius: 10,
    gap: 12,
  },
  rowLabel: { flex: 1, color: "#fff", fontSize: 15 },
  rowValue: { color: "#8B95A8", fontSize: 13 },
});
