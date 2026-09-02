from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReceiptItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=150, description="Nome articolo")
    amount_cents: int = Field(
        gt=0, description="Prezzo totale voce in centesimi interi"
    )
    quantity: int = Field(default=1, ge=1, description="Quantità acquistata")
    category: str | None = Field(
        default=None,
        description="Categoria merceologica dell'articolo (es. Alimentari, Casa)",
    )
    category_hint: str | None = Field(
        default=None, description="Suggerimento categoria (retrocompatibilità)"
    )


class ReceiptExtractionResponse(BaseModel):
    model_config = ConfigDict(frozen=False)

    merchant_name: str = Field(
        min_length=1, max_length=150, description="Esercente o negozio"
    )
    expense_date: date | None = Field(
        default=None, description="Data emissione scontrino"
    )
    total_amount_cents: int = Field(gt=0, description="Totale complessivo in centesimi")
    currency: str = Field(
        default="EUR", min_length=3, max_length=3, description="Valuta ISO"
    )
    items: list[ReceiptItem] = Field(
        default_factory=list, description="Lista singole voci"
    )
    category_suggestion: str | None = Field(
        default=None, description="Categoria macro suggerita per la spesa"
    )
    tax_amount_cents: int | None = Field(
        default=None, ge=0, description="Importo IVA in centesimi"
    )
    payment_method: str | None = Field(default=None, description="Metodo di pagamento")
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Indice di confidenza (0.0 - 1.0)",
    )
    validation_warning: bool = Field(
        default=False,
        description="True se le voci differiscono dal totale di oltre 0.05€",
    )
    validation_mismatch: bool = Field(
        default=False,
        description="True se le voci differiscono dal totale",
    )
    items_sum_cents: int = Field(
        default=0, description="Somma calcolata delle singole voci"
    )

    @model_validator(mode="after")
    def check_arithmetic_consistency(self) -> Self:
        """Verifica la quadratura con soglia di tolleranza di 0.05€."""
        if self.items:
            calculated_sum = sum(
                item.amount_cents * item.quantity for item in self.items
            )
            self.items_sum_cents = calculated_sum
            diff_cents = abs(calculated_sum - self.total_amount_cents)

            # AC: se differisce di oltre 0.05€ (5 centesimi), validation_warning = True
            self.validation_warning = diff_cents > 5
            self.validation_mismatch = diff_cents > 0
        else:
            self.items_sum_cents = self.total_amount_cents
            self.validation_warning = False
            self.validation_mismatch = False
        return self
