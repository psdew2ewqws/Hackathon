import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useTranslation } from "react-i18next";
import { SafeAreaView } from "react-native-safe-area-context";

import { PoweredBy } from "../../src/components/PoweredBy";
import { SanadAuthSheet, type SanadIdentity } from "../../src/components/SanadAuthSheet";
import { SanadButton } from "../../src/components/SanadButton";
import { TaregakMark } from "../../src/components/TaregakMark";
import { useProfile } from "../../src/store/profile";

const MOCK_SANAD_IDENTITY: SanadIdentity = {
  name: "Omar Al-Hourani",
  phone: "+962 79 123 4567",
  nationalId: "9871234567",
};

const PHONE_RE = /^[+\d][\d\s-]{6,}$/;

export default function LoginScreen() {
  const { t } = useTranslation();
  const signIn = useProfile((s) => s.signIn);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("+962 ");
  const [submitting, setSubmitting] = useState(false);
  const [sanadOpen, setSanadOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = name.trim().length >= 2 && PHONE_RE.test(phone.trim());

  const onSubmit = async () => {
    if (!valid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await signIn({ name, phone });
      // AuthGate in root layout redirects to (tabs) once profile is set.
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const onSanadApprove = async () => {
    try {
      await signIn({ name: MOCK_SANAD_IDENTITY.name, phone: MOCK_SANAD_IDENTITY.phone });
      setSanadOpen(false);
    } catch (e) {
      setError((e as Error).message);
      setSanadOpen(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.hero}>
            <TaregakMark size={120} />
            <Text style={styles.brand}>Taregak</Text>
            <View style={styles.arabicRow}>
              <View style={styles.divider} />
              <Text style={styles.arabic}>طريقك</Text>
              <View style={styles.divider} />
            </View>
            <Text style={styles.tagline}>{t("auth.tagline")}</Text>
          </View>

          <View style={styles.form}>
            <SanadButton
              label={t("auth.sanadButton")}
              onPress={() => setSanadOpen(true)}
              loading={sanadOpen}
            />

            <View style={styles.orRow}>
              <View style={styles.orLine} />
              <Text style={styles.orText}>{t("auth.or")}</Text>
              <View style={styles.orLine} />
            </View>

            <Text style={styles.label}>{t("auth.nameLabel")}</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder={t("auth.namePlaceholder")}
              placeholderTextColor="#5C6373"
              autoCapitalize="words"
              autoCorrect={false}
              returnKeyType="next"
            />

            <Text style={styles.label}>{t("auth.phoneLabel")}</Text>
            <TextInput
              style={styles.input}
              value={phone}
              onChangeText={setPhone}
              placeholder="+962 7X XXX XXXX"
              placeholderTextColor="#5C6373"
              keyboardType="phone-pad"
              returnKeyType="done"
              onSubmitEditing={onSubmit}
            />

            {error && <Text style={styles.error}>{error}</Text>}

            <Pressable
              style={[styles.button, (!valid || submitting) && styles.buttonDisabled]}
              onPress={onSubmit}
              disabled={!valid || submitting}
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.buttonText}>{t("auth.continue")}</Text>
              )}
            </Pressable>

            <Text style={styles.disclaimer}>{t("auth.disclaimer")}</Text>
          </View>
        </ScrollView>

        <PoweredBy />
      </KeyboardAvoidingView>

      <SanadAuthSheet
        visible={sanadOpen}
        identity={MOCK_SANAD_IDENTITY}
        onApprove={onSanadApprove}
        onClose={() => setSanadOpen(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#0F1115" },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, padding: 24, justifyContent: "center" },
  hero: { alignItems: "center", marginBottom: 36 },
  brand: {
    color: "#fff",
    fontSize: 38,
    fontWeight: "800",
    letterSpacing: -1,
    marginTop: 18,
  },
  arabicRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 8,
    gap: 10,
  },
  divider: { width: 22, height: 1, backgroundColor: "#2A3343" },
  arabic: { color: "#A8B3C5", fontSize: 16, fontWeight: "500" },
  tagline: { color: "#8B95A8", fontSize: 15, marginTop: 14, textAlign: "center" },
  form: { gap: 4 },
  orRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 22,
    marginBottom: 6,
    gap: 12,
  },
  orLine: { flex: 1, height: 1, backgroundColor: "#1F2530" },
  orText: { color: "#5C6373", fontSize: 12, fontWeight: "600", letterSpacing: 1.2 },
  label: { color: "#8B95A8", fontSize: 13, marginTop: 12, marginBottom: 6 },
  input: {
    backgroundColor: "#1A1F29",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 14,
    color: "#fff",
    fontSize: 16,
  },
  button: {
    marginTop: 24,
    backgroundColor: "#3B82F6",
    paddingVertical: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonDisabled: { backgroundColor: "#2A3343" },
  buttonText: { color: "#fff", fontWeight: "700", fontSize: 16, letterSpacing: 0.3 },
  disclaimer: { color: "#5C6373", fontSize: 11, textAlign: "center", marginTop: 14 },
  error: { color: "#F87171", fontSize: 13, marginTop: 8 },
});
