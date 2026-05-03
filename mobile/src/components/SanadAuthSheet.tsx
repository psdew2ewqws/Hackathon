import { useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { SanadMark } from "./SanadMark";

const SANAD_GREEN = "#0F5F50";

export interface SanadIdentity {
  name: string;
  phone: string;
  nationalId: string;
}

interface Props {
  visible: boolean;
  identity: SanadIdentity;
  onApprove: () => void;
  onClose: () => void;
}

type Stage = "connecting" | "review" | "authorizing";

const CONNECT_MS = 1100;
const AUTHORIZE_MS = 900;

export function SanadAuthSheet({ visible, identity, onApprove, onClose }: Props) {
  const [stage, setStage] = useState<Stage>("connecting");

  useEffect(() => {
    if (!visible) return;
    setStage("connecting");
    const t = setTimeout(() => setStage("review"), CONNECT_MS);
    return () => clearTimeout(t);
  }, [visible]);

  const handleApprove = () => {
    setStage("authorizing");
    setTimeout(onApprove, AUTHORIZE_MS);
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={stage === "review" ? onClose : undefined}
    >
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <SanadMark tone="dark" />
          </View>

          {stage === "connecting" && <ConnectingView />}
          {stage === "review" && (
            <ReviewView identity={identity} onApprove={handleApprove} onCancel={onClose} />
          )}
          {stage === "authorizing" && <AuthorizingView />}
        </View>
      </View>
    </Modal>
  );
}

function ConnectingView() {
  return (
    <View style={styles.body}>
      <ActivityIndicator color={SANAD_GREEN} size="large" />
      <Text style={styles.headline}>Connecting to Sanad…</Text>
      <Text style={styles.sub}>Securely verifying your identity.</Text>
    </View>
  );
}

function AuthorizingView() {
  return (
    <View style={styles.body}>
      <ActivityIndicator color={SANAD_GREEN} size="large" />
      <Text style={styles.headline}>Signing you in…</Text>
    </View>
  );
}

function ReviewView({
  identity,
  onApprove,
  onCancel,
}: {
  identity: SanadIdentity;
  onApprove: () => void;
  onCancel: () => void;
}) {
  return (
    <View style={styles.body}>
      <Text style={styles.headline}>Authorize Taregak</Text>
      <Text style={styles.sub}>Taregak is requesting access to:</Text>

      <View style={styles.scopeBox}>
        <ScopeRow label="Full name" value={identity.name} />
        <ScopeRow label="Phone number" value={identity.phone} />
        <ScopeRow label="National ID" value={maskNationalId(identity.nationalId)} />
      </View>

      <Text style={styles.disclaimer}>
        Only the fields above will be shared. You can revoke access at any time from your Sanad
        account.
      </Text>

      <View style={styles.actions}>
        <Pressable style={[styles.btn, styles.btnGhost]} onPress={onCancel}>
          <Text style={[styles.btnText, { color: "#3A4253" }]}>Cancel</Text>
        </Pressable>
        <Pressable style={[styles.btn, styles.btnPrimary]} onPress={onApprove}>
          <Text style={styles.btnText}>Approve</Text>
        </Pressable>
      </View>
    </View>
  );
}

function ScopeRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.scopeRow}>
      <Text style={styles.scopeLabel}>{label}</Text>
      <Text style={styles.scopeValue}>{value}</Text>
    </View>
  );
}

function maskNationalId(id: string): string {
  if (id.length <= 4) return id;
  return `••••••${id.slice(-4)}`;
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
  },
  sheet: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: "#fff",
    borderRadius: 18,
    overflow: "hidden",
  },
  header: {
    paddingVertical: 24,
    backgroundColor: "#F1F8F5",
    alignItems: "center",
    justifyContent: "center",
    borderBottomWidth: 1,
    borderBottomColor: "#E1EDE7",
  },
  body: {
    padding: 24,
    alignItems: "center",
    gap: 8,
  },
  headline: { fontSize: 20, fontWeight: "700", color: "#0F1115", marginTop: 8 },
  sub: { fontSize: 14, color: "#5C6373", textAlign: "center" },
  scopeBox: {
    width: "100%",
    backgroundColor: "#F4F6F8",
    borderRadius: 12,
    padding: 14,
    marginTop: 14,
    gap: 10,
  },
  scopeRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  scopeLabel: { color: "#5C6373", fontSize: 13 },
  scopeValue: { color: "#0F1115", fontSize: 14, fontWeight: "600" },
  disclaimer: {
    color: "#8B95A8",
    fontSize: 11,
    textAlign: "center",
    marginTop: 12,
    lineHeight: 16,
  },
  actions: { flexDirection: "row", gap: 10, marginTop: 18, width: "100%" },
  btn: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: "center",
  },
  btnGhost: { backgroundColor: "#F0F2F5" },
  btnPrimary: { backgroundColor: SANAD_GREEN },
  btnText: { color: "#fff", fontWeight: "700", fontSize: 15 },
});
