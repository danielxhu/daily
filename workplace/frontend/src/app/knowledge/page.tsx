"use client";

import { useT } from "@/lib/i18n";
import { BoardsView } from "@/components/BoardsView";
import { KnowledgeView } from "@/components/KnowledgeView";

/** Knowledge (zh: 知识库) — the operator's verified knowledge base (M12.4).
 * Two surfaces on one page: browse by topic board (each board = its verified
 * facts + notes + AI summary — promoted here from the old footer-level Boards
 * page), and the "ask daily" conversation over the same fact layer. */
export default function KnowledgePage() {
  const t = useT();
  return (
    <div>
      <header className="border-b border-line pb-5">
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">{t("page.knowledge.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("page.knowledge.subtitle")}
        </p>
      </header>
      <div className="space-y-10 py-8">
        <section aria-labelledby="knowledge-boards" className="space-y-5">
          <div className="section-head">
            <h2 id="knowledge-boards" className="section-title">
              {t("knowledge.section.boards")}
            </h2>
            <span aria-hidden="true" className="section-rule" />
          </div>
          <BoardsView />
        </section>
        <section aria-labelledby="knowledge-ask" className="space-y-5">
          <div className="section-head">
            <h2 id="knowledge-ask" className="section-title">
              {t("knowledge.section.ask")}
            </h2>
            <span aria-hidden="true" className="section-rule" />
          </div>
          <KnowledgeView />
        </section>
      </div>
    </div>
  );
}
