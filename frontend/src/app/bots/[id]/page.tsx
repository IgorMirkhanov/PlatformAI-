import { redirect } from "next/navigation";

interface BotIndexPageProps {
  params: Promise<{ id: string }>;
}

export default async function BotIndexPage({ params }: BotIndexPageProps) {
  const { id } = await params;
  redirect(`/bots/${id}/settings`);
}
