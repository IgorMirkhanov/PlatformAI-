"use client";



import { useEffect } from "react";

import { useParams, useRouter } from "next/navigation";



export default function ChannelsAgentIndexPage() {

  const params = useParams<{ id: string }>();

  const router = useRouter();



  useEffect(() => {

    router.replace(`/dashboard/channels?botId=${encodeURIComponent(params.id)}`);

  }, [params.id, router]);



  return null;

}

