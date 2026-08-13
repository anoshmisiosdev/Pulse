"""Import the public UCI Online Retail workbook into Churnary's normalized model.

The source workbook contains 541k line items, so this adapter streams the XLSX
worksheet XML and aggregates line items into invoice-level payments. It uses only
the Python standard library and keeps at most the selected customers/payments in
the returned ``SyncResult``.

Dataset: https://archive.ics.uci.edu/dataset/352/online+retail
License: CC BY 4.0
"""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile

from app.integrations.base import IntegrationError
from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)

SOURCE = "uci_online_retail"
DATASET_URL = "https://archive.ics.uci.edu/dataset/352/online+retail"
DATASET_DOI = "https://doi.org/10.24432/C5BW33"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"([A-Z]+)")


@dataclass(frozen=True)
class OnlineRetailRow:
    invoice_no: str
    description: str | None
    quantity: Decimal
    invoice_at: datetime
    unit_price: Decimal
    customer_id: str


@dataclass
class _Invoice:
    invoice_no: str
    customer_id: str
    occurred_at: datetime
    gross: Decimal = Decimal("0")
    refunded: Decimal = Decimal("0")


@dataclass
class _CustomerStats:
    first_seen: datetime
    last_seen: datetime
    item_value: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError) as exc:
        raise IntegrationError(f"Invalid numeric value in UCI workbook: {value!r}") from exc


