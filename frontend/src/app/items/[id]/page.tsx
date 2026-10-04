import { ItemDetailView } from "@/components/ItemDetailView";
import { STATIC_ITEM_IDS } from "@/lib/static-params";

export function generateStaticParams() {
  return STATIC_ITEM_IDS.map((id) => ({ id }));
}

export default function ItemPage({ params }: { params: { id: string } }) {
  return (
    <section className="py-2">
      <ItemDetailView itemId={params.id} />
    </section>
  );
}
