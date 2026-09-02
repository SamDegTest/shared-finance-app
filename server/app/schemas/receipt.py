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
    category_hint: str | None = Field(
        default=None, description="Suggerimento categoria"
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
    validation_mismatch: bool = Field(
        default=False,
        description="True se la somma delle voci differisce dal totale",
    )
    items_sum_cents: int = Field(
        default=0, description="Somma calcolata delle singole voci"
    )

    @model_validator(mode="after")
    def check_arithmetic_consistency(self) -> Self:
        """Verifica la quadratura tra somma voci e totale dichiarato."""
        if self.items:
            calculated_sum = sum(
                item.amount_cents * item.quantity for item in self.items
            )
            self.items_sum_cents = calculated_sum
            self.validation_mismatch = calculated_sum != self.total_amount_cents
        else:
            self.items_sum_cents = self.total_amount_cents
            self.validation_mismatch = False
        return self
