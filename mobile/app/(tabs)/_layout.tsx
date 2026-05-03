import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";

export default function TabsLayout() {
  const { t } = useTranslation();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: "#0F1115" },
        headerTintColor: "#fff",
        headerTitleStyle: { fontWeight: "700" },
        tabBarStyle: {
          backgroundColor: "#0F1115",
          borderTopColor: "#1A1F29",
          borderTopWidth: 1,
        },
        tabBarActiveTintColor: "#3B82F6",
        tabBarInactiveTintColor: "#5C6373",
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t("tabs.plan"),
          headerTitle: t("appName"),
          tabBarIcon: ({ color, size }) => <Ionicons name="navigate" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="history"
        options={{
          title: t("tabs.history"),
          headerTitle: t("history.title"),
          tabBarIcon: ({ color, size }) => <Ionicons name="time-outline" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t("tabs.profile"),
          headerTitle: t("profile.title"),
          tabBarIcon: ({ color, size }) => <Ionicons name="person-circle-outline" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