def _identifier(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _excel_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    try:
        serial = float(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationError(f"Invalid invoice date in UCI workbook: {value!r}") from exc
    # Excel's 1900 date system includes the historic leap-year compatibility bug.
    return (datetime(1899, 12, 30, tzinfo=UTC) + timedelta(days=serial))


def _column_index(reference: str) -> int:
    match = _CELL_REF.match(reference)
    if match is None:
        raise IntegrationError(f"Invalid XLSX cell reference: {reference!r}")
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        stream = archive.open("xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: list[str] = []
    with stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if element.tag == f"{_SHEET_NS}si":
                strings.append(
                    "".join(
                        node.text or ""
                        for node in element.iter()
                        if node.tag == f"{_SHEET_NS}t"
                    )
                )
                element.clear()
    return strings


def _cell_value(cell: ET.Element, shared: list[str]) -> object:
    cell_type = cell.attrib.get("t")
    value_node = cell.find(f"{_SHEET_NS}v")
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as exc:
            raise IntegrationError("UCI workbook contains an invalid shared string") from exc
    if cell_type in {"str", "inlineStr"}:
        return raw
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number


def iter_online_retail_xlsx(path: str | Path) -> Iterator[OnlineRetailRow]:
    """Stream the UCI workbook without loading its 541k rows into memory."""
    try:
        archive = ZipFile(path)
    except (OSError, ValueError) as exc:
        raise IntegrationError(f"Could not open UCI workbook: {exc}") from exc

    with archive:
        shared = _shared_strings(archive)
        try:
            stream = archive.open("xl/worksheets/sheet1.xml")
        except KeyError as exc:
            raise IntegrationError("UCI workbook is missing its first worksheet") from exc
        with stream:
            header: dict[int, str] | None = None
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag != f"{_SHEET_NS}row":
                    continue
                values: dict[int, object] = {}
                for cell in element.findall(f"{_SHEET_NS}c"):
                    values[_column_index(cell.attrib.get("r", ""))] = _cell_value(cell, shared)
                element.clear()
                if header is None:
                    header = {column: str(value or "").strip() for column, value in values.items()}
                    continue
                by_name = {
                    header[column]: value
                    for column, value in values.items()
                    if column in header
                }
                customer_id = _identifier(by_name.get("CustomerID"))
                invoice_no = _identifier(by_name.get("InvoiceNo"))
                if not customer_id or not invoice_no or by_name.get("InvoiceDate") is None:
                    continue
                yield OnlineRetailRow(
                    invoice_no=invoice_no,
                    description=str(by_name.get("Description") or "").strip() or None,
                    quantity=_as_decimal(by_name.get("Quantity")),
                    invoice_at=_excel_datetime(by_name.get("InvoiceDate")),
                    unit_price=_as_decimal(by_name.get("UnitPrice")),
                    customer_id=customer_id,
                )


def _stratified_customer_ids(
    invoices_by_customer: dict[str, list[_Invoice]], max_customers: int | None
) -> list[str]:
    eligible = [
        customer_id
        for customer_id, invoices in invoices_by_customer.items()
        if sum(1 for invoice in invoices if invoice.gross > invoice.refunded) >= 2
    ]
    eligible.sort(
        key=lambda customer_id: max(
            invoice.occurred_at for invoice in invoices_by_customer[customer_id]
        )
    )
    if max_customers is None or len(eligible) <= max_customers:
        return eligible

    selected: list[str] = []
    # Draw from lapsed, middle, and recent thirds so the sample produces a useful
    # mix of retention states rather than only the largest active accounts.
    allocations = [max_customers // 3] * 3
    for index in range(max_customers % 3):
        allocations[2 - index] += 1
    for bucket_index, allocation in enumerate(allocations):
        start = len(eligible) * bucket_index // 3
        end = len(eligible) * (bucket_index + 1) // 3
        bucket = eligible[start:end]
        bucket.sort(
            key=lambda customer_id: (
                -sum(
                    1
                    for invoice in invoices_by_customer[customer_id]
                    if invoice.gross > invoice.refunded
                ),
                customer_id,
            )
        )
        selected.extend(bucket[:allocation])
    return selected


def build_online_retail_sync(
    rows: Iterable[OnlineRetailRow],
    *,
    max_customers: int | None = 60,
    max_transactions_per_customer: int | None = 48,
) -> SyncResult:
    """Aggregate UCI line items into customer, payment, and visit records."""
    invoices: dict[tuple[str, str], _Invoice] = {}
    customers: dict[str, _CustomerStats] = {}
    line_count = 0

    for row in rows:
        line_count += 1
        invoice_key = (row.customer_id, row.invoice_no)
        invoice = invoices.setdefault(
            invoice_key,
            _Invoice(
                invoice_no=row.invoice_no,
                customer_id=row.customer_id,
                occurred_at=row.invoice_at,
            ),
        )
        invoice.occurred_at = min(invoice.occurred_at, row.invoice_at)
        line_value = row.quantity * row.unit_price
        if row.invoice_no.upper().startswith("C") or line_value < 0:
            invoice.refunded += abs(line_value)
        else:
            invoice.gross += line_value

        stats = customers.get(row.customer_id)
        if stats is None:
            stats = _CustomerStats(first_seen=row.invoice_at, last_seen=row.invoice_at)
            customers[row.customer_id] = stats
        stats.first_seen = min(stats.first_seen, row.invoice_at)
        stats.last_seen = max(stats.last_seen, row.invoice_at)
        if row.description and line_value > 0:
            stats.item_value[row.description] += line_value

    invoices_by_customer: dict[str, list[_Invoice]] = defaultdict(list)
    for invoice in invoices.values():
        if invoice.gross > 0 or invoice.refunded > 0:
            invoices_by_customer[invoice.customer_id].append(invoice)

    selected_ids = _stratified_customer_ids(invoices_by_customer, max_customers)
    result = SyncResult()
    for customer_id in selected_ids:
        stats = customers[customer_id]
        favorite_item = (
            max(stats.item_value.items(), key=lambda pair: (pair[1], pair[0]))[0]
            if stats.item_value
            else None
        )
        result.customers.append(
            NormalizedCustomer(
                external_id=customer_id,
                source=SOURCE,
                first_name="UCI",
                last_name=f"Customer {customer_id}",
                created_at=stats.first_seen,
                favorite_item=favorite_item,
            )
        )
        customer_invoices = sorted(
            invoices_by_customer[customer_id], key=lambda invoice: invoice.occurred_at, reverse=True
        )
        if max_transactions_per_customer is not None:
            customer_invoices = customer_invoices[:max_transactions_per_customer]
        for invoice in sorted(customer_invoices, key=lambda item: item.occurred_at):
            if invoice.refunded > 0 and invoice.gross > invoice.refunded:
                status = "partially_refunded"
                amount = invoice.gross - invoice.refunded
                gross = invoice.gross
            elif invoice.refunded > 0:
                status = "refunded"
                amount = Decimal("0")
                gross = max(invoice.gross, invoice.refunded)
            else:
                status = "completed"
                amount = invoice.gross
                gross = invoice.gross
            external_id = f"uci-{invoice.customer_id}-{invoice.invoice_no}"
            transaction = NormalizedTransaction(
                external_id=external_id,
                source=SOURCE,
                customer_external_id=customer_id,
                amount=amount,
                gross_amount=gross,
                refunded_amount=invoice.refunded,
                currency="GBP",
                status=status,
                occurred_at=invoice.occurred_at,
                updated_at=invoice.occurred_at,
            )
            result.transactions.append(transaction)
            if transaction.is_revenue:
                result.visits.append(
                    NormalizedVisit(
                        external_id=f"visit-{external_id}",
                        source=SOURCE,
                        customer_external_id=customer_id,
                        occurred_at=invoice.occurred_at,
                    )
                )

    result.warnings.extend(
        [
            (
                f"Public UCI Online Retail sample: {line_count:,} identified line items; "
                f"selected {len(result.customers):,} customers and "
                f"{len(result.transactions):,} invoice-level payments."
            ),
            f"Source: {DATASET_DOI} (CC BY 4.0). Customer names are generated labels.",
        ]
    )
    return result


def parse_online_retail_xlsx(
    path: str | Path,
    *,
    max_customers: int | None = 60,
    max_transactions_per_customer: int | None = 48,
) -> SyncResult:
    return build_online_retail_sync(
        iter_online_retail_xlsx(path),
        max_customers=max_customers,
        max_transactions_per_customer=max_transactions_per_customer,
    )


def rebase_sync(sync: SyncResult, *, now: datetime | None = None) -> SyncResult:
    """Move a historical sample near today while preserving every interval."""
    event_dates = [transaction.occurred_at for transaction in sync.transactions]
    if not event_dates:
        return sync.model_copy(deep=True)
    anchor = now or datetime.now(UTC)
    anchor = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor.astimezone(UTC)
    latest = max(
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        for value in event_dates
    )
    delta = anchor - timedelta(days=1) - latest
    rebased = sync.model_copy(deep=True)
    for customer in rebased.customers:
        if customer.created_at:
            customer.created_at = customer.created_at + delta
    for transaction in rebased.transactions:
        transaction.occurred_at = transaction.occurred_at + delta
        if transaction.updated_at:
            transaction.updated_at = transaction.updated_at + delta
    for visit in rebased.visits:
        visit.occurred_at = visit.occurred_at + delta
    return rebased


_FIXTURE_FIELDS = (
    "customer_id",
    "customer_name",
    "joined_at",
    "favorite_item",
    "transaction_id",
    "occurred_at",
    "amount",
    "gross_amount",
    "refunded_amount",
    "status",
    "currency",
)


def export_sample_csv(sync: SyncResult, path: str | Path) -> None:
    """Write a compact, auditable invoice-level fixture derived from UCI."""
    customers = {customer.external_id: customer for customer in sync.customers}
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIXTURE_FIELDS)
        writer.writeheader()
        for transaction in sync.transactions:
            customer = customers.get(transaction.customer_external_id)
            writer.writerow(
                {
                    "customer_id": transaction.customer_external_id,
                    "customer_name": customer.full_name if customer else "UCI Customer",
                    "joined_at": (
                        customer.created_at.isoformat()
                        if customer and customer.created_at
                        else ""
                    ),
                    "favorite_item": customer.favorite_item if customer else "",
                    "transaction_id": transaction.external_id,
                    "occurred_at": transaction.occurred_at.isoformat(),
                    "amount": transaction.amount,
                    "gross_amount": transaction.gross_amount,
                    "refunded_amount": transaction.refunded_amount,
                    "status": transaction.status,
                    "currency": transaction.currency,
                }
            )


def load_sample_csv(path: str | Path, *, now: datetime | None = None) -> SyncResult:
    """Load the repository's attributed UCI invoice sample and rebase it."""
    result = SyncResult()
    customers: dict[str, NormalizedCustomer] = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            customer_id = (row.get("customer_id") or "").strip()
            transaction_id = (row.get("transaction_id") or "").strip()
            if not customer_id or not transaction_id:
                continue
            if customer_id not in customers:
                name = (row.get("customer_name") or "").split(" ", 1)
                customers[customer_id] = NormalizedCustomer(
                    external_id=customer_id,
                    source=SOURCE,
                    first_name=name[0] if name else "UCI",
                    last_name=name[1] if len(name) > 1 else None,
                    created_at=datetime.fromisoformat(row["joined_at"]),
                    favorite_item=row.get("favorite_item") or None,
                )
            transaction = NormalizedTransaction(
                external_id=transaction_id,
                source=SOURCE,
                customer_external_id=customer_id,
                amount=_as_decimal(row.get("amount")),
                gross_amount=_as_decimal(row.get("gross_amount")),
                refunded_amount=_as_decimal(row.get("refunded_amount")),
                status=row.get("status") or "completed",
                currency=row.get("currency") or "GBP",
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            result.transactions.append(transaction)
            if transaction.is_revenue:
                result.visits.append(
                    NormalizedVisit(
                        external_id=f"visit-{transaction_id}",
                        source=SOURCE,
                        customer_external_id=customer_id,
                        occurred_at=transaction.occurred_at,
                    )
                )
    result.customers = list(customers.values())
    result.warnings.extend(
        [
            "Loaded an attributed subset of the public UCI Online Retail dataset.",
            f"Source: {DATASET_DOI} (CC BY 4.0). Customer names are generated labels.",
        ]
    )
    return rebase_sync(result, now=now)
