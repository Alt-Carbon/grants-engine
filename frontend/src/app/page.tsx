import { redirect } from "next/navigation";
import { LANDING_ROUTE } from "@/lib/deployment";

export default function Home() {
  redirect(LANDING_ROUTE);
}
