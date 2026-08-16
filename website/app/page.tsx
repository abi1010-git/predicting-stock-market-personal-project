import type { Metadata } from "next";
import { Dashboard } from "./Dashboard";

export const metadata: Metadata = {
  title: "SignalFive — Five-session market research",
  description: "A transparent machine-learning research system exploring whether SPY will close higher five trading sessions ahead.",
};

export default function Home() {
  return <Dashboard />;
}
