import { SmartCommandBar } from "@/components/smart-input/SmartCommandBar";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-950 font-sans text-slate-100 selection:bg-indigo-500 selection:text-white">
      {/* Navbar Header */}
      <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-slate-950/60 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-emerald-400 font-bold text-white shadow-lg shadow-indigo-500/20">
              S
            </div>
            <span className="text-base font-semibold tracking-tight text-white">
              shared-finance-app
            </span>
            <span className="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-[11px] font-medium text-indigo-400">
              v0.1.0-alpha
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs font-medium text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
              Ledger ACID Sync
            </span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center px-4 py-8 sm:px-6 sm:py-12">
        {/* Hero Title */}
        <div className="mx-auto mb-6 max-w-xl text-center">
          <h1 className="bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-3xl font-extrabold tracking-tight text-transparent sm:text-4xl">
            Gestione Finanziaria di Coppia
          </h1>
          <p className="mt-2 text-sm text-slate-400 sm:text-base">
            Inserisci le spese parlando naturalmente. Il motore LLM calcola la
            ripartizione 50/50 e aggiorna il bilancio in tempo reale.
          </p>
        </div>

        {/* Smart Command Bar Component (SHBC-28) */}
        <SmartCommandBar />

        {/* Features highlight grid */}
        <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-4">
            <div className="mb-1 text-lg text-indigo-400">
              ⚡ 0-Friction OCR
            </div>
            <div className="text-xs leading-relaxed text-slate-400">
              Scansiona scontrini con Vision AI e quadratura al centesimo
              garantita.
            </div>
          </div>
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-4">
            <div className="mb-1 text-lg text-emerald-400">
              ⚖️ Net Debt Balance
            </div>
            <div className="text-xs leading-relaxed text-slate-400">
              Algoritmo di debito netto istantaneo per chi deve dare quanto e a
              chi.
            </div>
          </div>
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-4">
            <div className="mb-1 text-lg text-amber-400">🧠 Smart Input</div>
            <div className="text-xs leading-relaxed text-slate-400">
              Dettatura naturale con mapping automatico di categorie e split.
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
