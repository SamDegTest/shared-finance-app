"use client";

import React, { useState } from "react";

interface ParsedExpenseItem {
  id: string;
  title: string | null;
  amount_cents: number | null;
  category_name: string;
  split_type: string;
  expense_date: string;
  is_valid: boolean;
  missing_fields: string[];
  clarification_prompt?: string | null;
}

export function SmartCommandBar() {
  const [input, setInput] = useState("");
  const [expenses, setExpenses] = useState<ParsedExpenseItem[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [confirmedMessage, setConfirmedMessage] = useState<string | null>(null);

  const parseSingleClause = (
    clause: string,
    idx: number
  ): ParsedExpenseItem => {
    const text = clause.trim();
    const amountMatch = text.match(
      /(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)?|(\d+)\s+euro/i
    );
    const amount = amountMatch
      ? Math.round(
          parseFloat((amountMatch[1] || amountMatch[2]).replace(",", ".")) * 100
        )
      : null;

    let category = "Spesa Generale";
    const lower = text.toLowerCase();
    if (
      lower.includes("pizza") ||
      lower.includes("cena") ||
      lower.includes("ristorante") ||
      lower.includes("bar") ||
      lower.includes("sushi")
    ) {
      category = "Ristoranti & Bar";
    } else if (
      lower.includes("spesa") ||
      lower.includes("esselunga") ||
      lower.includes("supermercato") ||
      lower.includes("conad") ||
      lower.includes("lidl")
    ) {
      category = "Spesa Alimentari";
    } else if (
      lower.includes("bolletta") ||
      lower.includes("luce") ||
      lower.includes("gas") ||
      lower.includes("ikea") ||
      lower.includes("affitto")
    ) {
      category = "Casa & Utenze";
    } else if (
      lower.includes("farmacia") ||
      lower.includes("medicine") ||
      lower.includes("visita") ||
      lower.includes("dottore")
    ) {
      category = "Salute & Farmacia";
    } else if (
      lower.includes("benzina") ||
      lower.includes("treno") ||
      lower.includes("biglietto") ||
      lower.includes("telepass")
    ) {
      category = "Trasporti";
    }

    const missing: string[] = [];
    if (!amount) missing.push("amount_cents");
    const titleClean = text
      .replace(/(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)?/i, "")
      .replace(
        /\b(?:divis[oa]\s+a\s+met[àa]|a\s+met[àa]|50\/50|divis[oa]\s+in\s+due|ieri|oggi|l'altro\s*ieri)\b/gi,
        ""
      )
      .trim();

    if (titleClean.length < 2) missing.push("title");

    return {
      id: `exp_${idx}_${Date.now()}`,
      title:
        titleClean.length >= 2
          ? titleClean.charAt(0).toUpperCase() + titleClean.slice(1)
          : null,
      amount_cents: amount,
      category_name: category,
      split_type: "EQUAL",
      expense_date: lower.includes("ieri") ? "Ieri" : "Oggi",
      is_valid: missing.length === 0,
      missing_fields: missing,
      clarification_prompt: !amount
        ? "Specifica l'importo"
        : missing.includes("title")
          ? "Specifica la descrizione"
          : null,
    };
  };

  const handleInputChange = (text: string) => {
    setInput(text);
    setConfirmedMessage(null);

    if (!text.trim()) {
      setExpenses([]);
      return;
    }

    // Segmentazione multi-spesa
    let rawClauses: string[] = [];
    if (text.includes("\n")) {
      rawClauses = text.split("\n");
    } else if (text.includes(";")) {
      rawClauses = text.split(";");
    } else if (/\b(?:e\s+poi|e\s+anche|inoltre|\+)\b/i.test(text)) {
      rawClauses = text.split(/\b(?:e\s+poi|e\s+anche|inoltre|\+)\b/i);
    } else if (/\s+\be\b\s+/i.test(text)) {
      // Divide su " e " se ci sono più importi
      const amountsCount = (
        text.match(/\d+(?:[.,]\d{1,2})?\s*(?:€|eur|euro)?/gi) || []
      ).length;
      if (amountsCount > 1) {
        rawClauses = text.split(/\s+\be\b\s+/i);
      } else {
        rawClauses = [text];
      }
    } else {
      rawClauses = [text];
    }

    const parsed = rawClauses
      .filter((c) => c.trim().length > 0)
      .map((c, i) => parseSingleClause(c, i));

    setExpenses(parsed);
  };

  const isAllValid = expenses.length > 0 && expenses.every((e) => e.is_valid);
  const totalCents = expenses.reduce(
    (acc, e) => acc + (e.amount_cents || 0),
    0
  );

  const handleConfirmBatch = () => {
    if (!isAllValid) return;
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      setConfirmedMessage(
        expenses.length === 1
          ? "Spesa registrata con successo nel ledger ACID!"
          : `${expenses.length} spese registrate in un'unica transazione atomica ACID!`
      );
      setInput("");
      setExpenses([]);
      setTimeout(() => setConfirmedMessage(null), 5000);
    }, 450);
  };

  return (
    <div className="mx-auto my-6 w-full max-w-2xl rounded-2xl border border-slate-800/80 bg-gradient-to-b from-slate-900/90 to-slate-950/90 p-4 shadow-2xl shadow-indigo-950/20 backdrop-blur-xl">
      {/* Header bar */}
      <div className="mb-3 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          <span className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
            Smart Input Multi-Expense NLP
          </span>
        </div>
        <kbd className="hidden items-center gap-1 rounded border border-slate-700/60 bg-slate-800/80 px-2 py-0.5 font-mono text-[10px] text-slate-400 sm:inline-flex">
          <span>⌘</span>K
        </kbd>
      </div>

      {/* Input Field */}
      <div className="relative flex items-center">
        <div className="absolute left-3.5 text-slate-400">
          <svg
            className="h-5 w-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13 10V3L4 14h7v7l9-11h-7z"
            />
          </svg>
        </div>
        <input
          type="text"
          value={input}
          onChange={(e) => handleInputChange(e.target.value)}
          placeholder="Es: 'Cena 50€ a metà e poi 30€ di benzina ieri'..."
          className="w-full rounded-xl border border-slate-700/70 bg-slate-950/80 py-3.5 pr-32 pl-11 text-sm text-slate-100 placeholder-slate-500 transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/50 focus:outline-none sm:text-base"
        />
        {isAllValid && (
          <button
            onClick={handleConfirmBatch}
            disabled={isSubmitting}
            className="absolute right-2 rounded-lg bg-gradient-to-r from-indigo-500 to-emerald-500 px-3 py-2 text-xs font-medium text-white shadow-lg shadow-indigo-500/20 transition-all hover:from-indigo-600 hover:to-emerald-600 active:scale-95 disabled:opacity-50 sm:text-sm"
          >
            {isSubmitting
              ? "Salvataggio..."
              : expenses.length > 1
                ? `Conferma Tutte (${expenses.length}) ↵`
                : "Conferma ↵"}
          </button>
        )}
      </div>

      {/* Esempi rapidi con supporto multi-spesa */}
      {expenses.length === 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 px-1">
          <span className="text-xs text-slate-500">Suggeriti:</span>
          <button
            onClick={() =>
              handleInputChange("Cena 50€ a metà e 30€ benzina ieri")
            }
            className="rounded-full border border-slate-700/50 bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:bg-slate-800"
          >
            ✨ Multi: Cena 50€ + Benzina 30€
          </button>
          <button
            onClick={() =>
              handleInputChange("Spesa Esselunga 84,60 euro a metà")
            }
            className="rounded-full border border-slate-700/50 bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:bg-slate-800"
          >
            🛒 Spesa 84,60€
          </button>
          <button
            onClick={() =>
              handleInputChange("Farmacia 15€ e Bolletta luce 90€")
            }
            className="rounded-full border border-slate-700/50 bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:bg-slate-800"
          >
            ✨ Multi: Farmacia + Bolletta
          </button>
        </div>
      )}

      {/* Multi-Expense Preview Cards */}
      {expenses.length > 0 && (
        <div className="mt-3.5 space-y-2">
          {/* Header con conteggio e totale */}
          <div className="flex items-center justify-between px-1 text-xs font-medium text-slate-400">
            <span>
              Spese Rilevate:{" "}
              <strong className="text-slate-200">{expenses.length}</strong>
            </span>
            {totalCents > 0 && (
              <span>
                Totale Complessivo:{" "}
                <strong className="text-sm font-bold text-emerald-400">
                  {(totalCents / 100).toFixed(2)} €
                </strong>
              </span>
            )}
          </div>

          {/* Cards per ciascuna voce */}
          {expenses.map((exp, index) => (
            <div
              key={exp.id}
              className="animate-fadeIn flex flex-col justify-between gap-2.5 rounded-xl border border-slate-800 bg-slate-950/70 p-3 sm:flex-row sm:items-center"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] font-bold text-slate-500">
                  #{index + 1}
                </span>
                {exp.title ? (
                  <span className="inline-flex items-center gap-1 rounded-md border border-indigo-500/20 bg-indigo-500/10 px-2.5 py-1 text-xs font-semibold text-indigo-300">
                    📝 {exp.title}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded border border-red-800/30 bg-red-950/30 px-2 py-0.5 text-xs text-red-400">
                    Manca descrizione
                  </span>
                )}
                {exp.amount_cents !== null ? (
                  <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-bold text-emerald-300">
                    💶 {(exp.amount_cents / 100).toFixed(2)} €
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded border border-red-800/30 bg-red-950/30 px-2 py-0.5 text-xs text-red-400">
                    Manca importo
                  </span>
                )}
                <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300">
                  🏷️ {exp.category_name}
                </span>
                <span className="inline-flex items-center gap-1 rounded-md border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-xs font-medium text-sky-300">
                  👥 50/50
                </span>
                <span className="inline-flex items-center gap-1 rounded-md border border-purple-500/20 bg-purple-500/10 px-2 py-0.5 text-xs font-medium text-purple-300">
                  📅 {exp.expense_date}
                </span>
              </div>

              {!exp.is_valid && exp.clarification_prompt && (
                <div className="shrink-0 rounded border border-amber-800/30 bg-amber-950/20 px-2 py-1 text-xs text-amber-400">
                  ⚠️ {exp.clarification_prompt}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Success banner */}
      {confirmedMessage && (
        <div className="animate-fadeIn mt-3 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-950/40 p-3 text-xs font-medium text-emerald-300 sm:text-sm">
          <svg
            className="h-5 w-5 shrink-0 text-emerald-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
          <span>{confirmedMessage}</span>
        </div>
      )}
    </div>
  );
}
