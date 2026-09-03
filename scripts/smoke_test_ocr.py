#!/usr/bin/env python3
"""Script di Smoke Test per verificare Tesseract OCR, spaCy e Microsoft Presidio all'avvio del container.

Uso:
  python scripts/smoke_test_ocr.py
"""

import sys


def main() -> int:
    print("================================================================")
    print("🔍 SMOKE TEST: Infrastruttura OCR & Microsoft Presidio SDK")
    print("================================================================")

    # 1. Verifica Tesseract OCR a livello OS
    print("\n1. Controllo motore Tesseract OCR...")
    try:
        import pytesseract

        version = pytesseract.get_tesseract_version()
        print(f"   ✅ Tesseract OCR rilevato (Versione: {version})")
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"   ⚠️ Tesseract non rilevato o libreria OS non configurata: {e}")

    # 2. Verifica spaCy e Modello Linguistico
    print("\n2. Controllo spaCy & Modello NLP...")
    try:
        import spacy

        spacy_nlp = spacy.load("en_core_web_lg")
        print(
            f"   ✅ spaCy {spacy.__version__} ({spacy_nlp.lang}) e modello 'en_core_web_lg' caricati con successo!"
        )
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"   ⚠️ spaCy / modello 'en_core_web_lg' non caricato: {e}")

    # 3. Verifica Microsoft Presidio Analyzer & Redactor
    print("\n3. Controllo Microsoft Presidio SDK...")
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_image_redactor import ImageRedactorEngine

        analyzer = AnalyzerEngine()
        redactor = ImageRedactorEngine()
        print(
            f"   ✅ ImageRedactorEngine inizializzato: {redactor.__class__.__name__}"
        )

        # Test PII
        test_text = "Carta: 4532-1234-5678-9010, Email: test@example.com"
        results = analyzer.analyze(text=test_text, language="en")
        print(
            f"   ✅ Presidio Analyzer attivo! Entità rilevate: {len(results)}"
        )
        for r in results:
            print(f"      • {r.entity_type} (Score: {r.score:.2f})")
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"   ⚠️ Errore inizializzazione Presidio: {e}")

    print("\n================================================================")
    print("✨ Smoke Test completato!")
    print("================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
