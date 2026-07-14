"use client";

import { useParams } from "next/navigation";

import { ItemDetailView } from "@/components/ItemDetailView";

export default function ItemPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params?.id === "string" ? params.id : "";
  return (
    <section className="py-2">
      <ItemDetailView itemId={id} />
    </section>
  );
}
