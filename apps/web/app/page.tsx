"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/app" : "/login");
  }, [router]);
  return <p className="muted" style={{ padding: 32 }}>Opening Business Brain…</p>;
}
