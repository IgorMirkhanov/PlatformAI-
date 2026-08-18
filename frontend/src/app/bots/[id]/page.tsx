import { redirect } from "next/navigation";

interface BotIndexPageProps {
  params: { id: string };
}

export default function BotIndexPage({ params }: BotIndexPageProps) {
  redirect(`/bots/${params.id}/settings`);
}
