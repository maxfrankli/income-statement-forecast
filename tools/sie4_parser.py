# tools/sie4_parser.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Iterable, Union, IO
from datetime import date, datetime
from pathlib import Path
import re

try:
    import pandas as pd  # valfritt; krävs bara för DataFrame-hjälpare
except ImportError:
    pd = None


# ---------------------------
# Domänmodell
# ---------------------------

@dataclass
class Account:
    number: str
    name: str = ""
    parent: Optional["Account"] = None
    children: List["Account"] = field(default_factory=list)
    sru: Optional[str] = None
    opening_balance: Optional[float] = None  # #IB
    closing_balance: Optional[float] = None  # #UB

    def lineage(self) -> List["Account"]:
        node, chain = self, []
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


@dataclass
class Transaction:
    account: str
    amount: float
    dim: Optional[Tuple[str, ...]] = None  # råa “dimensioner”/metadata
    text: Optional[str] = None


@dataclass
class Voucher:
    series: str
    number: str
    date: date
    text: str = ""
    reg_date: Optional[date] = None
    transactions: List[Transaction] = field(default_factory=list)


@dataclass
class RAR:  # Räkenskapsår
    idx: int
    start: date
    end: date


@dataclass
class Company:
    orgnr: Optional[str] = None
    name: Optional[str] = None
    program: Optional[str] = None
    sietyp: Optional[str] = None
    format: Optional[str] = None
    generated: Optional[date] = None
    rars: List[RAR] = field(default_factory=list)
    accounts: Dict[str, Account] = field(default_factory=dict)
    vouchers: List[Voucher] = field(default_factory=list)
    source_encoding: Optional[str] = None  # <-- ny: vilken encoding som lyckades

    # --- Pandas helpers ---
    def to_pandas_accounts(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for acc in self.accounts.values():
            parent = acc.parent.number if acc.parent else None
            rows.append({
                "account": acc.number,
                "name": acc.name,
                "parent": parent,
                "sru": acc.sru,
                "opening_balance": acc.opening_balance,
                "closing_balance": acc.closing_balance,
            })
        return pd.DataFrame(rows).sort_values("account")

    def to_pandas_vouchers(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for v in self.vouchers:
            rows.append({
                "series": v.series,
                "number": v.number,
                "date": pd.to_datetime(v.date),
                "text": v.text,
                "reg_date": pd.to_datetime(v.reg_date) if v.reg_date else None,
                "n_transactions": len(v.transactions),
            })
        return pd.DataFrame(rows).sort_values(["date", "series", "number"])

    def to_pandas_transactions(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for v in self.vouchers:
            for i, t in enumerate(v.transactions, start=1):
                rows.append({
                    "series": v.series,
                    "number": v.number,
                    "voucher_date": pd.to_datetime(v.date),
                    "voucher_text": v.text,
                    "tx_index": i,
                    "account": t.account,
                    "amount": t.amount,
                    "dim": t.dim,
                    "text": t.text,
                })
        df = pd.DataFrame(rows)
        if not df.empty:
            df["month"] = df["voucher_date"].dt.to_period("M").astype(str)
        return df

    def to_pandas_monthly_by_account(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        tx = self.to_pandas_transactions()
        if tx.empty:
            return tx
        pivot = (tx
                 .groupby(["account", "month"], as_index=False)["amount"]
                 .sum()
                 .pivot(index="account", columns="month", values="amount")
                 .fillna(0.0)
                 .sort_index())
        acc = self.to_pandas_accounts().set_index("account")[["name"]]
        return acc.join(pivot, how="left").fillna(0.0)


# ---------------------------
# SIE4 Parser
# ---------------------------

class SIE4Parser:
    """
    Robust SIE4-parser.
    Stöd: #FLAGGA, #PROGRAM, #FORMAT, #GEN, #SIETYP, #ORGNR, #FNAMN, #RAR,
          #KONTO, #SRU, #IB, #UB, #VER { #TRANS ... }.
    Tålig mot extra tokens/klamrar och olika decimaltecken.
    """

    _num_re = re.compile(r'^[+-]?\d+(?:[.,]\d+)?$')

    # Standardordning på encodings vi testar:
    DEFAULT_ENCODINGS: Tuple[str, ...] = ("utf-8", "cp865", "cp1252", "latin1")

    def __init__(self, infer_account_hierarchy: bool = True):
        self.infer_account_hierarchy = infer_account_hierarchy

    # --- Publika indata-varianter ---

    def parse_text(self, text: str) -> Company:
        lines = self._normalize_lines(text)
        company = self._parse_lines(lines)
        # text-sträng: encoding okänd (lämna None)
        return company

    def parse_bytes(self, data: bytes,
                    encoding_candidates: Iterable[str] = DEFAULT_ENCODINGS) -> Company:
        text, enc = self._decode_with_guess(data, encoding_candidates)
        company = self.parse_text(text)
        company.source_encoding = enc
        return company

    def parse_file(self, path: Union[str, Path],
                   encoding_candidates: Iterable[str] = DEFAULT_ENCODINGS) -> Company:
        p = Path(path)
        data = p.read_bytes()
        return self.parse_bytes(data, encoding_candidates)

    def parse(self, source: Union[str, bytes, Path, IO[str], IO[bytes]]) -> Company:
        """
        Autodetekterar:
          - str: om fil finns -> fil, annars behandlas som SIE-text
          - bytes: tolkas via parse_bytes
          - Path: parse_file
          - file-like: read() -> bytes eller str
        """
        if hasattr(source, "read"):  # file-like
            content = source.read()
            if isinstance(content, bytes):
                return self.parse_bytes(content, self.DEFAULT_ENCODINGS)
            return self.parse_text(str(content))

        if isinstance(source, Path):
            return self.parse_file(source, self.DEFAULT_ENCODINGS)

        if isinstance(source, (bytes, bytearray)):
            return self.parse_bytes(bytes(source), self.DEFAULT_ENCODINGS)

        if isinstance(source, str):
            p = Path(source)
            if p.exists() and p.is_file():
                return self.parse_file(p, self.DEFAULT_ENCODINGS)
            return self.parse_text(source)

        raise TypeError(f"Unsupported source type: {type(source)!r}")

    # --- Intern parsning ---

    def _parse_lines(self, lines: List[str]) -> Company:
        company = Company()
        current_voucher: Optional[Voucher] = None

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(";;"):  # kommentar
                continue

            # block-delimiter
            if line == "{":
                # Vi väntar på #TRANS-rader efter #VER
                continue
            if line == "}":
                if current_voucher:
                    company.vouchers.append(current_voucher)
                    current_voucher = None
                continue

            if not line.startswith("#"):
                continue

            cmd, args = self._split_command(line)

            if cmd == "#FLAGGA":
                pass
            elif cmd == "#PROGRAM":
                company.program = " ".join(a for a in args if a).strip()
            elif cmd == "#FORMAT":
                company.format = args[0] if args else None
            elif cmd == "#GEN":
                company.generated = self._parse_date(args[0]) if args else None
            elif cmd == "#SIETYP":
                company.sietyp = args[0] if args else None
            elif cmd == "#ORGNR":
                company.orgnr = args[0] if args else None
            elif cmd == "#FNAMN":
                company.name = self._strip_quotes(args[0]) if args else None
            elif cmd == "#RAR":
                rar = RAR(idx=int(args[0]),
                          start=self._parse_date(args[1]),
                          end=self._parse_date(args[2]))
                company.rars.append(rar)
            elif cmd == "#KONTO":
                acc_no = args[0]
                acc_name = self._strip_quotes(args[1]) if len(args) > 1 else ""
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.name = acc_name or acc.name
                company.accounts[acc_no] = acc
            elif cmd == "#SRU":
                if len(args) >= 2:
                    acc_no, sru = args[0], args[1]
                    acc = company.accounts.get(acc_no) or Account(number=acc_no)
                    acc.sru = sru
                    company.accounts[acc_no] = acc
            elif cmd == "#IB":
                # #IB <konto> <belopp> [extra]
                acc_no = args[0]
                amount = self._first_number(args, start_idx=1)
                if amount is None:
                    continue
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.opening_balance = amount
                company.accounts[acc_no] = acc
            elif cmd == "#UB":
                # #UB <konto> <belopp> [extra]
                acc_no = args[0]
                amount = self._first_number(args, start_idx=1)
                if amount is None:
                    continue
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.closing_balance = amount
                company.accounts[acc_no] = acc
            elif cmd == "#VER":
                # #VER A 1 20240110 "Text" 20240110
                series = args[0]
                number = args[1]
                vdate = self._parse_date(args[2])
                text = self._strip_quotes(args[3]) if len(args) > 3 else ""
                reg_date = self._parse_date(args[4]) if len(args) > 4 else None
                current_voucher = Voucher(series=series, number=number, date=vdate, text=text, reg_date=reg_date)
            elif cmd == "#TRANS":
                # #TRANS <konto> <belopp> ["text"] [dim...]
                if current_voucher is None:
                    # Malformad fil; hoppa över
                    continue
                acc_no = args[0]
                amount = self._first_number(args, start_idx=1)
                if amount is None:
                    # hoppa över trasig rad i stället för att krascha
                    continue

                # Hämta citerad text om den finns
                tx_text = None
                for t in args[1:]:
                    if self._is_quoted(t):
                        tx_text = self._strip_quotes(t)
                        break

                # Grovt bevara övriga icke-tals/icke-citerade tokens som "dimensioner"
                dims = tuple(a for a in args[1:]
                             if not self._num_re.match(a)
                             and not self._is_quoted(a)
                             and a not in ("{", "}", "{}"))

                current_voucher.transactions.append(
                    Transaction(account=acc_no, amount=float(str(amount).replace(",", ".")),
                                dim=dims or None, text=tx_text)
                )
            else:
                # Ignorera övriga taggar tills vidare (#RES, #OBJEKT, #KUND, ...)
                pass

        if self.infer_account_hierarchy and company.accounts:
            self._build_account_hierarchy(company.accounts)
        return company

    # ---------------------------
    # Hjälpare
    # ---------------------------

    @staticmethod
    def _normalize_lines(text: str) -> List[str]:
        return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    @staticmethod
    def _parse_date(s: str) -> date:
        s = re.sub(r'[^0-9]', '', s)
        return datetime.strptime(s, "%Y%m%d").date()

    @staticmethod
    def _strip_quotes(s: str) -> str:
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return s[1:-1]
        return s

    @staticmethod
    def _is_quoted(s: str) -> bool:
        return len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]

    @staticmethod
    def _split_command(line: str) -> Tuple[str, List[str]]:
        """
        Dela upp '#CMD args...' i (cmd, args) med citat-medveten tokenisering.
        """
        m = re.match(r"^(#[A-Z0-9]+)\s*(.*)$", line, re.IGNORECASE)
        if not m:
            return line, []
        cmd, rest = m.group(1), m.group(2)

        args: List[str] = []
        i, n = 0, len(rest)
        while i < n:
            while i < n and rest[i].isspace():
                i += 1
            if i >= n:
                break
            if rest[i] in ("'", '"'):
                q = rest[i]
                i += 1
                buf = []
                while i < n:
                    ch = rest[i]
                    if ch == q:
                        break
                    buf.append(ch)
                    i += 1
                args.append(q + "".join(buf) + q)
                i += 1  # hoppa över avslutande citat
            else:
                start = i
                while i < n and not rest[i].isspace():
                    i += 1
                args.append(rest[start:i])
        return cmd.upper(), args

    def _decode_with_guess(self, data: bytes, encodings: Iterable[str]) -> Tuple[str, str]:
        """
        Testa flera encodings och returnera (text, lyckad_encoding).
        Ordningen styrs av DEFAULT_ENCODINGS; inkluderar cp865 för OEM 865.
        """
        last_exc = None
        for enc in encodings:
            try:
                text = data.decode(enc)
                return text, enc
            except Exception as e:
                last_exc = e
                continue
        # Fallback: latin1 med ersättningstecken, men markera som 'latin1-replace'
        text = data.decode("latin1", errors="replace")
        return text, "latin1-replace"

    def _first_number(self, tokens: List[str], start_idx: int = 0) -> Optional[float]:
        """
        Hitta första token som ser ut som ett tal (t.ex. -1000,00 eller 1000.00).
        Ignorerar klammerbrus och icke-numeriska tokens.
        """
        for t in tokens[start_idx:]:
            tt = t.strip()
            if tt in ('{', '}', '{}'):
                continue
            if self._num_re.match(tt):
                try:
                    return float(tt.replace(',', '.'))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _build_account_hierarchy(accounts: Dict[str, Account]) -> None:
        # Skapa parent/child med numeriska prefix (BAS)
        for num, acc in list(accounts.items()):
            if not num.isdigit() or len(num) == 1:
                continue
            if len(num) >= 4:
                prefs = [num[:3], num[:2], num[:1]]
            elif len(num) == 3:
                prefs = [num[:2], num[:1]]
            else:  # len == 2
                prefs = [num[:1]]
            for p in prefs:
                parent = accounts.get(p)
                if parent and parent is not acc and acc.parent is None:
                    acc.parent = parent
                    if acc not in parent.children:
                        parent.children.append(acc)
                    break
        # Top-nivå (1-siffriga) saknar parent
        for num, acc in accounts.items():
            if num.isdigit() and len(num) == 1:
                acc.parent = None


# ---------------------------
# Snabb CLI-test (frivilligt)
# ---------------------------
if __name__ == "__main__":
    import sys
    parser = SIE4Parser()
    if len(sys.argv) == 2:
        src = sys.argv[1]
        company = parser.parse(src)  # funkar med filväg eller SIE-text
    else:
        demo = """#SIETYP 4
#FNAMN "Demo ÅÄÖ AB"
#ORGNR 556000-0000
#RAR 1 20240101 20241231
#KONTO 3001 "Försäljning åäö"
#KONTO 1930 "Bank"
#IB 1930 {} 10000,00
#VER A 1 20240301 "Faktura 1001 – ÅÄÖ" 20240301
{
#TRANS 1930 {} -1000,00 "Inbetalning åäö" {OBJEKT 1 10}
#TRANS 3001 1000.00 "Intäkt åäö"
}
#UB 1930 9000,00 {}
"""
        # Simulera OEM865: koda till cp865-bytes och låt parsern autodetektera
        data = demo.encode("cp865", errors="replace")
        company = parser.parse_bytes(data)

    print(f"Company: {company.name} ({company.orgnr}) – SIETYP {company.sietyp} – encoding: {company.source_encoding}")
    if pd:
        print(company.to_pandas_vouchers().head())
