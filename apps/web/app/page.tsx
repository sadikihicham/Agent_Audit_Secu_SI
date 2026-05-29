import { redirect } from "next/navigation";

// Root → dashboard (middleware handles unauthenticated redirect to /login)
export default function Home() {
  redirect("/dashboard");
}
