/* eslint-disable @next/next/no-img-element */
// Logo Infinity Holding (monogramme or, fond transparent) → posé sur une pastille blanche
// pour rester lisible aussi bien en thème clair qu'en thème sombre.
export function Logo({ className = "h-8" }: { className?: string }) {
  return (
    <span className="inline-flex items-center rounded-lg bg-white px-2 py-1 ring-1 ring-black/5">
      <img src="/logo.png" alt="Infinity Holding — GuardianOps AI" className={`${className} w-auto`} />
    </span>
  );
}
