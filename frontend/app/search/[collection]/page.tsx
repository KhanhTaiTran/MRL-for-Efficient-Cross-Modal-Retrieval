import { redirect } from "next/navigation";
export default async function Page({
  params,
}: {
  params: Promise<{ collection: string }>;
}) {
  const { collection } = await params;
  redirect(`/search?category=${encodeURIComponent(collection)}`);
}
