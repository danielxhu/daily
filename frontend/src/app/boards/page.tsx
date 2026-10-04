"use client";

import { BoardsView } from "@/components/BoardsView";
import { useT } from "@/lib/i18n";

/** Board admin: the modules inside each board and which source belongs to which.
 * The notes themselves live on Knowledge, as a pile of cards. */
export default function BoardsPage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-5">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">
          {t("page.boards.title")}
        </h1>
        <p className="mt-1 text-sm text-muted">{t("page.boards.subtitle")}</p>
      </header>
      <div className="py-8">
        <BoardsView />
      </div>
    </div>
  );
}
