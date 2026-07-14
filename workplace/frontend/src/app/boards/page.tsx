import { redirect } from "next/navigation";

// Boards browse moved into the Knowledge page (M12.4) — keep old links working.
export default function BoardsPage() {
  redirect("/knowledge");
}
