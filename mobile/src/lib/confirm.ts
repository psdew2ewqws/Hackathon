import { Alert, Platform } from "react-native";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel: string;
  cancelLabel: string;
  destructive?: boolean;
}

/**
 * Cross-platform confirm dialog. react-native-web's Alert.alert silently
 * drops the buttons array (it only renders the title/message via window.alert),
 * so destructive actions never fire on web. Use window.confirm there.
 */
export function confirmAction(opts: ConfirmOptions, onConfirm: () => void): void {
  if (Platform.OS === "web") {
    const text = opts.message ? `${opts.title}\n\n${opts.message}` : opts.title;
    if (typeof window !== "undefined" && window.confirm(text)) onConfirm();
    return;
  }
  Alert.alert(opts.title, opts.message, [
    { text: opts.cancelLabel, style: "cancel" },
    { text: opts.confirmLabel, style: opts.destructive ? "destructive" : "default", onPress: onConfirm },
  ]);
}
